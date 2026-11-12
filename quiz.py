"""کوییز روزانه: هر روز یک سؤال تستی آزمون‌های استخدامی به شکل کوییز تلگرام.

سؤال‌ها در quiz.json:  [{"id": "...", "q": "...", "options": ["..", "..", "..", ".."],
                         "answer": 0, "explain": "...", "topic": "هوش"}]
سؤال‌های منتشرشده در quiz_state.json ثبت می‌شوند تا تکرار نشوند.
"""
import json
import random
from pathlib import Path

import requests

import extras

BASE = Path(__file__).parent
BANK = BASE / "quiz.json"
STATE = BASE / "quiz_state.json"
QUIZ_HOURS = [12, 20]   # دو سؤال در روز: ظهر و شب (وقت ایران)
LETTERS = ["الف", "ب", "ج", "د", "ه"]


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def due(state):
    """نوبت بعدی امروز که رسیده و هنوز منتشر نشده (یا None)."""
    now = extras.iran_now()
    today = now.strftime("%Y-%m-%d")
    done = state.get("slots", []) if state.get("day") == today else []
    for h in QUIZ_HOURS:
        if now.hour >= h and h not in done:
            return h
    return None


def pick(bank, used):
    fresh = [q for q in bank if q["id"] not in used]
    if not fresh:  # همه استفاده شدند؛ از اول
        used.clear()
        fresh = bank
    return random.choice(fresh) if fresh else None


NOTE = ("📖 این سؤال از «منابع عمومی» است که در همه‌ی آزمون‌های استخدامی می‌آید؛ "
        "یادگرفتنش برای هر آزمونی که شرکت کنید به کارتان می‌آید.")


def hashtags(q):
    tags = ["#سؤال_روز", "#آزمون_استخدامی"]
    if q.get("topic"):
        tags.insert(1, "#" + q["topic"].replace("‌", "_").replace(" ", "_"))
    return " ".join(tags)


def intro_text(q, channel):
    """پیام کوتاه قبل از کوییز تلگرام (کوییز هشتگ قابل‌کلیک ندارد)."""
    topic = f" | {q['topic']}" if q.get("topic") else ""
    return (f"🧠 <b>سؤال روز{topic}</b>\n\n{NOTE}\n\n👇 جواب خودتان را در کوییز زیر بزنید."
            f"\n\n{hashtags(q)}")


def plain_text(q, channel):
    """متن کوییز برای بله و ایتا (که کوییز تلگرام ندارند)."""
    topic = f" ({q['topic']})" if q.get("topic") else ""
    opts = "\n".join(f"{LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
    ans = f"{LETTERS[q['answer']]}) {q['options'][q['answer']]}"
    text = (f"🧠 سؤال روز آزمون‌های استخدامی{topic}\n\n{NOTE}\n\n❓ {q['q']}\n\n{opts}\n\n"
            f"👇 اول خودتان جواب بدهید، بعد پاسخ را ببینید 👇\n.\n.\n.\n.\n"
            f"✅ پاسخ درست: {ans}")
    if q.get("explain"):
        text += f"\n💡 {q['explain']}"
    return text + f"\n\n{hashtags(q)}\n\n📚 سؤال‌های بیشتر در اپ «آزمون یار»\n🆔 {channel}"


def post(tg_token, channel, send_mirrors, dry=False, force=False):
    """force: همین الان یک سؤال (جدا از نوبت‌های روزانه)."""
    bank = _load(BANK, [])
    state = _load(STATE, {})
    slot = None if force else due(state)
    if not bank or (slot is None and not force):
        return
    used = state.setdefault("used", [])
    q = pick(bank, used)
    if not q:
        return
    topic = f" | {q['topic']}" if q.get("topic") else ""
    payload = {
        "chat_id": channel,
        "question": q["q"][:300],
        "options": json.dumps([{"text": o[:100]} for o in q["options"]], ensure_ascii=False),
        "type": "quiz",
        "correct_option_id": q["answer"],
        "is_anonymous": True,
    }
    if q.get("explain"):
        payload["explanation"] = q["explain"][:200]
    if dry:
        print(f"---- QUIZ (dry run) ----\n{payload['question']}\n{q['options']} → {q['answer']}")
        return
    intro = requests.post(f"https://api.telegram.org/bot{tg_token}/sendMessage",
                          json={"chat_id": channel, "text": intro_text(q, channel),
                                "parse_mode": "HTML"}, timeout=30)
    if not intro.ok:
        print(f"[!] quiz intro: {intro.text[:200]}")
    r = requests.post(f"https://api.telegram.org/bot{tg_token}/sendPoll", data=payload, timeout=30)
    if not r.ok:
        print(f"[!] quiz: {r.text[:300]}")
        return
    send_mirrors(plain_text(q, channel))
    used.append(q["id"])
    if slot is not None:
        today = extras.iran_now().strftime("%Y-%m-%d")
        if state.get("day") != today:
            state["day"], state["slots"] = today, []
        state["slots"].append(slot)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"[✓] quiz posted: {q['id']}")
