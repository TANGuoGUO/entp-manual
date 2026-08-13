from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path

from database import Database


def prepare(target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"拒绝覆盖已有 QA 数据库：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    db = Database(target)
    try:
        today = date.today()
        current = db.current_mainline_id()
        second = next(mid for mid in (
            int(row["id"])
            for row in db.list_mainlines()
            if row["name"] != "收集箱" and int(row["id"]) != current
        ))

        current_tasks = [
            db.create_task(current, "把本周主题拆成三个最小实验", next_action="先写第一个实验的判断标准", is_today=True),
            db.create_task(current, "整理一次真实用户反馈", is_today=True),
            db.create_task(current, "完成后可在日历看到的任务"),
        ]
        second_task = db.create_task(second, "另一条主线的完成记录")
        db.set_focus_task(current_tasks[0])

        yesterday = (today - timedelta(days=1)).isoformat()
        two_days_ago = (today - timedelta(days=2)).isoformat()
        overdue = db.create_task(current, "昨天没做完，今天决定是否顺延")
        db.plan_task_for_day(overdue, yesterday, source="qa")

        actual_today_iso = db.today_iso
        db.today_iso = lambda: yesterday  # type: ignore[method-assign]
        completed_yesterday = db.plan_task_for_day(current_tasks[2], yesterday, source="qa")
        db.set_daily_entry_completed(completed_yesterday, True)
        db.set_daily_entry_completed(completed_yesterday, False)
        completed_other = db.plan_task_for_day(second_task, yesterday, source="qa")
        db.set_daily_entry_completed(completed_other, True)

        db.today_iso = lambda: two_days_ago  # type: ignore[method-assign]
        older = db.create_task(current, "更早完成的一次尝试")
        older_entry = db.plan_task_for_day(older, two_days_ago, source="qa")
        db.set_daily_entry_completed(older_entry, True)
        db.today_iso = actual_today_iso  # type: ignore[method-assign]
        db.refresh_today_flags()

        ideas = [
            db.create_thought("也许可以从相反的问题开始", ""),
            db.create_thought("把无聊步骤改成一次速度实验", ""),
            db.create_thought("这个方向值得再放几天", ""),
            db.create_thought("已经验证过的小发现", ""),
        ]
        db.set_thought_stage(ideas[1], "待孵化")
        db.set_thought_stage(ideas[2], "正在尝试")
        db.set_thought_stage(ideas[3], "已归档")
        db.update_thought(
            ideas[0],
            title="也许可以从相反的问题开始",
            raw_content="",
            conclusion="",
            evidence="",
            next_step="",
            status="未审视",
            progress=0,
            mainline_id=None,
            tags="反向思考, 选题",
        )

        archived = db.create_mainline("暂时收进保管箱的支线", "以后需要时再恢复。")
        db.create_task(archived, "归档后仍保留的任务")
        db.archive_mainline(archived)
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    prepare(args.target.resolve())
    print(args.target.resolve())


if __name__ == "__main__":
    main()
