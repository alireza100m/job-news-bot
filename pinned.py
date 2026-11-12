"""پست سنجاق‌شده‌ی «تقویم ثبت‌نام آزمون‌ها» که هر روز ویرایش (نه ارسال دوباره) می‌شود.

تلگرام و بله: ارسال یک بار + سنجاق، سپس editMessageText. ایتا ویرایش ندارد.
وضعیت در pinned.json ذخیره می‌شود.
"""
import hashlib
import html
import json
import re
from pathlib import Path

import requests

import extras
import followups

STATE_FILE = Path(__file__).parent / "pinned.json"
NEAR_DAYS = 3
MAX_OPEN = 25
MAX_SOON = 8
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]


def load():
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def _fa(n):
    return str(n).translate(followups.FA_DIGITS)


def _name(title):
    t = re.sub(r"^(استخدام|آزمون استخدامی|آزمون)\s+", "", title.strip())
    return html.escape(t, quote=False)


def _link(name, msg_id, channel):
    if msg_id and channel.startswith("@"):
        return f'<a href="https://t.me/{channel[1:]}/{msg_id}">{name}</a>'
    return name


def build_text(tracked, calendar, channel):
    rows = extras.open_registrations(tracked, calendar)
    msg_of = {}
    for v in tracked.values():
        if v.get("msg"):
            msg_of[v["title"]] = v["msg"]

    def line(title, deadline, left):
        end = extras._end_words(deadline)
        tail = f"تا {end}" if end else ""
        if left == 0:
            tail += " (امروز آخرین مهلت)"
        elif left <= NEAR_DAYS:
            tail += f" ({_fa(left)} روز مانده)"
        return f"• {_link(_name(title), msg_of.get(title), channel)}: {tail.strip()}"

    near = [line(*r) for r in rows if r[2] <= NEAR_DAYS]
    opened = [line(*r) for r in rows if r[2] > NEAR_DAYS][:MAX_OPEN]

    soon = []
    for c in calendar:
        if c.get("phase") != "soon":
            continue
        start = followups.date_words(c.get("pre", {}).get("start"))
        nm = _name(c["title"])
        if any(nm in s for s in soon):
            continue
        soon.append(f"• {nm}: " + (f"شروع از {start}" if start else "به‌زودی"))
    soon = soon[:MAX_SOON]

    now = extras.iran_now()
    y, m, d = followups.today_jalali()
    date = f"{WEEKDAYS[now.weekday()]} {_fa(d)} {followups.MONTH_NAMES[m - 1]} {_fa(y)}"
    parts = ["📌 <b>تقویم ثبت‌نام آزمون‌های استخدامی</b>", f"🕒 به‌روزرسانی: {date}"]
    if near:
        parts.append("🔴 <b>مهلت نزدیک</b>\n" + "\n".join(near))
    if opened:
        parts.append("🟢 <b>ثبت‌نام باز</b>\n" + "\n".join(opened))
    if soon:
        parts.append("🟡 <b>به‌زودی</b>\n" + "\n".join(soon))
    if not (near or opened or soon):
        parts.append("فعلاً ثبت‌نام بازی نیست؛ به‌محض شروع، همین‌جا اعلام می‌شود.")
    parts.append("👆 روی نام هر آزمون بزنید تا پست کامل و لینک ثبت‌نامش را ببینید.")
    parts.append(f"📚 برای آمادگی آزمون‌های استخدامی: <b>آزمون یار</b>\n🆔 {channel}")
    return "\n\n".join(parts)


def _call(base, method, payload):
    r = requests.post(f"{base}/{method}", json=payload, timeout=30)
    try:
        return r.json()
    except ValueError:
        return {"ok": False, "description": r.text[:200]}


def _publish(base, chat, text, msg_id, plain=False):
    """ویرایش پست قبلی یا (اگر نبود/پاک شده بود) ارسال و سنجاق پست تازه. شناسه را برمی‌گرداند."""
    body = {"chat_id": chat, "text": text}
    if not plain:
        body.update(parse_mode="HTML", disable_web_page_preview=True)
    if msg_id:
        res = _call(base, "editMessageText", {**body, "message_id": msg_id})
        desc = str(res.get("description", ""))
        if res.get("ok") or "not modified" in desc:
            return msg_id
        print(f"[pinned] edit failed ({desc[:120]}), sending a new one")
    res = _call(base, "sendMessage", body)
    if not res.get("ok"):
        print(f"[pinned] send failed: {str(res)[:200]}")
        return msg_id
    new_id = res["result"]["message_id"]
    pin = _call(base, "pinChatMessage", {"chat_id": chat, "message_id": new_id,
                                         "disable_notification": True})
    print(f"[pinned] sent {new_id}, pin: {pin.get('ok')} {str(pin.get('description', ''))[:120]}")
    return new_id


def update(tracked, calendar, tg_token, channel, bale_token="", bale_channel="", dry=False):
    text = build_text(tracked, calendar, channel)
    state = load()
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    if dry:
        print("---- PINNED (dry run) ----\n" + text)
        return
    if state.get("hash") == digest and state.get("tg"):
        return  # چیزی عوض نشده
    state["tg"] = _publish(f"https://api.telegram.org/bot{tg_token}", channel, text, state.get("tg"))
    if bale_token and bale_channel:
        plain = html.unescape(re.sub(r"<[^>]+>", "", text))
        plain = "\n\n".join(p for p in plain.split("\n\n") if not p.startswith("👆"))
        state["bale"] = _publish(f"https://tapi.bale.ai/bot{bale_token}", bale_channel, plain,
                                 state.get("bale"), plain=True)
    state["hash"] = digest
    save(state)
    print("[pinned] updated")
