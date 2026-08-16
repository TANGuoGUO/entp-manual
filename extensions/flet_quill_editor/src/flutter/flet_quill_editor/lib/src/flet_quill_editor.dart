// ignore_for_file: experimental_member_use

import 'dart:async';
import 'dart:io' as io;

import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill_extensions/flutter_quill_extensions.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:markdown_quill/markdown_quill.dart';
import 'package:pasteboard/pasteboard.dart';
import 'package:path/path.dart' as path;

@visibleForTesting
bool isImagePasteShortcut(
  KeyEvent event, {
  bool? controlPressed,
  bool? metaPressed,
}) {
  final modifierPressed =
      (controlPressed ?? HardwareKeyboard.instance.isControlPressed) ||
      (metaPressed ?? HardwareKeyboard.instance.isMetaPressed);
  return event is KeyDownEvent &&
      event.logicalKey == LogicalKeyboardKey.keyV &&
      modifierPressed;
}

@visibleForTesting
QuillEditorImageEmbedConfig safeImageEmbedConfig({
  required ImageProvider? Function(BuildContext, String) imageProviderBuilder,
  required Widget Function(BuildContext, Object, StackTrace?)
  imageErrorWidgetBuilder,
}) {
  return QuillEditorImageEmbedConfig(
    imageProviderBuilder: imageProviderBuilder,
    imageErrorWidgetBuilder: imageErrorWidgetBuilder,
    // Suppress flutter_quill_extensions' ImageOptionsMenu. Opening that route
    // on the first click races Quill's selection gesture on the second click.
    onImageClicked: (_) {},
  );
}

class FletQuillEditorControl extends StatefulWidget {
  final Control control;

  FletQuillEditorControl({Key? key, required this.control})
    : super(key: key ?? ValueKey('control_${control.id}'));

  @override
  State<FletQuillEditorControl> createState() => _FletQuillEditorControlState();
}

class _FletQuillEditorControlState extends State<FletQuillEditorControl> {
  final _markdownDocument = md.Document(
    encodeHtml: false,
    extensionSet: md.ExtensionSet.gitHubFlavored,
  );
  late final MarkdownToDelta _markdownToDelta;
  late final DeltaToMarkdown _deltaToMarkdown;
  late final QuillController _controller;
  late final FocusNode _focusNode;
  late final ScrollController _scrollController;
  StreamSubscription<DocChange>? _documentSubscription;
  Timer? _changeTimer;
  String _value = '';
  bool _applyingRemoteValue = false;
  bool _imageRenderErrorReported = false;

  @override
  void initState() {
    super.initState();
    _markdownToDelta = MarkdownToDelta(markdownDocument: _markdownDocument);
    _deltaToMarkdown = DeltaToMarkdown();
    _value = widget.control.getString('value', '')!;
    _controller = QuillController(
      document: _documentFromMarkdown(_value),
      selection: const TextSelection.collapsed(offset: 0),
      config: QuillControllerConfig(
        clipboardConfig: QuillClipboardConfig(
          enableExternalRichPaste: true,
          onClipboardPaste: _pasteImageFromSystemClipboard,
          onImagePaste: _storePastedImage,
        ),
      ),
      readOnly: widget.control.getBool('read_only', false)!,
    );
    _focusNode = FocusNode()..addListener(_handleFocusChange);
    _scrollController = ScrollController();
    _listenToDocument();
    if (widget.control.getBool('autofocus', false)!) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) _focusNode.requestFocus();
      });
    }
    if (widget.control.getBool('paste_on_mount', false)!) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (mounted) unawaited(_pasteImageFromSystemClipboard());
      });
    }
  }

  Document _documentFromMarkdown(String value) {
    try {
      return Document.fromDelta(_markdownToDelta.convert(value));
    } catch (_) {
      return Document()..insert(0, value);
    }
  }

  void _listenToDocument() {
    _documentSubscription?.cancel();
    _documentSubscription = _controller.document.changes.listen((_) {
      if (_applyingRemoteValue) return;
      _changeTimer?.cancel();
      _changeTimer = Timer(const Duration(milliseconds: 360), _emitChange);
    });
  }

  void _emitChange() {
    if (!mounted) return;
    final value = _deltaToMarkdown.convert(_controller.document.toDelta());
    _value = value;
    widget.control.updateProperties({'value': value});
    if (widget.control.hasEventHandler('change')) {
      widget.control.triggerEvent('change', value);
    }
  }

  void _handleFocusChange() {
    if (!_focusNode.hasFocus && _changeTimer?.isActive == true) {
      _changeTimer?.cancel();
      _emitChange();
    }
    widget.control.triggerEvent(_focusNode.hasFocus ? 'focus' : 'blur');
  }

  Future<String?> _storePastedImage(List<int> imageBytes) async {
    final imageDirectory = widget.control.getString('image_directory', '')!;
    if (imageDirectory.isEmpty || imageBytes.isEmpty) return null;

    final directory = io.Directory(imageDirectory);
    await directory.create(recursive: true);
    final filename = 'clipboard-${DateTime.now().microsecondsSinceEpoch}.png';
    final destination = io.File(path.join(directory.path, filename));
    await destination.writeAsBytes(imageBytes, flush: true);

    final prefix = widget.control.getString('image_link_prefix', '')!;
    return prefix.isEmpty
        ? filename
        : path.posix.join(prefix.replaceAll('\\', '/'), filename);
  }

  Future<bool> _pasteImageFromSystemClipboard() async {
    try {
      // flutter_quill's Windows native bridge currently supports HTML but
      // not bitmap clipboard reads. pasteboard supplies the missing Windows
      // implementation while Quill still owns the keyboard shortcut and
      // selection behavior.
      final imageBytes = await Pasteboard.image;
      if (imageBytes == null || imageBytes.isEmpty) return false;

      final imageUrl = await _storePastedImage(imageBytes);
      if (imageUrl == null) {
        _reportPasteError('No image storage directory is configured.');
        return true;
      }

      final selection = _controller.selection;
      final offset = selection.isValid
          ? selection.start
          : _controller.document.length - 1;
      final replacedLength = selection.isValid && !selection.isCollapsed
          ? selection.end - selection.start
          : 0;
      _controller.replaceText(
        offset,
        replacedLength,
        BlockEmbed.image(imageUrl),
        TextSelection.collapsed(offset: offset + 1),
      );
      return true;
    } catch (error, stackTrace) {
      debugPrint('Failed to paste clipboard image: $error\n$stackTrace');
      _reportPasteError(error.toString());
      return true;
    }
  }

  KeyEventResult? _handleEditorKeyEvent(KeyEvent event, Node? node) {
    if (!isImagePasteShortcut(event)) {
      return null;
    }

    unawaited(_pasteImageOrDelegateToQuill());
    return KeyEventResult.handled;
  }

  Future<void> _pasteImageOrDelegateToQuill() async {
    final imageHandled = await _pasteImageFromSystemClipboard();
    if (!imageHandled) {
      // Preserve Quill's normal text, HTML and Markdown paste behavior when
      // the clipboard does not contain a bitmap.
      await _controller.clipboardPaste();
    }
  }

  void _reportPasteError(String message) {
    if (widget.control.hasEventHandler('paste_error')) {
      widget.control.triggerEvent('paste_error', message);
    }
  }

  ImageProvider? _localImageProvider(BuildContext context, String imageUrl) {
    if (imageUrl.startsWith('http://') ||
        imageUrl.startsWith('https://') ||
        imageUrl.startsWith('data:') ||
        imageUrl.startsWith('assets/')) {
      return null;
    }
    final documentDirectory = widget.control.getString(
      'document_directory',
      '',
    )!;
    if (documentDirectory.isEmpty) return null;
    final platformPath = imageUrl.replaceAll('/', path.separator);
    final resolved = path.isAbsolute(platformPath)
        ? platformPath
        : path.normalize(path.join(documentDirectory, platformPath));
    return FileImage(io.File(resolved));
  }

  Widget _buildImageErrorWidget(
    BuildContext context,
    Object error,
    StackTrace? stackTrace,
  ) {
    if (!_imageRenderErrorReported) {
      _imageRenderErrorReported = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (!mounted || !widget.control.hasEventHandler('render_error')) return;
        widget.control.triggerEvent('render_error', error.toString());
      });
    }
    return Container(
      constraints: const BoxConstraints(minHeight: 96),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F6F8),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: const Color(0xFFE1E4E9)),
      ),
      child: const Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.broken_image_outlined, color: Color(0xFF8A909A)),
          SizedBox(width: 10),
          Flexible(
            child: Text(
              '图片无法显示，其他内容仍可继续编辑',
              style: TextStyle(color: Color(0xFF737986), fontSize: 14),
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _changeTimer?.cancel();
    _documentSubscription?.cancel();
    _controller.dispose();
    _focusNode
      ..removeListener(_handleFocusChange)
      ..dispose();
    _scrollController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final remoteValue = widget.control.getString('value', '')!;
    if (remoteValue != _value) {
      _applyingRemoteValue = true;
      _value = remoteValue;
      _controller.document = _documentFromMarkdown(remoteValue);
      _listenToDocument();
      _applyingRemoteValue = false;
    }
    _controller.readOnly = widget.control.getBool('read_only', false)!;

    final placeholder = widget.control.getString('placeholder', '')!;
    final textSize = widget.control.getDouble('text_size', 16)!;
    final editor = QuillEditor(
      controller: _controller,
      focusNode: _focusNode,
      scrollController: _scrollController,
      config: QuillEditorConfig(
        autoFocus: widget.control.getBool('autofocus', false)!,
        onKeyPressed: _handleEditorKeyEvent,
        expands: true,
        scrollable: true,
        placeholder: placeholder,
        padding: const EdgeInsets.symmetric(horizontal: 2, vertical: 4),
        customStyles: DefaultStyles(
          paragraph: DefaultTextBlockStyle(
            TextStyle(
              fontFamily: 'Microsoft YaHei UI',
              fontSize: textSize,
              height: 1.55,
              color: const Color(0xFF20242C),
            ),
            const HorizontalSpacing(0, 0),
            const VerticalSpacing(0, 8),
            const VerticalSpacing(0, 0),
            null,
          ),
        ),
        embedBuilders: FlutterQuillEmbeds.editorBuilders(
          imageEmbedConfig: safeImageEmbedConfig(
            imageProviderBuilder: _localImageProvider,
            imageErrorWidgetBuilder: _buildImageErrorWidget,
          ),
        ),
      ),
    );

    return LayoutControl(
      control: widget.control,
      child: Localizations.override(
        context: context,
        delegates: const [FlutterQuillLocalizations.delegate],
        child: editor,
      ),
    );
  }
}
