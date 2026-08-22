from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from flet_quill_editor import FletQuillEditor

from flet_app import build_markdown_editor
from markdown_store import MarkdownStore


class QuillEditorIntegrationTests(unittest.TestCase):
    def test_local_preview_uses_renderable_text_fallback(self) -> None:
        editor = build_markdown_editor(
            value="**正文**",
            placeholder="输入 Markdown",
            document_directory=".",
            image_directory=".",
            image_link_prefix="./assets",
            use_native_quill=False,
        )

        self.assertEqual(editor.__class__.__name__, "TextField")
        self.assertEqual(editor.data, "markdown-editor")
        self.assertEqual(editor.value, "**正文**")

    def test_native_build_uses_quill_editor(self) -> None:
        editor = build_markdown_editor(
            value="正文",
            placeholder="输入 Markdown",
            document_directory=".",
            image_directory=".",
            image_link_prefix="./assets",
            use_native_quill=True,
        )

        self.assertIsInstance(editor, FletQuillEditor)
        self.assertEqual(editor.data, "markdown-editor")

    def test_editor_exposes_direct_autosave_events(self) -> None:
        paste_errors: list[str] = []
        render_errors: list[str] = []
        editor = FletQuillEditor(
            value="正文",
            placeholder="在这里直接记录……",
            autofocus=True,
            on_change=lambda _event: None,
            on_blur=lambda _event: None,
            on_paste_error=lambda event: paste_errors.append(event.data),
            on_render_error=lambda event: render_errors.append(event.data),
        )

        self.assertEqual(editor.value, "正文")
        self.assertTrue(editor.autofocus)
        self.assertIsNotNone(editor.on_change)
        self.assertIsNotNone(editor.on_blur)
        self.assertIsNotNone(editor.on_paste_error)
        self.assertIsNotNone(editor.on_render_error)

    def test_editor_image_context_is_durable_and_relative(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarkdownStore(Path(directory) / "markdown")

            image_directory, link_prefix = store.editor_image_context("task", 7)

            self.assertTrue(image_directory.is_dir())
            self.assertEqual(image_directory.name, "T0007")
            self.assertEqual(link_prefix, "../_assets/task/T0007")

    def test_legacy_bottom_gallery_images_enter_editor_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = MarkdownStore(Path(directory) / "markdown")
            store.write_user_edited(
                "task",
                7,
                "正文\n\n![](../_assets/task/T0007/old.png)\n",
            )

            migrated = store.editor_body_with_legacy_images("task", 7, "正文")
            repeated = store.editor_body_with_legacy_images("task", 7, migrated)

            self.assertEqual(
                migrated, "正文\n\n![](../_assets/task/T0007/old.png)"
            )
            self.assertEqual(repeated, migrated)


if __name__ == "__main__":
    unittest.main()
