import json
import os
import re
from pathlib import Path

SETTINGS_DIR = os.environ.get("SETTINGS_DIR", "user_settings")
Path(SETTINGS_DIR).mkdir(exist_ok=True)

WEEKDAY_MAP = {"月": 0, "火": 1, "水": 2, "木": 3, "金": 4}
WEEKDAY_NAMES = ["月", "火", "水", "木", "金"]

DEFAULT: dict = {
    "buffer_minutes": 0,
    "fixed_blocks": [],
    "exclude_weekdays": [],
    "exclude_dates": [],
    "exclude_time_ranges": [],
    "participants": [],
    "block_keywords": [
        "商談", "面談", "面接", "MTG", "mtg", "ミーティング", "会議",
        "打合せ", "打ち合わせ", "sync", "Sync", "interview", "Interview",
        "ブロック", "有給", "午前休", "午後休",
    ],
    "ignore_keywords": ["準備", "前準備"],
    "filter_mode": "keywords",
    "display_mode": "slots",
    # モーダルのデフォルト値
    "default_duration": 60,
    "default_start_time": "10:00",
    "default_end_time": "19:00",
    "default_slot_interval": 30,
    "default_weeks_ahead": 2,
}


def _path(user_id: str) -> str:
    return os.path.join(SETTINGS_DIR, f"{user_id}.json")


def load(user_id: str) -> dict:
    path = _path(user_id)
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {**DEFAULT, **data}
    return DEFAULT.copy()


def save(user_id: str, s: dict) -> None:
    with open(_path(user_id), "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)


def save_modal_defaults(user_id: str, values: dict) -> None:
    """モーダルで使用した条件をユーザーのデフォルトとして保存する。"""
    s = load(user_id)
    s.update({
        "default_duration": values.get("duration", s["default_duration"]),
        "default_start_time": values.get("start_time", s["default_start_time"]),
        "default_end_time": values.get("end_time", s["default_end_time"]),
        "default_slot_interval": values.get("slot_interval", s["default_slot_interval"]),
        "default_weeks_ahead": values.get("weeks_ahead", s["default_weeks_ahead"]),
        "buffer_minutes": values.get("buffer_minutes", s["buffer_minutes"]),
        "filter_mode": values.get("filter_mode", s["filter_mode"]),
        "display_mode": values.get("display_mode", s["display_mode"]),
    })
    save(user_id, s)


def apply_command(user_id: str, text: str) -> str:
    s = load(user_id)
    text = text.strip()

    if text == "リセット":
        save(user_id, DEFAULT.copy())
        return "✅ 設定をリセットしました。"

    # バッファ N分
    m = re.fullmatch(r"バッファ\s*(\d+)\s*分", text)
    if m:
        s["buffer_minutes"] = int(m.group(1))
        save(user_id, s)
        return f"✅ バッファを {m.group(1)}分 に設定しました。"

    # ブロック追加 ラベル HH:MM-HH:MM
    m = re.fullmatch(r"ブロック追加\s+(\S+)\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", text)
    if m:
        label, start, end = m.group(1), m.group(2), m.group(3)
        s["fixed_blocks"] = [b for b in s["fixed_blocks"] if b["label"] != label]
        s["fixed_blocks"].append({"label": label, "start": start, "end": end})
        save(user_id, s)
        return f"✅ 固定ブロック「{label} {start}〜{end}」を追加しました。"

    # ブロック削除 ラベル
    m = re.fullmatch(r"ブロック削除\s+(\S+)", text)
    if m:
        label = m.group(1)
        before = len(s["fixed_blocks"])
        s["fixed_blocks"] = [b for b in s["fixed_blocks"] if b["label"] != label]
        save(user_id, s)
        return f"✅ 固定ブロック「{label}」を削除しました。" if len(s["fixed_blocks"]) < before else f"⚠️ 「{label}」は見つかりませんでした。"

    # 除外曜日
    m = re.fullmatch(r"除外曜日\s+([月火水木金]+)", text)
    if m:
        days = [WEEKDAY_MAP[c] for c in m.group(1) if c in WEEKDAY_MAP]
        s["exclude_weekdays"] = sorted(set(s["exclude_weekdays"] + days))
        save(user_id, s)
        names = "、".join(WEEKDAY_NAMES[d] + "曜" for d in days)
        return f"✅ 除外曜日に {names} を追加しました。"

    # 除外時間
    m = re.fullmatch(r"除外時間\s+(\d{1,2}:\d{2})-(\d{1,2}:\d{2})", text)
    if m:
        r = {"start": m.group(1), "end": m.group(2)}
        if r not in s["exclude_time_ranges"]:
            s["exclude_time_ranges"].append(r)
        save(user_id, s)
        return f"✅ 除外時間帯 {r['start']}〜{r['end']} を追加しました。"

    # 除外日
    m = re.fullmatch(r"除外日\s+(\d{4}-\d{2}-\d{2})", text)
    if m:
        d = m.group(1)
        if d not in s["exclude_dates"]:
            s["exclude_dates"].append(d)
        save(user_id, s)
        return f"✅ 除外日 {d} を追加しました。"

    # 参加者追加
    m = re.fullmatch(r"参加者追加\s+(\S+@\S+)", text)
    if m:
        email = m.group(1)
        if email not in s["participants"]:
            s["participants"].append(email)
        save(user_id, s)
        return f"✅ 参加者 {email} を追加しました。"

    # 参加者削除
    m = re.fullmatch(r"参加者削除\s+(\S+@\S+)", text)
    if m:
        email = m.group(1)
        before = len(s["participants"])
        s["participants"] = [p for p in s["participants"] if p != email]
        save(user_id, s)
        return f"✅ 参加者 {email} を削除しました。" if len(s["participants"]) < before else f"⚠️ {email} は登録されていません。"

    # busyワード追加
    m = re.fullmatch(r"busyワード追加\s+(\S+)", text)
    if m:
        kw = m.group(1)
        if kw not in s["block_keywords"]:
            s["block_keywords"].append(kw)
        save(user_id, s)
        return f"✅ busyワード「{kw}」を追加しました。"

    # 除外ワード追加
    m = re.fullmatch(r"除外ワード追加\s+(\S+)", text)
    if m:
        kw = m.group(1)
        if kw not in s["ignore_keywords"]:
            s["ignore_keywords"].append(kw)
        save(user_id, s)
        return f"✅ 除外ワード「{kw}」を追加しました。"

    return (
        "⚠️ コマンドが認識できませんでした。\n"
        "`/日程調整-設定` で設定画面を開いてください。"
    )
