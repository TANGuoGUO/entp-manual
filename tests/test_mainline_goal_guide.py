from __future__ import annotations

import unittest

import flet as ft

from flet_app import MAINLINE_GOAL_GUIDE, mainline_goal_guide_button


class MainlineGoalGuideTests(unittest.TestCase):
    def test_hover_guide_contains_the_three_approved_questions(self) -> None:
        button = mainline_goal_guide_button()

        self.assertIsInstance(button, ft.IconButton)
        self.assertIsInstance(button.tooltip, ft.Tooltip)
        self.assertEqual(button.tooltip.message, MAINLINE_GOAL_GUIDE)
        self.assertEqual(MAINLINE_GOAL_GUIDE.count("这样问，是为了"), 3)
        self.assertIn("基础、经验、兴趣", MAINLINE_GOAL_GUIDE)
        self.assertIn("给我之外的人或世界带来什么", MAINLINE_GOAL_GUIDE)
        self.assertIn("驱动我实现这个目标的理由", MAINLINE_GOAL_GUIDE)

    def test_hover_guide_has_no_callback_that_can_interrupt_saving(self) -> None:
        button = mainline_goal_guide_button()

        # 悬停由 Flet 原生 Tooltip 处理；说明组件不注册应用层回调，
        # 因此不会干扰主线保存流程。
        self.assertIsNone(button.on_click)
        self.assertIsNone(button.on_hover)


if __name__ == "__main__":
    unittest.main()
