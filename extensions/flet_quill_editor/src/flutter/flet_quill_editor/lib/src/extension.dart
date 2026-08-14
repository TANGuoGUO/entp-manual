import 'package:flet/flet.dart';
import 'package:flutter/widgets.dart';

import 'flet_quill_editor.dart';

class Extension extends FletExtension {
  @override
  Widget? createWidget(Key? key, Control control) {
    switch (control.type) {
      case "FletQuillEditor":
        return FletQuillEditorControl(control: control);
      default:
        return null;
    }
  }
}
