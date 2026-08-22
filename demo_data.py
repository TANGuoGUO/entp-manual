from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from database import Database


INTERNAL_DEMO_VERSION = 1


def populate_internal_demo(db: Database) -> None:
    """Populate an empty database with plausible, internally consistent demo data."""

    if db.row("SELECT 1 FROM mainlines LIMIT 1"):
        raise ValueError("演示数据只能写入空数据库")

    today = date.today()
    now = datetime.now().astimezone()

    def day(offset: int) -> str:
        return (today + timedelta(days=offset)).isoformat()

    def timestamp(offset: int, hour: int, minute: int = 0) -> str:
        target = now + timedelta(days=offset)
        return target.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()

    def add_mainline(
        name: str,
        vision: str,
        color: str,
        *,
        status: str = "进行中",
        created_offset: int = -20,
    ) -> int:
        cursor = db.conn.execute(
            """INSERT INTO mainlines(name, vision, color, status, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (name, vision, color, status, timestamp(created_offset, 10)),
        )
        return int(cursor.lastrowid)

    def add_task(
        mainline_id: int,
        title: str,
        *,
        parent_id: int | None = None,
        description: str = "",
        status: str = "待执行",
        priority: str = "普通",
        due_offset: int | None = None,
        is_today: bool = False,
        is_focus: bool = False,
        next_action: str = "",
        progress: int = 0,
        completed_offset: int | None = None,
        sort_order: int = 0,
        created_offset: int = -10,
    ) -> int:
        # Subtasks intentionally never enter the independent today/focus queues.
        if parent_id is not None and (is_today or is_focus):
            raise ValueError(f"子任务不能进入今日或焦点：{title}")
        completed_at = (
            timestamp(completed_offset, 18, 20)
            if completed_offset is not None
            else ""
        )
        cursor = db.conn.execute(
            """INSERT INTO tasks(
                   mainline_id, parent_task_id, title, description, status,
                   priority, due_date, is_today, is_focus, next_action,
                   progress, sort_order, completed_at, created_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mainline_id,
                parent_id,
                title,
                description,
                status,
                priority,
                day(due_offset) if due_offset is not None else "",
                int(is_today),
                int(is_focus),
                next_action,
                progress,
                sort_order,
                completed_at,
                timestamp(created_offset, 11, 10),
            ),
        )
        return int(cursor.lastrowid)

    def add_daily_entry(
        task_id: int,
        offset: int,
        *,
        state: str = "planned",
        source: str = "manual",
        proof: str = "",
        is_primary: bool = False,
    ) -> int:
        task = db.get_task(task_id)
        if not task or task["parent_task_id"] is not None:
            raise ValueError("每日清单只能引用存在的父任务")
        completed_at = timestamp(offset, 18, 20) if state == "completed" else ""
        created_at = timestamp(offset, 9, 15)
        cursor = db.conn.execute(
            """INSERT INTO daily_entries(
                   entry_date, task_id, task_title_snapshot, mainline_id,
                   mainline_name_snapshot, mainline_color_snapshot,
                   priority_snapshot, due_date_snapshot, state, is_primary,
                   source, completed_at, proof, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                day(offset),
                task_id,
                task["title"],
                task["mainline_id"],
                task["mainline_name"],
                task["mainline_color"],
                task["priority"],
                task["due_date"],
                state,
                int(is_primary),
                source,
                completed_at,
                proof,
                created_at,
                completed_at or created_at,
            ),
        )
        entry_id = int(cursor.lastrowid)
        event_type = "completed" if state == "completed" else "planned"
        db.conn.execute(
            """INSERT INTO task_events(
                   task_id, daily_entry_id, event_type, event_date, occurred_at,
                   task_title_snapshot, details_json
               ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                entry_id,
                event_type,
                day(offset),
                completed_at or created_at,
                task["title"],
                json.dumps({"source": source}, ensure_ascii=False),
            ),
        )
        return entry_id

    with db.conn:
        product = add_mainline(
            "摄影行业创业",
            "有影棚 有摄影资源 想长期做",
            "#316BEE",
        )
        content = add_mainline(
            "把表达练成长期能力",
            "平时就在写方案、做分享，想把表达练成长期本事。别人能更快听懂、少踩坑；我享受把难事讲明白，不只想要流量。",
            "#8B6FD6",
            created_offset=-34,
        )
        business = add_mainline(
            "建立能稳定养活自己的个人业务",
            "做过几次零散合作，也愿意继续学销售和交付。想给小团队解决真问题，也让自己的收入不只靠一份工资；我喜欢直接面对用户，不只是想象当老板。",
            "#D8893B",
            created_offset=-12,
        )
        leadership = add_mainline(
            "成为能带团队把复杂项目推进到底的人",
            "已经独立做过项目，也愿意补沟通和协作这块短板。希望团队少内耗、事情更快落地；我喜欢把大家拉到同一个方向，不只是想要一个管理头衔。",
            "#37A46A",
            created_offset=-28,
        )
        photography = add_mainline(
            "用照片把身边的人留下来",
            "认真拍过两年，也愿意继续练。想把朋友和家人的真实样子留下来；我喜欢观察人的状态，不是为了买设备或发作品。",
            "#8B9099",
            status="已归档",
            created_offset=-90,
        )
        inbox = add_mainline(
            "收集箱",
            "先放这，晚点再分。",
            "#8B9099",
            created_offset=-60,
        )

        first_release = add_task(
            product,
            "调研客户",
            status="执行中",
            priority="重要",
            due_offset=7,
            is_today=True,
            is_focus=True,
            description="客户类型 需求 预算",
            next_action="问老客户",
            progress=10,
            sort_order=-70,
        )
        old_customer_outreach = add_task(product, "老客户", parent_id=first_release, sort_order=1)
        add_task(product, "摄影师客户", parent_id=first_release, sort_order=2)
        add_task(product, "coser", parent_id=first_release, sort_order=3)
        competitor_research = add_task(product, "影棚竞品调研", status="今日", is_today=True, due_offset=0, sort_order=-60)
        photographer_resources = add_task(product, "摄影师合作", status="今日", is_today=True, sort_order=-50)
        set_designer_resources = add_task(product, "布景师合作", sort_order=-40)
        social_acquisition = add_task(product, "自媒体获客", sort_order=-30)
        add_task(product, "cos mcn", sort_order=-20)
        add_task(product, "coser账号", sort_order=-10)
        pet_photography = add_task(product, "宠物摄影", sort_order=10)
        scene_done = add_task(product, "影棚设备清单", status="完成", progress=100, completed_offset=-1, sort_order=20)

        topics = add_task(content, "先定三个选题", status="今日", is_today=True, is_focus=True, sort_order=-50)
        add_task(content, "工位改造", parent_id=topics, sort_order=1)
        add_task(content, "效率工具别讲空话", parent_id=topics, sort_order=2)
        add_task(content, "一周复盘", parent_id=topics, status="完成", progress=100, completed_offset=-2, sort_order=3)
        add_task(content, "找回以前的封面源文件", sort_order=-40)
        add_task(content, "把置顶那篇重写一下", sort_order=-30)
        add_task(content, "问阿宁愿不愿意帮拍", next_action="微信问一句", sort_order=-20)
        phone_done = add_task(content, "先用手机拍一条", status="完成", progress=100, completed_offset=-3, sort_order=-10)

        first_offer = add_task(business, "把第一个付费服务写清楚", priority="重要", due_offset=3, is_focus=True, sort_order=-50)
        ask_clients = add_task(business, "问三个老客户现在最缺什么", status="今日", is_today=True, sort_order=-40)
        pricing = add_task(business, "把报价整理成一页", sort_order=-30)
        add_task(business, "基础版", parent_id=pricing, sort_order=1)
        add_task(business, "陪跑版", parent_id=pricing, sort_order=2)
        add_task(business, "先试一次", parent_id=pricing, sort_order=3)
        ask_invoice = add_task(business, "约会计问一下开票", status="今日", is_today=True, due_offset=0, sort_order=-20)
        add_task(business, "把老客户反馈收在一起", sort_order=-10)
        cost_done = add_task(business, "算清一个月最低成本", status="完成", progress=100, completed_offset=-2, sort_order=0)
        add_task(business, "写清楚什么情况不接", sort_order=10)

        blockers = add_task(leadership, "把这周阻塞项开个短会", status="今日", is_today=True, is_focus=True, sort_order=-40)
        add_task(leadership, "把决策记录补上", sort_order=-30)
        add_task(leadership, "找小周做一次 1:1", due_offset=4, sort_order=-20)
        add_task(leadership, "周三别再塞新需求", sort_order=-10)
        cadence_done = add_task(leadership, "把版本节奏排出来", status="完成", progress=100, completed_offset=-4, sort_order=0)

        add_task(photography, "把去年的照片翻一遍", sort_order=-20)
        add_task(photography, "先别买新镜头", status="完成", progress=100, completed_offset=-40, sort_order=-10)

        add_task(inbox, "给爸妈买个血压计", is_focus=True, sort_order=-50)
        reimburse = add_task(inbox, "报销上个月打车", status="今日", is_today=True, sort_order=-40)
        add_task(inbox, "周五拿快递", due_offset=2, sort_order=-30)
        add_task(inbox, "春节要不要去云南", sort_order=-20)
        add_task(inbox, "小区停车月卡", sort_order=-10)

        # Today contains tasks from several mainlines, which makes the cross-line
        # daily view useful during a short product walkthrough.
        add_daily_entry(first_release, 0, source="manual", is_primary=True)
        add_daily_entry(competitor_research, 0)
        add_daily_entry(photographer_resources, 0)
        add_daily_entry(topics, 0)
        add_daily_entry(ask_clients, 0)
        add_daily_entry(ask_invoice, 0)
        add_daily_entry(blockers, 0)
        add_daily_entry(reimburse, 0)
        add_daily_entry(scene_done, -1, state="completed", proof="灯 背景纸 道具")
        add_daily_entry(cost_done, -2, state="completed", proof="暂时每个月至少要覆盖 6800")
        add_daily_entry(phone_done, -3, state="completed", proof="拍了 38 秒，收音还能听")
        add_daily_entry(cadence_done, -4, state="completed", proof="两周一个小版本，周五不再临时塞需求")

        db.conn.executemany(
            """INSERT INTO daily_notes(note_date, intention, reflection, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                (day(0), "调研客户", "", timestamp(0, 9), timestamp(0, 9)),
                (day(-1), "盘影棚资源", "设备够用", timestamp(-1, 9), timestamp(-1, 22)),
            ),
        )

        thought_specs = [
            (product, "摄影师个人ip", "棚拍 花絮 教程", "待孵化", "获客", "很想继续", "摄影师,账号"),
            (product, "布景出租", "影棚空档", "未审视", "资源", "有点好奇", "布景,场地"),
            (product, "宠物摄影棚", "客单 复购", "正在尝试", "项目", "很想继续", "宠物,摄影"),
            (product, "coser会员", "月卡 妆造 棚拍", "未审视", "项目", "有点好奇", "cos,会员"),
            (product, "摄影训练营", "线下 实拍", "待孵化", "项目", "有点好奇", "摄影,培训"),
            (content, "先拍个 30 秒的", "别管完整不完整，拍完再说。", "正在尝试", "内容", "持续着迷", "短视频,实验"),
            (content, "一周发一条就行吧", "别又给自己排一堆。", "待孵化", "提醒", "很想继续", "节奏"),
            (content, "一周只更一次可能也行", "先连续四周再说。", "未审视", "内容", "有点好奇", "频率"),
            (business, "报价是不是做三档", "一页里放太多又怕别人看不懂。", "未审视", "业务", "有点好奇", "报价"),
            (business, "第一个客户先按次也行", "别一上来就逼人包月。", "待孵化", "业务", "很想继续", "客户,交付"),
            (business, "要不要送一次诊断", "可能更容易让人先试。", "未审视", "业务", "有点好奇", "体验"),
            (leadership, "周会可能可以砍掉", "大家其实只是轮流念进度。", "待孵化", "协作", "有点好奇", "会议"),
            (leadership, "先让每个人写阻塞", "会前写一句，也许十分钟就能开完。", "正在尝试", "协作", "很想继续", "推进,实验"),
            (None, "做播客好像也可以", "先记着，别现在买麦克风。", "已归档", "内容", "一闪而过", "新点子"),
        ]
        thought_ids: dict[str, int] = {}
        for index, (mainline_id, title, content_text, status, category, interest, tags) in enumerate(thought_specs):
            # 当前主线的灵感放在候审区前面，演示时先看到正在讲解的案例；
            # 其他主线仍然保留，体现候审区可以跨主线暂存想法。
            updated_offset = 0 if mainline_id == product else -(index % 4) - 1
            cursor = db.conn.execute(
                """INSERT INTO thoughts(
                       mainline_id, title, raw_content, status, category,
                       interest_level, tags, progress, reviewed_at, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mainline_id,
                    title,
                    content_text,
                    status,
                    category,
                    interest,
                    tags,
                    35 if status == "正在尝试" else 0,
                    timestamp(updated_offset, 20) if status != "未审视" else "",
                    timestamp(-8 + index // 3, 14, 30),
                    timestamp(updated_offset, 20, index),
                ),
            )
            thought_ids[title] = int(cursor.lastrowid)

        db.conn.executemany(
            "INSERT INTO thought_task_links(thought_id, task_id) VALUES (?, ?)",
            (
                (thought_ids["摄影师个人ip"], social_acquisition),
                (thought_ids["布景出租"], set_designer_resources),
                (thought_ids["宠物摄影棚"], pet_photography),
                (thought_ids["先拍个 30 秒的"], topics),
                (thought_ids["报价是不是做三档"], pricing),
                (thought_ids["周会可能可以砍掉"], blockers),
            ),
        )
        db.conn.executemany(
            """INSERT INTO thought_links(source_thought_id, target_thought_id, relation)
               VALUES (?, ?, ?)""",
            (
                (thought_ids["一周发一条就行吧"], thought_ids["一周只更一次可能也行"], "支撑"),
                (thought_ids["布景出租"], thought_ids["coser会员"], "启发"),
                (thought_ids["周会可能可以砍掉"], thought_ids["先让每个人写阻塞"], "支撑"),
            ),
        )
        for title, thought_id in thought_ids.items():
            thought = db.get_thought(thought_id)
            if thought and thought["status"] != "未审视":
                db.conn.execute(
                    """INSERT INTO thought_review_events(
                           thought_id, from_status, to_status, note, event_date, created_at
                       ) VALUES (?, '未审视', ?, ?, ?, ?)""",
                    (
                        thought_id,
                        thought["status"],
                        "先放到这个阶段" if thought["status"] != "已归档" else "已经记住了，不用再看",
                        day(-1),
                        timestamp(-1, 20, 30),
                    ),
                )

        db.conn.executemany(
            "INSERT INTO app_settings(key, value) VALUES (?, ?)",
            (
                ("current_mainline_id", str(product)),
                ("internal_demo_version", str(INTERNAL_DEMO_VERSION)),
            ),
        )

    issues = validate_internal_demo(db)
    if issues:
        raise RuntimeError("演示数据校验失败：" + "；".join(issues))


def validate_internal_demo(db: Database) -> list[str]:
    """Return human-readable problems instead of leaking raw SQLite errors."""

    issues: list[str] = []
    if db.rows("PRAGMA foreign_key_check"):
        issues.append("存在外键异常")
    checks = {
        "存在跨主线子任务": """SELECT 1 FROM tasks child JOIN tasks parent
            ON parent.id = child.parent_task_id
            WHERE child.mainline_id <> parent.mainline_id LIMIT 1""",
        "存在二级子任务": """SELECT 1 FROM tasks child JOIN tasks parent
            ON parent.id = child.parent_task_id
            WHERE parent.parent_task_id IS NOT NULL LIMIT 1""",
        "子任务进入了今日或焦点": """SELECT 1 FROM tasks
            WHERE parent_task_id IS NOT NULL AND (is_today <> 0 OR is_focus <> 0) LIMIT 1""",
        "每日清单引用了子任务": """SELECT 1 FROM daily_entries de JOIN tasks task
            ON task.id = de.task_id WHERE task.parent_task_id IS NOT NULL LIMIT 1""",
    }
    for message, sql in checks.items():
        if db.row(sql):
            issues.append(message)
    if int(db.row("SELECT COUNT(*) FROM mainlines")[0]) < 5:
        issues.append("主线数量不足")
    if int(db.row("SELECT COUNT(*) FROM tasks")[0]) < 25:
        issues.append("任务数量不足")
    if int(db.row("SELECT COUNT(*) FROM thoughts")[0]) < 10:
        issues.append("思路数量不足")
    return issues
