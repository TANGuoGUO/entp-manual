import 'package:flutter_test/flutter_test.dart';
import 'package:markdown/markdown.dart' as md;
import 'package:markdown_quill/markdown_quill.dart';

void main() {
  test('keeps a pasted image between the surrounding paragraphs', () {
    final document = md.Document(
      encodeHtml: false,
      extensionSet: md.ExtensionSet.gitHubFlavored,
    );
    final toDelta = MarkdownToDelta(markdownDocument: document);
    final toMarkdown = DeltaToMarkdown();
    const source = '第一段\n\n![](../_assets/task/T0001/paste.png)\n\n第二段';

    final roundTrip = toMarkdown.convert(toDelta.convert(source));

    final first = roundTrip.indexOf('第一段');
    final image = roundTrip.indexOf('../_assets/task/T0001/paste.png');
    final second = roundTrip.indexOf('第二段');
    expect(first, greaterThanOrEqualTo(0));
    expect(image, greaterThan(first));
    expect(second, greaterThan(image));
  });
}
