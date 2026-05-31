import os
from datetime import datetime, timedelta, date
from googleapiclient.discovery import build
import pytz
import pickle

TIMEZONE = "Asia/Tokyo"
DAYS_JP = ["月", "火", "水", "木", "金", "土", "日"]


def get_calendar_service(user_id: str):
    """Slack user_id に対応する Google Calendar サービスを返す。"""
    from auth import load_credentials
    creds = load_credentials(user_id)
    return build("calendar", "v3", credentials=creds)


def _is_blocked(title: str, block_keywords: list[str], ignore_keywords: list[str]) -> bool:
    """
    タイトルが busy 扱いかどうかを返す。
    - block_keywords のいずれかを含む → busy 候補
    - さらに ignore_keywords のいずれかも含む → 除外（free扱い）
    例: "商談準備" は block("商談") に合致するが ignore("準備") にも合致 → free
    """
    t = title.lower()
    if not any(kw.lower() in t for kw in block_keywords):
        return False
    return not any(kw.lower() in t for kw in ignore_keywords)


def _get_own_busy(service, calendar_id: str, time_min: str, time_max: str,
                  tz, block_keywords: list, ignore_keywords: list,
                  filter_mode: str = "keywords") -> list:
    """
    自カレンダーのbusy期間を返す。
    - filter_mode='keywords': block_keywords に合致する予定のみ busy 扱い
    - filter_mode='all'     : 全予定を busy 扱い（freebusy API 使用）
    - filter_mode='none'    : カレンダーを無視（空リストを返す）
    """
    if filter_mode == "none":
        return []

    if filter_mode == "all":
        body = {"timeMin": time_min, "timeMax": time_max, "items": [{"id": calendar_id}]}
        result = service.freebusy().query(body=body).execute()
        busy = []
        for b in result["calendars"][calendar_id]["busy"]:
            start = datetime.fromisoformat(b["start"].replace("Z", "+00:00")).astimezone(tz)
            end = datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(tz)
            busy.append((start, end))
        return busy

    # filter_mode == "keywords"
    events = []
    page_token = None
    while True:
        resp = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page_token,
        ).execute()
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    busy = []
    for ev in events:
        title = ev.get("summary", "")
        if not _is_blocked(title, block_keywords, ignore_keywords):
            continue
        start_raw = ev["start"].get("dateTime")
        end_raw = ev["end"].get("dateTime")
        if not start_raw or not end_raw:
            continue  # 終日予定はスキップ
        start = datetime.fromisoformat(start_raw.replace("Z", "+00:00")).astimezone(tz)
        end = datetime.fromisoformat(end_raw.replace("Z", "+00:00")).astimezone(tz)
        busy.append((start, end))
    return busy


def _get_participants_busy(service, emails: list[str], time_min: str, time_max: str, tz) -> list:
    """参加者のfreebusy（タイトル不明のため全予定をbusy扱い）を返す。"""
    if not emails:
        return []
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": e} for e in emails],
    }
    result = service.freebusy().query(body=body).execute()
    busy = []
    for email in emails:
        for b in result["calendars"].get(email, {}).get("busy", []):
            start = datetime.fromisoformat(b["start"].replace("Z", "+00:00")).astimezone(tz)
            end = datetime.fromisoformat(b["end"].replace("Z", "+00:00")).astimezone(tz)
            busy.append((start, end))
    return busy


def get_available_slots(
    user_id: str,
    weeks_ahead=2,
    start_hour=10,
    start_minute=0,
    end_hour=19,
    end_minute=0,
    duration_minutes=60,
    buffer_minutes=0,
    fixed_blocks=None,
    exclude_weekdays=None,
    exclude_dates=None,
    exclude_time_ranges=None,
    participants=None,
    block_keywords=None,
    ignore_keywords=None,
    filter_mode="keywords",
    interval_minutes=30,
    return_windows=False,
):
    service = get_calendar_service(user_id)
    tz = pytz.timezone(TIMEZONE)

    fixed_blocks = fixed_blocks or []
    exclude_weekdays = set(exclude_weekdays or [])
    exclude_dates = set(exclude_dates or [])
    exclude_time_ranges = exclude_time_ranges or []
    participants = participants or []
    block_keywords = block_keywords or ["MTG", "ミーティング", "会議", "商談", "打合せ", "打ち合わせ", "面談"]
    ignore_keywords = ignore_keywords or ["準備"]
    buffer_td = timedelta(minutes=buffer_minutes)

    end_total_minutes = end_hour * 60 + end_minute

    now = datetime.now(tz)
    now_total_minutes = now.hour * 60 + now.minute
    if now_total_minutes >= end_total_minutes - 60:
        search_start = (now + timedelta(days=1)).replace(
            hour=start_hour, minute=start_minute, second=0, microsecond=0
        )
    else:
        search_start = now.replace(second=0, microsecond=0)
        if search_start.minute % 30 != 0:
            search_start = search_start.replace(minute=0) + timedelta(hours=1)

    search_end = now + timedelta(weeks=weeks_ahead)
    time_min = search_start.isoformat()
    time_max = search_end.isoformat()

    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    own_busy = _get_own_busy(service, calendar_id, time_min, time_max, tz, block_keywords, ignore_keywords, filter_mode)
    participant_busy = _get_participants_busy(service, participants, time_min, time_max, tz)
    all_busy = sorted(own_busy + participant_busy, key=lambda x: x[0])

    available_slots = []
    current_day = search_start.date()
    end_day = search_end.date()

    while current_day <= end_day:
        if current_day.weekday() >= 5:
            current_day += timedelta(days=1)
            continue
        if current_day.weekday() in exclude_weekdays:
            current_day += timedelta(days=1)
            continue
        if current_day.isoformat() in exclude_dates:
            current_day += timedelta(days=1)
            continue

        day_start = tz.localize(datetime(current_day.year, current_day.month, current_day.day, start_hour, start_minute))
        day_end = tz.localize(datetime(current_day.year, current_day.month, current_day.day, end_hour, end_minute))

        if current_day == search_start.date():
            day_start = max(day_start, search_start)

        day_busy = [
            (max(bs, day_start), min(be, day_end))
            for bs, be in all_busy
            if bs < day_end and be > day_start
        ]
        for block in fixed_blocks:
            bs = _parse_time(block["start"], current_day, tz)
            be = _parse_time(block["end"], current_day, tz)
            if bs < day_end and be > day_start:
                day_busy.append((max(bs, day_start), min(be, day_end)))
        for rng in exclude_time_ranges:
            bs = _parse_time(rng["start"], current_day, tz)
            be = _parse_time(rng["end"], current_day, tz)
            if bs < day_end and be > day_start:
                day_busy.append((max(bs, day_start), min(be, day_end)))

        if buffer_td.total_seconds() > 0:
            day_busy = [
                (max(bs - buffer_td, day_start), min(be + buffer_td, day_end))
                for bs, be in day_busy
            ]
        day_busy = _merge_intervals(day_busy)

        free_start = day_start
        for busy_start, busy_end in day_busy:
            if free_start < busy_start:
                if return_windows:
                    _add_window(free_start, busy_start, duration_minutes, available_slots)
                else:
                    _add_slots(free_start, busy_start, duration_minutes, available_slots, interval_minutes)
            free_start = max(free_start, busy_end)

        if free_start < day_end:
            if return_windows:
                _add_window(free_start, day_end, duration_minutes, available_slots)
            else:
                _add_slots(free_start, day_end, duration_minutes, available_slots, interval_minutes)

        current_day += timedelta(days=1)

    return available_slots


def _parse_time(time_str: str, day: date, tz) -> datetime:
    h, m = map(int, time_str.split(":"))
    return tz.localize(datetime(day.year, day.month, day.day, h, m))


def _merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [tuple(i) for i in merged]


def _add_window(free_start, free_end, duration_minutes, windows):
    """空き時間帯を duration_minutes 以上の窓だけ収録する。"""
    from datetime import timedelta
    if (free_end - free_start).total_seconds() >= duration_minutes * 60:
        windows.append((free_start, free_end))


def _add_slots(free_start, free_end, duration_minutes, slots, interval_minutes=30):
    slot_start = free_start
    # 刻み単位に切り上げ
    if slot_start.minute % interval_minutes != 0:
        slot_start += timedelta(minutes=interval_minutes - slot_start.minute % interval_minutes)
        slot_start = slot_start.replace(second=0, microsecond=0)

    while True:
        slot_end = slot_start + timedelta(minutes=duration_minutes)
        if slot_end > free_end:
            break
        slots.append((slot_start, slot_end))
        slot_start += timedelta(minutes=interval_minutes)


def format_slot(slot_start, slot_end) -> str:
    day = DAYS_JP[slot_start.weekday()]
    return f"{slot_start.month}月{slot_start.day}日（{day}）{slot_start.strftime('%H:%M')}〜{slot_end.strftime('%H:%M')}"


def create_event(
    user_id: str,
    title: str,
    start_dt: datetime,
    end_dt: datetime,
    attendees: list[str] | None = None,
    meeting_url: str | None = None,
) -> tuple[str, str]:
    """
    Google Calendar にイベントを作成する。
    meeting_url が指定されていればそれを使用、なければ Google Meet を自動生成。
    戻り値: (event_url, mtg_url)
    """
    import uuid as _uuid
    service = get_calendar_service(user_id)
    calendar_id = os.environ.get("GOOGLE_CALENDAR_ID", "primary")

    event = {
        "summary": title,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": TIMEZONE},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": TIMEZONE},
    }
    if attendees:
        event["attendees"] = [{"email": e} for e in attendees]

    if meeting_url:
        # カスタムURL（Zoom等）をメモとして追加
        event["description"] = f"MTG URL: {meeting_url}"
        mtg_url = meeting_url
        result = service.events().insert(
            calendarId=calendar_id,
            body=event,
            sendUpdates="all" if attendees else "none",
        ).execute()
    else:
        # Google Meet を自動生成
        event["conferenceData"] = {
            "createRequest": {
                "requestId": _uuid.uuid4().hex,
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        result = service.events().insert(
            calendarId=calendar_id,
            body=event,
            conferenceDataVersion=1,
            sendUpdates="all" if attendees else "none",
        ).execute()
        mtg_url = ""
        for entry in result.get("conferenceData", {}).get("entryPoints", []):
            if entry.get("entryPointType") == "video":
                mtg_url = entry.get("uri", "")
                break

    return result.get("htmlLink", ""), mtg_url
