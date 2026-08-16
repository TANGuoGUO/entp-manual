import 'dart:convert';

import 'package:flet_quill_editor/src/flet_quill_editor.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill_extensions/flutter_quill_extensions.dart';

void main() {
  test('Ctrl+V is routed to the image paste handler', () {
    final event = KeyDownEvent(
      logicalKey: LogicalKeyboardKey.keyV,
      physicalKey: PhysicalKeyboardKey.keyV,
      timeStamp: Duration.zero,
    );

    expect(
      isImagePasteShortcut(event, controlPressed: true, metaPressed: false),
      isTrue,
    );
  });

  test('plain V keeps Quill normal typing behavior', () {
    final event = KeyDownEvent(
      logicalKey: LogicalKeyboardKey.keyV,
      physicalKey: PhysicalKeyboardKey.keyV,
      timeStamp: Duration.zero,
    );

    expect(
      isImagePasteShortcut(event, controlPressed: false, metaPressed: false),
      isFalse,
    );
  });

  testWidgets('double-clicking an embedded image does not open an image dialog', (
    tester,
  ) async {
    const image = 'test-image';
    const imageBase64 =
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
    final document = Document()..insert(0, BlockEmbed.image(image));
    final controller = QuillController(
      document: document,
      selection: const TextSelection.collapsed(offset: 0),
    );
    final focusNode = FocusNode();
    final scrollController = ScrollController();
    addTearDown(() {
      controller.dispose();
      focusNode.dispose();
      scrollController.dispose();
    });

    final imageConfig = safeImageEmbedConfig(
      imageProviderBuilder: (_, __) => ResizeImage(
        MemoryImage(base64Decode(imageBase64)),
        width: 120,
        height: 80,
      ),
      imageErrorWidgetBuilder: (_, __, ___) => const SizedBox(height: 40),
    );
    await tester.pumpWidget(
      MaterialApp(
        localizationsDelegates: const [FlutterQuillLocalizations.delegate],
        home: Scaffold(
          body: SizedBox(
            width: 480,
            height: 320,
            child: QuillEditor(
              controller: controller,
              focusNode: focusNode,
              scrollController: scrollController,
              config: QuillEditorConfig(
                expands: true,
                scrollable: true,
                embedBuilders: FlutterQuillEmbeds.editorBuilders(
                  imageEmbedConfig: imageConfig,
                ),
              ),
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(Image), findsOneWidget);
    expect(imageConfig.onImageClicked, isNotNull);
    imageConfig.onImageClicked!(image);
    await tester.pump(const Duration(milliseconds: 50));
    imageConfig.onImageClicked!(image);
    await tester.pumpAndSettle();

    expect(find.byType(SimpleDialog), findsNothing);
    expect(find.byType(QuillEditor), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
