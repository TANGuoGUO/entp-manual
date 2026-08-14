from typing import Optional

import flet as ft
from flet.controls.control_event import ControlEventHandler

@ft.control("FletQuillEditor")
class FletQuillEditor(ft.LayoutControl):
    """
    A thin Flet bridge around the open-source Flutter Quill editor.

    ``value`` is Markdown. Images pasted into the editor are written to
    ``image_directory`` and stored in Markdown using ``image_link_prefix``.
    """

    value: str = ""
    placeholder: str = ""
    document_directory: str = ""
    image_directory: str = ""
    image_link_prefix: str = ""
    autofocus: bool = False
    read_only: bool = False
    text_size: float = 16
    on_change: Optional[ControlEventHandler["FletQuillEditor"]] = None
    on_focus: Optional[ControlEventHandler["FletQuillEditor"]] = None
    on_blur: Optional[ControlEventHandler["FletQuillEditor"]] = None
