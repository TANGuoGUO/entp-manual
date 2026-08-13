# ENTP 自强手册：今日清单与完成日历 Design QA

## Source visual truth

- 今日清单参考：`G:\project\entp\designs\reference-ticktick-today-list.png`
- 完成日历参考：`G:\project\entp\designs\entp-self-help-2.0-mainline-tasks-calendar.png`
- 完整并排对照：`G:\project\entp\designs\flet-2.5-daily-calendar-comparison.png`

## Implementation evidence

- 今日清单宽屏：`G:\project\entp\designs\flet-2.5-today-final.png`
- 今日清单窄屏：`G:\project\entp\designs\flet-2.5-today-compact-fixed.png`
- 历史日期账本：`G:\project\entp\designs\flet-2.5-daily-history.png`
- 完成日历宽屏：`G:\project\entp\designs\flet-2.5-calendar-final.png`
- 完成日历窄屏：`G:\project\entp\designs\flet-2.5-calendar-compact.png`

## Viewport and normalization

- Today source: 1055 × 859 px.
- Calendar source: 1487 × 1058 px.
- Wide implementation captures: 1463 × 752 px at pixel ratio 1.0.
- Compact implementation captures: 907 × 684 px at pixel ratio 1.0; requested window 920 × 720.
- The comparison board proportionally contains each full native capture in equal 720 × 430 cells. It is used to judge hierarchy and visual language, not pixel-identical content placement across different source viewports.
- State: current date 2026-08-13; calendar detail comparison selects 2026-08-12 with one completed item, matching the source's selected-day completion state.

## Findings

- No remaining P0/P1/P2 mismatch.
- Information architecture: the implementation preserves the reference hierarchy of title → direct input → overdue/today/completed groups. Calendar preserves month overview → selected-day completion details.
- Fonts and typography: Microsoft YaHei UI, 30 px page title, 19 px group title, 16 px task title, and 12–15 px metadata remain readable at both tested widths. Completed items use reduced contrast without becoming illegible.
- Spacing and layout rhythm: today rows remain flat with divider lines rather than excessive boxed cards. Input and history banner use 14–16 px radii. Calendar uses two outlined 20 px radius surfaces on wide screens and stacks them on compact screens.
- Colors and visual tokens: blue remains the navigation and selection color, green denotes recorded completion facts, red denotes overdue dates, and neutral gray carries metadata. The palette matches the existing Flet 2.0 shell.
- Image quality and assets: no raster product assets are required. All controls use Flet's Material icon library; no emoji, handcrafted SVG, or placeholder art is used.
- Copy and content: “顺延到今天”, “历史账本”, “后续改名不会覆盖这里”, and “不计算连续天数” communicate the product's date semantics directly.
- Responsiveness: at 920 × 720 the today list keeps all header actions visible. The calendar and selected-day detail change from side-by-side to vertical flow and remain scrollable.
- Interaction: quick task entry, complete/reopen, overdue carry, day navigation, priority sorting, group collapse, month navigation, selected-day detail, and entry into a historical ledger are connected to SQLite data.

## Comparison history

1. P2 compact overflow: the first compact capture used a fixed 1120 px content width, clipping header actions and row metadata.
   - Fix: replaced fixed page widths with expanding constrained content inside the existing padded shell.
   - Post-fix evidence: `G:\project\entp\designs\flet-2.5-today-compact-fixed.png`.
2. P1 completion-history loss: completion calendar originally depended on the daily entry's current state, so reopening could remove a past completion from the calendar.
   - Fix: calendar and history summaries now derive completion facts from append-only `task_events`; the daily entry still represents current task state.
   - Post-fix evidence: `G:\project\entp\tests\test_daily_ledger.py` and `G:\project\entp\designs\flet-2.5-calendar-final.png`.

## Verification

- Python compilation passed for `flet_app.py`, `database.py`, `markdown_store.py`, and the daily-ledger test.
- Daily snapshot, rename immutability, complete/reopen fact retention, overdue carry idempotency, and Markdown daily document tests passed.
- Existing archive/restore regression test still passes.
- Native wide and compact Flet captures contain no clipped primary controls or broken text.

## Follow-up polish

- P3: on the minimum compact window, selected-day calendar details are below the month grid and require scrolling. This is intentional to preserve readable date cells and task text.

final result: passed
