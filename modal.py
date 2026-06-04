import json
import settings as cfg
from calendar_utils import format_slot


def _sel(label: str, value: str) -> dict:
    return {"text": {"type": "plain_text", "text": label}, "value": value}


def _dur_opts() -> list:
    return [_sel("30分", "30"), _sel("1時間", "60"), _sel("1時間30分", "90"), _sel("2時間", "120")]


def _weeks_opts() -> list:
    return [_sel("1週間先まで", "1"), _sel("2週間先まで", "2"), _sel("3週間先まで", "3"), _sel("4週間先まで", "4")]


def _buffer_opts() -> list:
    return [_sel("なし", "0"), _sel("15分", "15"), _sel("30分", "30"), _sel("1時間", "60")]


def _interval_opts() -> list:
    return [
        _sel("15分刻み（14:00 / 14:15 / 14:30 …）", "15"),
        _sel("30分刻み（14:00 / 14:30 / 15:00 …）", "30"),
        _sel("1時間刻み（14:00 / 15:00 / 16:00 …）", "60"),
    ]


def _weekday_checkboxes(exclude_weekdays: list) -> dict:
    weekday_names = ["月", "火", "水", "木", "金"]
    options = [{"text": {"type": "plain_text", "text": name}, "value": str(i)} for i, name in enumerate(weekday_names)]
    element = {"type": "checkboxes", "action_id": "value", "options": options}
    if exclude_weekdays:
        element["initial_options"] = [{"text": {"type": "plain_text", "text": weekday_names[d]}, "value": str(d)} for d in exclude_weekdays]
    return element


def build_settings_modal(user_id: str) -> dict:
    """ユーザーのデフォルト設定を変更するモーダルを返す。"""
    s = cfg.load(user_id)

    def _initial_time(val: str) -> dict:
        return _sel(val, val)

    def _initial_dur(val: int) -> dict:
        labels = {30: "30分", 60: "1時間", 90: "1時間30分", 120: "2時間"}
        return _sel(labels.get(val, "1時間"), str(val))

    def _initial_weeks(val: int) -> dict:
        return _sel(f"{val}週間先まで", str(val))

    def _initial_interval(val: int) -> dict:
        labels = {15: "15分刻み（14:00 / 14:15 / 14:30 …）",
                  30: "30分刻み（14:00 / 14:30 / 15:00 …）",
                  60: "1時間刻み（14:00 / 15:00 / 16:00 …）"}
        return _sel(labels.get(val, "30分刻み（14:00 / 14:30 / 15:00 …）"), str(val))

    filter_opts = [
        {
            "text": {"type": "plain_text", "text": "指定キーワードのみ除外"},
            "description": {"type": "plain_text", "text": "商談・MTG・有給・移動など指定した単語を含む予定だけをブロック。「商談準備」など除外ワードを含む場合は空きとして扱う"},
            "value": "keywords",
        },
        {
            "text": {"type": "plain_text", "text": "予定が入っている枠はすべて除外"},
            "description": {"type": "plain_text", "text": "タイトルに関係なく、カレンダーに何か入っている時間はすべてブロックする"},
            "value": "all",
        },
        {
            "text": {"type": "plain_text", "text": "どの予定も除外しない"},
            "description": {"type": "plain_text", "text": "カレンダーを無視して、時間帯設定の範囲内をすべて候補として出す"},
            "value": "none",
        },
    ]

    display_opts = [
        {
            "text": {"type": "plain_text", "text": "スロット形式"},
            "description": {"type": "plain_text", "text": "14:00〜15:00 / 14:30〜15:30 … のように開始時刻ごとに個別に列挙する"},
            "value": "slots",
        },
        {
            "text": {"type": "plain_text", "text": "空き枠まとめ形式"},
            "description": {"type": "plain_text", "text": "14:00〜16:00 ※いずれか1時間 のように空き窓をまとめて提示する。相手に開始時刻を選んでもらいたいときに便利"},
            "value": "windows",
        },
    ]

    return {
        "type": "modal",
        "callback_id": "settings_modal",
        "private_metadata": json.dumps({"user_id": user_id}),
        "title": {"type": "plain_text", "text": "自分の設定"},
        "submit": {"type": "plain_text", "text": "保存する"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "ここで保存した設定が `/日程調整` を打ったときのデフォルト値になります。\nモーダル上でいつでも上書き変更できます。"},
            },
            {"type": "divider"},
            # 所要時間
            {
                "type": "input",
                "block_id": "default_duration",
                "label": {"type": "plain_text", "text": "⏱ デフォルト所要時間"},
                "hint": {"type": "plain_text", "text": "1時間の商談なら「1時間」、30分のオンライン面談なら「30分」"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _initial_dur(s["default_duration"]),
                    "options": _dur_opts(),
                },
            },
            # 開始時間
            {
                "type": "input",
                "block_id": "default_start_time",
                "label": {"type": "plain_text", "text": "🕙 候補の開始時間（デフォルト）"},
                "hint": {"type": "plain_text", "text": "この時刻より前の枠は候補に出さない。通常は 10:00"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _initial_time(s["default_start_time"]),
                    "options": _time_opts(8, 18),
                },
            },
            # 終了時間
            {
                "type": "input",
                "block_id": "default_end_time",
                "label": {"type": "plain_text", "text": "🕕 候補の終了時間（デフォルト）"},
                "hint": {"type": "plain_text", "text": "この時刻より後の枠は候補に出さない。例: 19:00 なら 18:00 開始の1時間枠が最後"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _initial_time(s["default_end_time"]),
                    "options": _time_opts(9, 22),
                },
            },
            # 刻み
            {
                "type": "input",
                "block_id": "default_slot_interval",
                "label": {"type": "plain_text", "text": "🔢 候補の刻み（デフォルト）"},
                "hint": {"type": "plain_text", "text": "細かいほど候補が増える。「14:15 開始でも OK」なら 15分刻みを選ぶ"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _initial_interval(s["default_slot_interval"]),
                    "options": _interval_opts(),
                },
            },
            # バッファ
            {
                "type": "input",
                "block_id": "default_buffer",
                "label": {"type": "plain_text", "text": "⏰ 前後のバッファ（デフォルト）"},
                "hint": {"type": "plain_text", "text": "15分に設定すると、既存の予定の前後15分も候補から除外される。移動・準備時間の確保に"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _sel(
                        {0: "なし", 15: "15分", 30: "30分", 60: "1時間"}.get(s["buffer_minutes"], "なし"),
                        str(s["buffer_minutes"]),
                    ),
                    "options": _buffer_opts(),
                },
            },
            # 検索期間
            {
                "type": "input",
                "block_id": "default_weeks_ahead",
                "label": {"type": "plain_text", "text": "📅 検索期間（デフォルト）"},
                "hint": {"type": "plain_text", "text": "今日から何週間先まで空き枠を探すか。急ぎの商談なら「1週間」、余裕があれば「4週間」"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _initial_weeks(s["default_weeks_ahead"]),
                    "options": _weeks_opts(),
                },
            },
            {"type": "divider"},
            # 除外曜日
            {
                "type": "input",
                "block_id": "exclude_weekdays",
                "label": {"type": "plain_text", "text": "🚫 除外する曜日"},
                "optional": True,
                "element": _weekday_checkboxes(s["exclude_weekdays"]),
            },
            # 除外時間帯
            {
                "type": "input",
                "block_id": "exclude_time_ranges",
                "label": {"type": "plain_text", "text": "🕐 除外する時間帯"},
                "hint": {"type": "plain_text", "text": "1行につき1つ。例: 12:00-13:00"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "12:00-13:00\n17:30-18:30"},
                    **({"initial_value": "\n".join(f"{r['start']}-{r['end']}" for r in s["exclude_time_ranges"])} if s["exclude_time_ranges"] else {}),
                },
            },
            # 除外モード
            {
                "type": "input",
                "block_id": "filter_mode",
                "label": {"type": "plain_text", "text": "🔒 予定の除外モード"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "value",
                    "initial_option": next(o for o in filter_opts if o["value"] == s["filter_mode"]),
                    "options": filter_opts,
                },
            },
            # 表示形式
            {
                "type": "input",
                "block_id": "display_mode",
                "label": {"type": "plain_text", "text": "📊 候補の表示形式"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "value",
                    "initial_option": next(o for o in display_opts if o["value"] == s["display_mode"]),
                    "options": display_opts,
                },
            },
        ],
    }


def _time_opts(from_h: int, to_h: int) -> list:
    """HH:00 / HH:30 の選択肢リストを生成する。"""
    opts = []
    for h in range(from_h, to_h + 1):
        for m in (0, 30):
            if h == to_h and m > 0:
                break
            label = f"{h:02d}:{m:02d}"
            opts.append({"text": {"type": "plain_text", "text": label}, "value": label})
    return opts


def build_event_modal(session_id: str, slots: list) -> dict:
    slot_lines = "\n".join(f"• {format_slot(s, e)}" for s, e in slots)
    metadata = json.dumps({"session_id": session_id})

    return {
        "type": "modal",
        "callback_id": "event_modal",
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": "カレンダーに登録"},
        "submit": {"type": "plain_text", "text": "登録する"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"*登録する日程:*\n{slot_lines}"},
            },
            {
                "type": "input",
                "block_id": "event_title",
                "label": {"type": "plain_text", "text": "📋 イベント名"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "例: 商談 株式会社◯◯"},
                },
            },
            {
                "type": "input",
                "block_id": "meeting_url",
                "label": {"type": "plain_text", "text": "🔗 MTG URL（任意）"},
                "hint": {"type": "plain_text", "text": "空欄にすると Google Meet を自動生成します。Zoom 等を使う場合はここに入力してください"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "https://zoom.us/j/..."},
                },
            },
        ],
    }


def build_modal(channel_id: str, user_id: str, thread_ts: str = "") -> dict:
    s = cfg.load(user_id)
    metadata = json.dumps({"channel_id": channel_id, "user_id": user_id, "thread_ts": thread_ts})
    saved_display = s.get("display_mode", "slots")

    return {
        "type": "modal",
        "callback_id": "schedule_modal",
        "private_metadata": metadata,
        "title": {"type": "plain_text", "text": "日程調整の条件"},
        "submit": {"type": "plain_text", "text": "日程調整を検索する"},
        "close": {"type": "plain_text", "text": "キャンセル"},
        "blocks": [
            # ── 所要時間 ──
            {
                "type": "input",
                "block_id": "duration",
                "label": {"type": "plain_text", "text": "⏱ 所要時間"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _sel({30:"30分",60:"1時間",90:"1時間30分",120:"2時間"}.get(s["default_duration"],"1時間"), str(s["default_duration"])),
                    "options": _dur_opts(),
                },
            },
            # ── 検索期間 ──
            {
                "type": "input",
                "block_id": "weeks_ahead",
                "label": {"type": "plain_text", "text": "📅 検索期間"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": _sel(f"{s['default_weeks_ahead']}週間先まで", str(s["default_weeks_ahead"])),
                    "options": _weeks_opts(),
                },
            },
            # ── 時間帯（開始・終了） ──
            {
                "type": "input",
                "block_id": "start_time",
                "label": {"type": "plain_text", "text": "🕙 候補の開始時間"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {"text": {"type": "plain_text", "text": "10:00"}, "value": "10:00"},
                    "options": _time_opts(8, 18),
                },
            },
            {
                "type": "input",
                "block_id": "end_time",
                "label": {"type": "plain_text", "text": "🕕 候補の終了時間"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {"text": {"type": "plain_text", "text": "19:00"}, "value": "19:00"},
                    "options": _time_opts(9, 22),
                },
            },
            # ── 候補の刻み ──
            {
                "type": "input",
                "block_id": "slot_interval",
                "label": {"type": "plain_text", "text": "🔢 候補の刻み（開始時間の間隔）"},
                "hint": {"type": "plain_text", "text": "細かいほど多くの開始時刻を提案します"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {"text": {"type": "plain_text", "text": "30分刻み（14:00 / 14:30 / 15:00 …）"}, "value": "30"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "15分刻み（14:00 / 14:15 / 14:30 …）"}, "value": "15"},
                        {"text": {"type": "plain_text", "text": "30分刻み（14:00 / 14:30 / 15:00 …）"}, "value": "30"},
                        {"text": {"type": "plain_text", "text": "1時間刻み（14:00 / 15:00 / 16:00 …）"}, "value": "60"},
                    ],
                },
            },
            # ── バッファ ──
            {
                "type": "input",
                "block_id": "buffer",
                "label": {"type": "plain_text", "text": "⏰ 前後のバッファ"},
                "element": {
                    "type": "static_select",
                    "action_id": "value",
                    "initial_option": {"text": {"type": "plain_text", "text": "なし"}, "value": "0"},
                    "options": [
                        {"text": {"type": "plain_text", "text": "なし"}, "value": "0"},
                        {"text": {"type": "plain_text", "text": "15分"}, "value": "15"},
                        {"text": {"type": "plain_text", "text": "30分"}, "value": "30"},
                    ],
                },
            },
            # ── 参加者 ──
            {
                "type": "input",
                "block_id": "participants",
                "label": {"type": "plain_text", "text": "👥 参加者（自分以外）"},
                "hint": {"type": "plain_text", "text": "選択したユーザーのカレンダーも考慮して空き枠を探します"},
                "optional": True,
                "element": {
                    "type": "multi_users_select",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "追加する場合はユーザーを選択"},
                },
            },
            # ── 予定の除外モード ──
            {
                "type": "input",
                "block_id": "filter_mode",
                "label": {"type": "plain_text", "text": "🔒 予定の除外モード"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "value",
                    "initial_option": {
                        "text": {"type": "plain_text", "text": "指定キーワードのみ除外"},
                        "description": {"type": "plain_text", "text": "商談・面談・面接・MTG・ブロック・有給・午前休・午後休・移動 を含む予定"},
                        "value": "keywords",
                    },
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "指定キーワードのみ除外"},
                            "description": {"type": "plain_text", "text": "商談・面談・面接・MTG・ブロック・有給・午前休・午後休・移動 を含む予定"},
                            "value": "keywords",
                        },
                        {
                            "text": {"type": "plain_text", "text": "予定が入っている枠はすべて除外"},
                            "description": {"type": "plain_text", "text": "タイトルに関わらず全予定をブロック"},
                            "value": "all",
                        },
                        {
                            "text": {"type": "plain_text", "text": "どの予定も除外しない"},
                            "description": {"type": "plain_text", "text": "カレンダーを無視して平日10〜19時の全枠を候補にする"},
                            "value": "none",
                        },
                    ],
                },
            },
            # ── 除外曜日 ──
            {
                "type": "input",
                "block_id": "exclude_weekdays",
                "label": {"type": "plain_text", "text": "🚫 除外する曜日"},
                "optional": True,
                "element": _weekday_checkboxes(s["exclude_weekdays"]),
            },
            # ── 除外時間帯 ──
            {
                "type": "input",
                "block_id": "exclude_time_ranges",
                "label": {"type": "plain_text", "text": "🕐 除外する時間帯"},
                "hint": {"type": "plain_text", "text": "1行につき1つ。例: 12:00-13:00"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "12:00-13:00\n17:30-18:30"},
                    **({"initial_value": "\n".join(f"{r['start']}-{r['end']}" for r in s["exclude_time_ranges"])} if s["exclude_time_ranges"] else {}),
                },
            },
            # ── 表示形式 ──
            {
                "type": "input",
                "block_id": "display_mode",
                "label": {"type": "plain_text", "text": "📊 候補の表示形式"},
                "element": {
                    "type": "radio_buttons",
                    "action_id": "value",
                    "initial_option": (
                        {"text": {"type": "plain_text", "text": "空き枠まとめ形式"}, "description": {"type": "plain_text", "text": "14:00〜16:00（この間で1時間 自由に調整可）と空き窓を提示"}, "value": "windows"}
                        if saved_display == "windows"
                        else {"text": {"type": "plain_text", "text": "スロット形式"}, "description": {"type": "plain_text", "text": "14:00〜15:00 / 14:15〜15:15 … と個別に列挙"}, "value": "slots"}
                    ),
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "スロット形式"},
                            "description": {"type": "plain_text", "text": "14:00〜15:00 / 14:15〜15:15 … と個別に列挙"},
                            "value": "slots",
                        },
                        {
                            "text": {"type": "plain_text", "text": "空き枠まとめ形式"},
                            "description": {"type": "plain_text", "text": "14:00〜16:00（この間で1時間 自由に調整可）と空き窓を提示"},
                            "value": "windows",
                        },
                    ],
                },
            },
            # ── 直接登録（任意） ──
            {
                "type": "input",
                "block_id": "direct_event_title",
                "label": {"type": "plain_text", "text": "📋 イベント名（入力すると検索後すぐカレンダーに登録）"},
                "hint": {"type": "plain_text", "text": "空欄のままにすると通常通りチェックボックスで選択できます"},
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "value",
                    "placeholder": {"type": "plain_text", "text": "例: 商談 株式会社◯◯"},
                },
            },
        ],
    }
