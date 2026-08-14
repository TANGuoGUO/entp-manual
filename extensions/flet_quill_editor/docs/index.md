# Introduction

FletQuillEditor for Flet.

## Examples

```
import flet as ft

from flet_quill_editor import FletQuillEditor


def main(page: ft.Page):
    page.vertical_alignment = ft.MainAxisAlignment.CENTER
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER

    page.add(

                ft.Container(height=150, width=300, alignment = ft.Alignment.CENTER, bgcolor=ft.Colors.PURPLE_200, content=FletQuillEditor(
                    tooltip="My new FletQuillEditor Control tooltip",
                    value = "My new FletQuillEditor Flet Control",
                ),),

    )


ft.run(main)
```

## Classes

[FletQuillEditor](FletQuillEditor.md)
