import json
import os
import threading
import uuid
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import settings as cfg
import auth

load_dotenv()

app = App(token=os.environ["SLACK_BOT_TOKEN"])

# {session_id: {"slots": [...], "selected": [int, ...], "channel_id": str, "user_id": str}}
session_store: dict = {}


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def resolve_user_emails(user_ids: list[str]) -> list[str]:
    emails = []
    for uid in user_ids:
        try:
            resp = app.client.users_info(user=uid)
            email = resp["user"]["profile"].get("email")
            if email:
                emails.append(email)
        except Exception:
            pass
    return emails


def _send_auth_prompt(client, channel_id: str, user_id: str):
    """未認証ユーザーに認証ボタンを送る。"""
    auth_url = auth.start_oauth(user_id)
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="Google カレンダーとの連携が必要です",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🔐 *初回認証が必要です*\n下のボタンをクリックして Google アカウントを連携してください。",
                },
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Google で認証する"},
                        "style": "primary",
                        "url": auth_url,
                        "action_id": "open_auth_url",
                    }
                ],
            },
        ],
    )


# ---------------------------------------------------------------------------
# /日程調整 → 認証チェック → モーダルを開く
# ---------------------------------------------------------------------------

@app.command("/日程調整")
def handle_schedule(ack, client, body, command):
    ack()
    user_id = command["user_id"]
    channel_id = command["channel_id"]

    if not auth.has_valid_token(user_id):
        _send_auth_prompt(client, channel_id, user_id)
        return

    s = cfg.load(user_id)
    filter_labels = {"keywords": "キーワード除外", "all": "全予定除外", "none": "除外なし"}
    display_labels = {"slots": "スロット形式", "windows": "空き枠まとめ形式"}
    dur_labels = {30: "30分", 60: "1時間", 90: "1時間30分", 120: "2時間"}
    buf_labels = {0: "なし", 15: "15分", 30: "30分"}
    client.chat_postEphemeral(
        channel=channel_id,
        user=user_id,
        text="現在の検索条件",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": (
                        f"⚙️ *現在の検索条件*\n"
                        f"• 所要時間: {dur_labels.get(s['default_duration'], str(s['default_duration'])+'分')}\n"
                        f"• 検索期間: {s['default_weeks_ahead']}週間先まで\n"
                        f"• 時間帯: {s['default_start_time']}〜{s['default_end_time']}\n"
                        f"• 刻み: {s['default_slot_interval']}分\n"
                        f"• バッファ: {buf_labels.get(s['buffer_minutes'], str(s['buffer_minutes'])+'分')}\n"
                        f"• 除外モード: {filter_labels.get(s['filter_mode'], s['filter_mode'])}\n"
                        f"• 表示形式: {display_labels.get(s['display_mode'], s['display_mode'])}"
                    ),
                },
            }
        ],
    )

    from modal import build_modal
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_modal(channel_id=channel_id, user_id=user_id),
    )


@app.action("open_auth_url")
def handle_open_auth_url(ack):
    ack()


@app.command("/日程調整-認証")
def handle_auth_code(ack, respond, command):
    ack()
    user_id = command["user_id"]
    raw = command.get("text", "").strip()

    if not raw:
        respond("⚠️ URLを貼り付けてください。例: `/日程調整-認証 http://localhost/?code=xxxx`")
        return

    try:
        auth.exchange_code(user_id, raw)
        respond("✅ Google カレンダーとの認証が完了しました。`/日程調整` を実行してください。")
    except Exception as e:
        respond(f"❌ 認証に失敗しました。もう一度 `/日程調整` からやり直してください。\n`{str(e)}`")


# ---------------------------------------------------------------------------
# @メンション → デフォルト設定で即検索
# ---------------------------------------------------------------------------

@app.event("app_mention")
def handle_mention(event, client):
    user_id = event["user"]
    channel_id = event["channel"]
    thread_ts = event.get("thread_ts") or event.get("ts")

    if not auth.has_valid_token(user_id):
        _send_auth_prompt(client, channel_id, user_id)
        return

    def process():
        try:
            from calendar_utils import get_available_slots
            from formatter import build_schedule_blocks, build_windows_blocks

            s = cfg.load(user_id)
            start_h, start_m = map(int, s["default_start_time"].split(":"))
            end_h, end_m = map(int, s["default_end_time"].split(":"))
            use_windows = s["display_mode"] == "windows"

            results = get_available_slots(
                user_id=user_id,
                weeks_ahead=s["default_weeks_ahead"],
                start_hour=start_h,
                start_minute=start_m,
                end_hour=end_h,
                end_minute=end_m,
                duration_minutes=s["default_duration"],
                buffer_minutes=s["buffer_minutes"],
                fixed_blocks=s["fixed_blocks"],
                exclude_weekdays=s["exclude_weekdays"],
                exclude_dates=s["exclude_dates"],
                exclude_time_ranges=s["exclude_time_ranges"],
                participants=s["participants"],
                block_keywords=s["block_keywords"],
                ignore_keywords=s["ignore_keywords"],
                filter_mode=s["filter_mode"],
                interval_minutes=s["default_slot_interval"],
                return_windows=use_windows,
            )

            if not results:
                client.chat_postEphemeral(channel=channel_id, user=user_id,
                    text="❌ 条件に合う空き時間が見つかりませんでした。")
                return

            session_id = uuid.uuid4().hex
            session_store[session_id] = {
                "slots": results,
                "selected": [],
                "channel_id": channel_id,
                "user_id": user_id,
                "participant_emails": s["participants"],
                "participant_slack_ids": [],
                "duration_minutes": s["default_duration"],
                "display_mode": s["display_mode"],
                "modal_values": {
                    "duration": s["default_duration"],
                    "start_time": s["default_start_time"],
                    "end_time": s["default_end_time"],
                    "slot_interval": s["default_slot_interval"],
                    "weeks_ahead": s["default_weeks_ahead"],
                    "buffer_minutes": s["buffer_minutes"],
                    "filter_mode": s["filter_mode"],
                    "display_mode": s["display_mode"],
                },
            }

            if use_windows:
                blocks = build_windows_blocks(results, session_id, s["default_duration"])
            else:
                blocks = build_schedule_blocks(results, session_id)

            client.chat_postEphemeral(
                channel=channel_id,
                user=user_id,
                thread_ts=thread_ts,
                blocks=blocks,
                text="日程調整",
            )

        except Exception as e:
            client.chat_postEphemeral(channel=channel_id, user=user_id,
                text=f"❌ エラーが発生しました: {str(e)}")

    threading.Thread(target=process).start()


# ---------------------------------------------------------------------------
# モーダル送信 → カレンダー照会 → チェックボックスを表示
# ---------------------------------------------------------------------------

@app.view("schedule_modal")
def handle_modal_submit(ack, body, client, view):
    ack()

    values = view["state"]["values"]
    metadata = json.loads(view.get("private_metadata", "{}"))
    channel_id = metadata.get("channel_id")
    user_id = body["user"]["id"]

    duration = int(values["duration"]["value"]["selected_option"]["value"])
    weeks_ahead = int(values["weeks_ahead"]["value"]["selected_option"]["value"])
    buffer_minutes = int(values["buffer"]["value"]["selected_option"]["value"])
    filter_mode = values["filter_mode"]["value"]["selected_option"]["value"]

    start_h, start_m = map(int, values["start_time"]["value"]["selected_option"]["value"].split(":"))
    end_h, end_m = map(int, values["end_time"]["value"]["selected_option"]["value"].split(":"))
    interval_minutes = int(values["slot_interval"]["value"]["selected_option"]["value"])

    display_mode = values["display_mode"]["value"]["selected_option"]["value"]

    direct_block = values.get("direct_event_title", {}).get("value") or {}
    direct_title = (direct_block.get("value") or "").strip()

    participants_state = values.get("participants", {}).get("value") or {}
    raw_user_ids = participants_state.get("selected_users") or []

    def process():
        try:
            from calendar_utils import get_available_slots
            from formatter import build_schedule_blocks

            s = cfg.load(user_id)
            participants = list(set(s["participants"] + resolve_user_emails(raw_user_ids)))

            use_windows = (display_mode == "windows")
            results = get_available_slots(
                user_id=user_id,
                weeks_ahead=weeks_ahead,
                start_hour=start_h,
                start_minute=start_m,
                end_hour=end_h,
                end_minute=end_m,
                duration_minutes=duration,
                buffer_minutes=buffer_minutes,
                fixed_blocks=s["fixed_blocks"],
                exclude_weekdays=s["exclude_weekdays"],
                exclude_dates=s["exclude_dates"],
                exclude_time_ranges=s["exclude_time_ranges"],
                participants=participants,
                block_keywords=s["block_keywords"],
                ignore_keywords=s["ignore_keywords"],
                filter_mode=filter_mode,
                interval_minutes=interval_minutes,
                return_windows=use_windows,
            )

            if not results:
                client.chat_postEphemeral(channel=channel_id, user=user_id, text="❌ 条件に合う空き時間が見つかりませんでした。")
                return

            # ── 直接登録モード（スロット形式のみ） ──
            if direct_title and not use_windows:
                from calendar_utils import create_event, format_slot
                event_url, mtg_url = create_event(user_id, direct_title, results[0][0], results[0][1], participants)
                slot_str = format_slot(results[0][0], results[0][1])
                confirm = f"✅ *カレンダーに登録しました*\n• {slot_str}  <{event_url}|カレンダーで確認>"
                if mtg_url:
                    confirm += f"  <{mtg_url}|MTGに参加>"
                client.chat_postEphemeral(channel=channel_id, user=user_id, text=confirm)
                mention_str = " ".join(f"<@{uid}>" for uid in raw_user_ids) if raw_user_ids else "なし"
                ch_msg = f"📅 *{direct_title}*\n• {slot_str}  <{event_url}|カレンダーで確認>"
                if mtg_url:
                    ch_msg += f"\n  🔗 <{mtg_url}|MTG URL>"
                ch_msg += f"\n参加者: {mention_str}"
                client.chat_postMessage(channel=channel_id, text=ch_msg)
                return

            # ── チェックボックス表示 ──
            session_id = uuid.uuid4().hex
            session_store[session_id] = {
                "slots": results,
                "selected": [],
                "channel_id": channel_id,
                "user_id": user_id,
                "participant_emails": participants,
                "participant_slack_ids": raw_user_ids,
                "duration_minutes": duration,
                "display_mode": display_mode,
                "modal_values": {
                    "duration": duration,
                    "start_time": f"{start_h:02d}:{start_m:02d}",
                    "end_time": f"{end_h:02d}:{end_m:02d}",
                    "slot_interval": interval_minutes,
                    "weeks_ahead": weeks_ahead,
                    "buffer_minutes": buffer_minutes,
                    "filter_mode": filter_mode,
                    "display_mode": display_mode,
                },
            }

            if use_windows:
                from formatter import build_windows_blocks
                blocks = build_windows_blocks(results, session_id, duration)
            else:
                blocks = build_schedule_blocks(results, session_id)

            client.chat_postEphemeral(channel=channel_id, user=user_id, blocks=blocks, text="日程調整")

        except Exception as e:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text=f"❌ エラー: {str(e)}")

    threading.Thread(target=process).start()


# ---------------------------------------------------------------------------
# チェックボックス変更
# ---------------------------------------------------------------------------

@app.action("date_selected")
def handle_date_selected(ack, action):
    ack()
    session_id = action.get("block_id", "").removeprefix("cb_")
    if session_id in session_store:
        session_store[session_id]["selected"] = [
            int(opt["value"]) for opt in action.get("selected_options", [])
        ]


# ---------------------------------------------------------------------------
# ✉️ メール文面を作る
# ---------------------------------------------------------------------------

@app.action("create_email")
def handle_create_email(ack, action, respond):
    ack()
    session = session_store.get(action["value"])
    if not session:
        respond("⚠️ セッションが切れました。再度 `/日程調整` を実行してください。")
        return
    selected = [session["slots"][i] for i in session["selected"] if i < len(session["slots"])]
    from formatter import format_email_text
    respond({"text": format_email_text(selected), "response_type": "ephemeral", "replace_original": False})


# ---------------------------------------------------------------------------
# ✉️ メール文面を作る（空き枠まとめ形式）
# ---------------------------------------------------------------------------

@app.action("create_email_window")
def handle_create_email_window(ack, action, respond):
    ack()
    session = session_store.get(action["value"])
    if not session:
        respond("⚠️ セッションが切れました。再度 `/日程調整` を実行してください。")
        return
    selected = [session["slots"][i] for i in session["selected"] if i < len(session["slots"])]
    duration = session.get("duration_minutes", 60)
    from formatter import format_email_windows
    respond({"text": format_email_windows(selected, duration), "response_type": "ephemeral", "replace_original": False})


# ---------------------------------------------------------------------------
# 📅 カレンダーに登録 → イベント名モーダルを開く
# ---------------------------------------------------------------------------

@app.action("register_calendar")
def handle_register_calendar(ack, action, body, client, respond):
    ack()
    session = session_store.get(action["value"])
    if not session:
        respond("⚠️ セッションが切れました。再度 `/日程調整` を実行してください。")
        return

    selected = [session["slots"][i] for i in session["selected"] if i < len(session["slots"])]
    if not selected:
        respond({"text": "⚠️ 日程を選択してください。", "response_type": "ephemeral", "replace_original": False})
        return

    from modal import build_event_modal
    client.views_open(trigger_id=body["trigger_id"], view=build_event_modal(action["value"], selected))


# ---------------------------------------------------------------------------
# event_modal 送信 → イベント作成 → URL を返す
# ---------------------------------------------------------------------------

@app.view("event_modal")
def handle_event_modal_submit(ack, body, client, view):
    ack()

    metadata = json.loads(view.get("private_metadata", "{}"))
    session_id = metadata.get("session_id")
    user_id = body["user"]["id"]
    event_title = view["state"]["values"]["event_title"]["value"]["value"].strip()
    mtg_url_block = view["state"]["values"].get("meeting_url", {}).get("value") or {}
    custom_meeting_url = (mtg_url_block.get("value") or "").strip() or None

    session = session_store.get(session_id)
    if not session:
        return

    selected = [session["slots"][i] for i in session["selected"] if i < len(session["slots"])]
    channel_id = session.get("channel_id")
    attendees = session.get("participant_emails", [])
    participant_slack_ids = session.get("participant_slack_ids", [])

    def process():
        try:
            from calendar_utils import create_event, format_slot

            created = []
            for start, end in selected:
                event_url, mtg_url = create_event(user_id, event_title, start, end, attendees, custom_meeting_url)
                created.append((start, end, event_url, mtg_url))

            # 本人へ完了通知（ephemeral）
            confirm_lines = [f"✅ *カレンダーに登録しました*（{len(created)}件）\n"]
            for start, end, event_url, mtg_url in created:
                line = f"• {format_slot(start, end)}  <{event_url}|カレンダーで確認>"
                if mtg_url:
                    line += f"  <{mtg_url}|MTGに参加>"
                confirm_lines.append(line)
            client.chat_postEphemeral(channel=channel_id, user=user_id, text="\n".join(confirm_lines))

            # チャンネルにMTG情報を投稿
            mention_str = " ".join(f"<@{uid}>" for uid in participant_slack_ids) if participant_slack_ids else "なし"
            thread_lines = [f"📅 *{event_title}*"]
            for start, end, event_url, mtg_url in created:
                thread_lines.append(f"• {format_slot(start, end)}  <{event_url}|カレンダーで確認>")
                if mtg_url:
                    thread_lines.append(f"  🔗 <{mtg_url}|MTG URL>")
            thread_lines.append(f"参加者: {mention_str}")
            client.chat_postMessage(channel=channel_id, text="\n".join(thread_lines))

        except Exception as e:
            client.chat_postEphemeral(channel=channel_id, user=user_id, text=f"❌ イベント作成に失敗しました: {str(e)}")

    threading.Thread(target=process).start()


# ---------------------------------------------------------------------------
# 📋 全件テキスト表示
# ---------------------------------------------------------------------------

@app.action("show_all")
def handle_show_all(ack, action, respond):
    ack()
    session = session_store.get(action["value"])
    if not session:
        respond("⚠️ セッションが切れました。再度 `/日程調整` を実行してください。")
        return
    from formatter import format_all_text
    respond({"text": format_all_text(session["slots"]), "response_type": "ephemeral", "replace_original": False})


# ---------------------------------------------------------------------------
# ⚙️ 条件を変えて再検索（メンション後に使う）
# ---------------------------------------------------------------------------

@app.action("reopen_modal")
def handle_reopen_modal(ack, action, body, client):
    ack()
    session = session_store.get(action["value"])
    if not session:
        return
    from modal import build_modal
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_modal(channel_id=session["channel_id"], user_id=session["user_id"]),
    )


# ---------------------------------------------------------------------------
# 💾 この条件をデフォルトに保存
# ---------------------------------------------------------------------------

@app.action("save_as_default")
def handle_save_as_default(ack, action, respond):
    ack()
    session = session_store.get(action["value"])
    if not session:
        respond("⚠️ セッションが切れました。")
        return
    user_id = session.get("user_id")
    cfg.save_modal_defaults(user_id, session.get("modal_values", {}))
    respond({"text": "✅ この条件をデフォルトとして保存しました。次回から自動で反映されます。", "response_type": "ephemeral", "replace_original": False})


# ---------------------------------------------------------------------------
# /日程調整-設定 → 設定モーダルを開く
# ---------------------------------------------------------------------------

@app.command("/日程調整-設定")
def handle_settings(ack, client, body, command):
    ack()
    user_id = command["user_id"]
    text = command.get("text", "").strip()

    # テキストコマンドが渡された場合は従来通り処理
    if text:
        respond_text = cfg.apply_command(user_id, text)
        client.chat_postEphemeral(channel=command["channel_id"], user=user_id, text=respond_text)
        return

    # 引数なし → 設定モーダルを開く
    from modal import build_settings_modal
    client.views_open(trigger_id=body["trigger_id"], view=build_settings_modal(user_id))


@app.view("settings_modal")
def handle_settings_modal_submit(ack, body, view):
    ack()
    user_id = body["user"]["id"]
    values = view["state"]["values"]

    s = cfg.load(user_id)
    s["default_duration"] = int(values["default_duration"]["value"]["selected_option"]["value"])
    s["default_start_time"] = values["default_start_time"]["value"]["selected_option"]["value"]
    s["default_end_time"] = values["default_end_time"]["value"]["selected_option"]["value"]
    s["default_slot_interval"] = int(values["default_slot_interval"]["value"]["selected_option"]["value"])
    s["buffer_minutes"] = int(values["default_buffer"]["value"]["selected_option"]["value"])
    s["default_weeks_ahead"] = int(values["default_weeks_ahead"]["value"]["selected_option"]["value"])
    s["filter_mode"] = values["filter_mode"]["value"]["selected_option"]["value"]
    s["display_mode"] = values["display_mode"]["value"]["selected_option"]["value"]
    cfg.save(user_id, s)


# ---------------------------------------------------------------------------
# 起動
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import web
    threading.Thread(target=web.run, kwargs={"port": int(os.environ.get("PORT", 8080))}, daemon=True).start()
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
