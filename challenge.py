"""چالش هفتگی کوییز: مخاطب از دکمه‌ی زیر کوییز کانال وارد ربات می‌شود، همان سؤال را
جواب می‌دهد و امتیاز می‌گیرد. جمعه‌شب «برترین‌های هفته» در کانال منتشر می‌شود.

mirror.py (که همیشه روشن است) پیام‌های ربات را به handle_update می‌دهد.
امتیازها رمزنگاری‌شده در challenge.enc ذخیره می‌شوند (مخزن عمومی است).
"""
import base64
import datetime
import hashlib
import html
import json
import os
import time
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken

BASE = Path(__file__).parent
STATE_FILE = BASE / "challenge.enc"
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG = f"https://api.telegram.org/bot{TOKEN}"
CHANNEL = "@" + os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam").lstrip("@")
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "estekhdam_news_bot")
SUPPORT = os.environ.get("CHALLENGE_SUPPORT", "")    # آیدی پشتیبانی برای گرفتن جایزه
APP_URL = os.environ.get("AZMOONYAR_APP_URL", "https://myket.ir/app/ir.azmoonyar.app")
LEADERBOARD_DAY, LEADERBOARD_HOUR = 4, 21            # جمعه ساعت ۹ شب (Monday=0)
TOP_N, WINNERS = 10, 3
MAX_AGE_DAYS = 3                                     # فقط سؤال‌های ۳ روز اخیر امتیاز دارند
LETTERS = ["الف", "ب", "ج", "د"]
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MEDALS = ["🥇", "🥈", "🥉"]


def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(("challenge|" + TOKEN).encode()).digest())
    return Fernet(key)


def iran_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)


def week_key(now=None):
    """هفته از شنبه شروع می‌شود؛ کلید = تاریخ شنبه."""
    now = now or iran_now()
    sat = now.date() - datetime.timedelta(days=(now.weekday() - 5) % 7)
    return sat.isoformat()


def load():
    try:
        raw = _fernet().decrypt(STATE_FILE.read_bytes())
        st = json.loads(raw)
    except (FileNotFoundError, InvalidToken, ValueError):
        st = {}
    st.setdefault("week", week_key())
    st.setdefault("users", {})      # uid → {"name", "score", "answered": [qid]}
    st.setdefault("posted_weeks", [])
    return st


def save(st):
    STATE_FILE.write_bytes(_fernet().encrypt(json.dumps(st, ensure_ascii=False).encode()))


def _bank():
    try:
        return {q["id"]: q for q in json.loads((BASE / "quiz.json").read_text(encoding="utf-8"))}
    except Exception:
        return {}


def _posted():
    try:
        return json.loads((BASE / "quiz_state.json").read_text(encoding="utf-8")).get("posted", {})
    except Exception:
        return {}


def _api(method, **payload):
    try:
        return requests.post(f"{TG}/{method}", json=payload, timeout=30).json()
    except Exception as e:
        print(f"[challenge] {method}: {e}"[:200])
        return {}


def _fa(n):
    return str(n).translate(FA)


def _rank(st, uid):
    order = sorted(st["users"].items(), key=lambda kv: (-kv[1]["score"], kv[1].get("t", 0)))
    for i, (u, _) in enumerate(order, 1):
        if u == uid:
            return i, len(order)
    return None, len(order)


def _promo():
    t = "📲 تست‌های بیشتر از منابع عمومی در اپ «آزمون یار»"
    return f'{t}: <a href="{APP_URL}">دانلود</a>' if APP_URL else t


def _score_text(st, uid):
    u = st["users"].get(uid)
    if not u:
        return ("🏆 هنوز در چالش این هفته امتیازی نداری.\n"
                f"زیر هر «سؤال روز» در کانال {CHANNEL} دکمه‌ی «جواب بده و امتیاز بگیر» را بزن.")
    rank, total = _rank(st, uid)
    return (f"🏆 امتیاز این هفته‌ی تو: <b>{_fa(u['score'])}</b>\n"
            f"📊 رتبه: {_fa(rank)} از {_fa(total)} نفر\n"
            "برترین‌های هفته جمعه ساعت ۹ شب در کانال اعلام می‌شوند و به ۳ نفر اول "
            "کد تخفیف بسته‌های تست اپ آزمون یار هدیه داده می‌شود 🎁")


def _send_question(chat_id, q, uid, st):
    if q["id"] in st["users"].get(uid, {}).get("answered", []):
        _api("sendMessage", chat_id=chat_id, parse_mode="HTML",
             text="✅ به این سؤال قبلاً جواب داده‌ای.\n\n" + _score_text(st, uid))
        return
    opts = "\n".join(f"{LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
    kb = [[{"text": f"{LETTERS[i]}) {o}"[:60], "callback_data": f"a|{q['id']}|{i}"}]
          for i, o in enumerate(q["options"])]
    _api("sendMessage", chat_id=chat_id, parse_mode="HTML",
         text=f"🧠 <b>چالش هفته | {q.get('topic', 'سؤال روز')}</b>\n\n❓ {q['q']}\n\n{opts}\n\n"
              "👇 گزینه‌ی درست را انتخاب کن (فقط یک بار):",
         reply_markup={"inline_keyboard": kb})


def handle_update(upd, st):
    """True برمی‌گرداند اگر وضعیت تغییر کرد (برای ذخیره)."""
    if "callback_query" in upd:
        return _on_answer(upd["callback_query"], st)
    msg = upd.get("message")
    if not msg or msg.get("chat", {}).get("type") != "private":
        return False
    chat_id, uid = msg["chat"]["id"], str(msg["from"]["id"])
    text = (msg.get("text") or "").strip()
    if text.startswith("/start q_"):
        qid = text.split("q_", 1)[1].strip()
        q = _bank().get(qid)
        posted = _posted().get(qid, 0)
        if not q or time.time() - posted > MAX_AGE_DAYS * 86400:
            _api("sendMessage", chat_id=chat_id, parse_mode="HTML",
                 text="⏳ مهلت امتیاز این سؤال تمام شده؛ سؤال‌های تازه را در کانال دنبال کن.\n\n"
                      + _score_text(st, uid))
            return False
        _send_question(chat_id, q, uid, st)
        return False
    if text in ("/score", "امتیاز من", "/start"):
        welcome = ("سلام 👋 به چالش هفتگی «آزمون یار» خوش آمدی!\n"
                   "هر روز زیر «سؤال روز» کانال دکمه‌ی چالش را بزن، جواب بده و امتیاز جمع کن.\n\n"
                   if text == "/start" else "")
        _api("sendMessage", chat_id=chat_id, parse_mode="HTML",
             text=welcome + _score_text(st, uid),
             reply_markup={"keyboard": [[{"text": "امتیاز من"}]], "resize_keyboard": True})
    return False


def _on_answer(cq, st):
    data = cq.get("data", "")
    if not data.startswith("a|"):
        return False
    _, qid, idx = data.split("|")
    uid = str(cq["from"]["id"])
    q = _bank().get(qid)
    if not q or time.time() - _posted().get(qid, 0) > MAX_AGE_DAYS * 86400:
        _api("answerCallbackQuery", callback_query_id=cq["id"], text="مهلت این سؤال تمام شده")
        return False
    u = st["users"].setdefault(uid, {"name": "", "score": 0, "answered": []})
    u["name"] = html.escape((cq["from"].get("first_name") or "")[:20], quote=False)
    if qid in u["answered"]:
        _api("answerCallbackQuery", callback_query_id=cq["id"], text="قبلاً جواب داده‌ای ✅")
        return False
    u["answered"].append(qid)
    right = int(idx) == q["answer"]
    if right:
        u["score"] += 1
        u["t"] = time.time()  # در امتیاز برابر، کسی که زودتر رسیده جلوتر است
    ans = f"{LETTERS[q['answer']]}) {q['options'][q['answer']]}"
    head = "🎉 <b>آفرین! درست جواب دادی (+۱ امتیاز)</b>" if right else \
        f"❌ <b>جوابت درست نبود.</b>\nپاسخ درست: {ans}"
    expl = f"\n💡 {q['explain']}" if q.get("explain") else ""
    _api("answerCallbackQuery", callback_query_id=cq["id"], text="درست بود 🎉" if right else "نادرست ❌")
    m = cq.get("message", {})
    _api("editMessageText", chat_id=m.get("chat", {}).get("id"), message_id=m.get("message_id"),
         parse_mode="HTML", disable_web_page_preview=True,
         text=f"❓ {q['q']}\n\n{head}{expl}\n\n{_score_text(st, uid)}\n\n{_promo()}")
    return True


def roll_week(st):
    """هفته‌ی جدید: امتیازها صفر شود."""
    wk = week_key()
    if st["week"] != wk:
        st["week"], st["users"] = wk, {}


def leaderboard_due(st):
    """جمعه از ساعت ۹ شب؛ اگر آن موقع ربات خاموش بود، اول هفته‌ی بعد (قبل از صفر شدن)."""
    if st["week"] in st["posted_weeks"]:
        return False
    now = iran_now()
    return week_key(now) != st["week"] or (now.weekday() == LEADERBOARD_DAY
                                          and now.hour >= LEADERBOARD_HOUR)


def leaderboard_text(st):
    order = sorted(((u, v) for u, v in st["users"].items() if v["score"] > 0),
                   key=lambda kv: (-kv[1]["score"], kv[1].get("t", 0)))[:TOP_N]
    lines = []
    for i, (_, v) in enumerate(order):
        badge = MEDALS[i] if i < 3 else f"{_fa(i + 1)}."
        lines.append(f"{badge} {v['name'] or 'بی‌نام'}: {_fa(v['score'])} امتیاز")
    total = len(st["users"])
    body = "\n".join(lines) if lines else "این هفته کسی امتیاز نگرفت؛ هفته‌ی بعد نوبت توست!"
    return order, (
        "🏆 <b>برترین‌های چالش هفته</b>\n\n" + body +
        f"\n\n👥 {_fa(total)} نفر در چالش این هفته شرکت کردند."
        "\n🎁 به ۳ نفر اول کد تخفیف بسته‌های تست اپ «آزمون یار» هدیه داده می‌شود."
        "\n\n🔄 چالش هفته‌ی جدید از فردا شروع می‌شود؛ زیر هر «سؤال روز» دکمه‌ی چالش را بزن!"
        f"\n\n#چالش_هفته #آزمون_استخدامی\n🆔 {CHANNEL}")


def post_leaderboard(st, mirror=None):
    if not any(v["score"] > 0 for v in st["users"].values()):
        st["posted_weeks"] = (st["posted_weeks"] + [st["week"]])[-10:]
        print("[challenge] no scores this week; leaderboard skipped")
        return True
    order, text = leaderboard_text(st)
    r = _api("sendMessage", chat_id=CHANNEL, text=text, parse_mode="HTML")
    if not r.get("ok"):
        print(f"[challenge] leaderboard failed: {r}")
        return False
    if mirror:
        mirror(text)
    for i, (uid, v) in enumerate(order[:WINNERS]):
        how = (f"برای دریافت کد تخفیف، همین پیام را برای {SUPPORT} فوروارد کن." if SUPPORT
               else "کد تخفیف به‌زودی از طرف پشتیبانی آزمون یار برایت فرستاده می‌شود.")
        _api("sendMessage", chat_id=int(uid), parse_mode="HTML",
             text=f"{MEDALS[i]} تبریک {v['name']}! در چالش این هفته نفر {_fa(i + 1)} شدی 🎉\n"
                  f"🎁 جایزه‌ات: کد تخفیف بسته‌های تست اپ «آزمون یار»\n{how}\n"
                  f"(کد پیگیری: {st['week']}-{_fa(i + 1)}-{uid[-4:]})")
    st["posted_weeks"] = (st["posted_weeks"] + [st["week"]])[-10:]
    print("[challenge] leaderboard posted")
    return True
