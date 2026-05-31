from calendar_utils import format_slot
from calendar_utils import DAYS_JP

MAX_CHECKBOX = 10  # Slack の checkboxes element の上限


def _window_label(w_start, w_end, duration_minutes: int) -> str:
    day = DAYS_JP[w_start.weekday()]
    h, m = divmod(duration_minutes, 60)
    duration_str = f"{h}時間" if m == 0 else f"{h}時間{m}分" if h else f"{m}分"
    return (
        f"{w_start.month}月{w_start.day}日（{day}）"
        f"{w_start.strftime('%H:%M')}〜{w_end.strftime('%H:%M')}"
        f" ※いずれか{duration_str}"
    )


def build_windows_blocks(windows: list, session_id: str, duration_minutes: int) -> list:
    """空き枠まとめ形式のブロックを返す。"""
    if not windows:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "❌ 空き時間が見つかりませんでした。"}}]

    display = windows[:MAX_CHECKBOX]
    options = [
        {
            "text": {"type": "mrkdwn", "text": _window_label(s, e, duration_minutes)},
            "value": str(i),
        }
        for i, (s, e) in enumerate(display)
    ]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🗓️ 空き時間帯が見つかりました（{len(windows)}件）*\n送る枠にチェックを入れてください",
            },
        },
        {
            "type": "actions",
            "block_id": f"cb_{session_id}",
            "elements": [{"type": "checkboxes", "action_id": "date_selected", "options": options}],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✉️ メール文面を作る"},
                    "style": "primary",
                    "action_id": "create_email_window",
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📋 全件テキスト表示"},
                    "action_id": "show_all",
                    "value": session_id,
                },
            ],
        },
    ]

    if len(windows) > MAX_CHECKBOX:
        blocks.insert(2, {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"_上位 {MAX_CHECKBOX} 件を表示中。残り {len(windows) - MAX_CHECKBOX} 件は「📋 全件テキスト表示」で確認できます_"}],
        })

    return blocks


def format_email_windows(windows: list, duration_minutes: int) -> str:
    if not windows:
        return "⚠️ 枠を選択してください。"
    lines = ["下記の時間帯はいかがでしょうか。ご都合のよい時間をお知らせください。", ""]
    for s, e in windows:
        lines.append(f"・{_window_label(s, e, duration_minutes)}")
    lines += ["", "ご都合のよい日時をお知らせください。"]
    return f"*✉️ メール文面（{len(windows)}件選択）*\n```\n" + "\n".join(lines) + "\n```"


def build_schedule_blocks(slots: list, session_id: str) -> list:
    if not slots:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": "❌ 2週間以内に空き時間が見つかりませんでした。"}}]

    display = slots[:MAX_CHECKBOX]
    options = [
        {"text": {"type": "mrkdwn", "text": format_slot(s, e)}, "value": str(i)}
        for i, (s, e) in enumerate(display)
    ]

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🗓️ 日程調整の候補が見つかりました（{len(slots)}件）*\n送る日程にチェックを入れてください",
            },
        },
        {
            "type": "actions",
            "block_id": f"cb_{session_id}",
            "elements": [
                {
                    "type": "checkboxes",
                    "action_id": "date_selected",
                    "options": options,
                }
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✉️ メール文面を作る"},
                    "style": "primary",
                    "action_id": "create_email",
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📅 カレンダーに登録"},
                    "action_id": "register_calendar",
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📋 全件テキスト表示"},
                    "action_id": "show_all",
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💾 この条件をデフォルトに保存"},
                    "action_id": "save_as_default",
                    "value": session_id,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⚙️ 条件を変えて再検索"},
                    "action_id": "reopen_modal",
                    "value": session_id,
                },
            ],
        },
    ]

    if len(slots) > MAX_CHECKBOX:
        blocks.insert(
            2,
            {
                "type": "context",
                "elements": [
                    {
                        "type": "mrkdwn",
                        "text": f"_上位 {MAX_CHECKBOX} 件を表示中。残り {len(slots) - MAX_CHECKBOX} 件は「📋 全件テキスト表示」で確認できます_",
                    }
                ],
            },
        )

    return blocks


def format_email_text(slots: list) -> str:
    if not slots:
        return "⚠️ 日程が選択されていません。チェックボックスで日程を選んでください。"
    lines = ["下記の日程はいかがでしょうか。", ""]
    for s, e in slots:
        lines.append(f"・{format_slot(s, e)}")
    lines += ["", "ご都合のよい日時をお知らせください。"]
    return f"*✉️ メール文面（{len(slots)}件選択）*\n```\n" + "\n".join(lines) + "\n```"


def format_all_text(slots: list) -> str:
    lines = [f"・{format_slot(s, e)}" for s, e in slots]
    return f"*📋 全候補（{len(slots)}件）*\n" + "\n".join(lines)
