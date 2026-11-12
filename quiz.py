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
QUIZ_HOUR = 12     # از ساعت ۱۲ ظهر به بعد (وقت ایران)
LETTERS = ["الف", "ب", "ج", "د", "ه"]


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def due(state):
    now = extras.iran_now()
    return now.hour >= QUIZ_HOUR and state.get("last") != now.strftime("%Y-%m-%d")


def pick(bank, used):
    fresh = [q for q in bank if q["id"] not in used]
    if not fresh:  # همه استفاده شدند؛ از اول
        used.clear()
        fresh = bank
    return random.choice(fresh) if fresh else None


def plain_text(q, channel):
    """متن کوییز برای بله و ایتا (که کوییز تلگرام ندارند)."""
    topic = f" ({q['topic']})" if q.get("topic") else ""
    opts = "\n".join(f"{LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
    ans = f"{LETTERS[q['answer']]}) {q['options'][q['answer']]}"
    text = (f"🧠 سؤال روز آزمون‌های استخدامی{topic}\n\n{q['q']}\n\n{opts}\n\n"
            f"👇 اول خودتان جواب بدهید، بعد پاسخ را ببینید 👇\n.\n.\n.\n.\n"
            f"✅ پاسخ درست: {ans}")
    if q.get("explain"):
        text += f"\n💡 {q['explain']}"
    return text + f"\n\n📚 سؤال‌های بیشتر در اپ «آزمون یار»\n🆔 {channel}"


def post(tg_token, channel, send_mirrors, dry=False):
    bank = _load(BANK, [])
    state = _load(STATE, {})
    if not bank or not due(state):
        return
    used = state.setdefault("used", [])
    q = pick(bank, used)
    if not q:
        return
    topic = f" | {q['topic']}" if q.get("topic") else ""
    payload = {
        "chat_id": channel,
        "question": f"🧠 سؤال روز{topic}\n{q['q']}"[:300],
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
    r = requests.post(f"https://api.telegram.org/bot{tg_token}/sendPoll", data=payload, timeout=30)
    if not r.ok:
        print(f"[!] quiz: {r.text[:300]}")
        return
    send_mirrors(plain_text(q, channel))
    used.append(q["id"])
    state["last"] = extras.iran_now().strftime("%Y-%m-%d")
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"[✓] quiz posted: {q['id']}")
