// ignore_for_file: experimental_member_use

import 'dart:async';
import 'dart:io' as io;

import 'package:flet/flet.dart';
import 'package:flutter/material.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill_extensions/flutter_quill_extensions.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:markdown_quill/markdown_quill.dart';
import 'package:path/path.dart' as path;

class FletQuillEditorControl extends StatefulWidget {
  final Control control;

  FletQuillEditorControl({Key? key, required this.control})
      : super(key: key ?? ValueKey('control_${control.id}'));

  @override
  State<FletQuillEditorControl> createState() =>
      _FletQuillEditorControlState();
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
    final filename =
        'clipboard-${DateTime.now().microsecondsSinceEpoch}.png';
    final destination = io.File(path.join(directory.path, filename));
    await destination.writeAsBytes(imageBytes, flush: true);

    final prefix = widget.control.getString('image_link_prefix', '')!;
    return prefix.isEmpty
        ? filename
        : path.posix.join(prefix.replaceAll('\\', '/'), filename);
  }

  ImageProvider? _localImageProvider(BuildContext context, String imageUrl) {
    if (imageUrl.startsWith('http://') ||
        imageUrl.startsWith('https://') ||
        imageUrl.startsWith('data:') ||
        imageUrl.startsWith('assets/')) {
      return null;
    }
    final documentDirectory =
        widget.control.getString('document_directory', '')!;
    if (documentDirectory.isEmpty) return null;
    final platformPath = imageUrl.replaceAll('/', path.separator);
    final resolved = path.isAbsolute(platformPath)
        ? platformPath
        : path.normalize(path.join(documentDirectory, platformPath));
    return FileImage(io.File(resolved));
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
          imageEmbedConfig: QuillEditorImageEmbedConfig(
            imageProviderBuilder: _localImageProvider,
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
