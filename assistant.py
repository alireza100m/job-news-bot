"""دستیار هوشمند ربات (تلگرام و بله): جذب مخاطب و تبدیل به مشتری اپ «آزمون یار».

- /start: خوش‌آمد + پرسیدن «برای کدام آزمون‌ها آماده می‌شوی؟» (چند انتخابی)
- ذخیره‌ی علاقه‌ی هر کاربر (رمزنگاری‌شده در leads.enc، چون مخزن عمومی است)
- «آزمون‌های باز من»: ثبت‌نام‌های باز مطابق علاقه‌ی کاربر، با لینک ثبت‌نام رسمی
- یادآور شخصی: آزمون تازه در دسته‌ی کاربر + ۲ روز/۱ روز/روز آخر مهلت (۸ تا ۲۱ ایران)
- جواب سؤال‌ها با Gemini (اگر GEMINI_API_KEY باشد)؛ وگرنه جست‌وجوی ساده در آزمون‌ها

mirror.py (که همیشه روشن است) پیام‌ها را به handle_update می‌دهد و tick را مرتب صدا می‌زند.
"""
import base64
import datetime
import hashlib
import json
import os
import re
import threading
import time
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken

import extras
import followups

BASE = Path(__file__).parent
STATE_FILE = BASE / "leads.enc"
TRACK_FILE = BASE / "tracked.json"
TG_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
BALE_TOKEN = os.environ.get("BALE_BOT_TOKEN", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
APP_URL = os.environ.get("AZMOONYAR_APP_URL", "https://myket.ir/app/ir.azmoonyar.app")
CHANNEL = "@" + os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam").lstrip("@")
DISABLED = os.environ.get("ASSISTANT_DISABLED") == "1"

AI_PER_DAY = 15           # سقف سؤال هوشمند برای هر کاربر در روز
REMIND_LEFT = (2, 1, 0)   # روزهای مانده برای یادآوری شخصی
REMIND_HOURS = (8, 21)
SENDS_PER_TICK = 25       # سقف پیام خودکار در هر دور (محدودیت سرعت تلگرام)
FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

# دسته‌ها: (کلید هشتگ در extras.CATEGORIES، نام نمایشی)
TOPICS = [
    ("آزمون_فراگیر", "آزمون فراگیر دستگاه‌ها"),
    ("آموزش_و_پرورش", "آموزش و پرورش"),
    ("بهداشت_و_درمان", "بهداشت و درمان"),
    ("بانک", "بانک و بیمه"),
    ("نظامی", "نظامی و انتظامی"),
    ("قوه_قضاییه", "قوه قضاییه"),
    ("شرکت_دولتی", "شرکت‌های دولتی (نفت، برق…)"),
    ("دانشگاه", "دانشگاه‌ها"),
    ("شهرداری", "شهرداری و استانداری"),
]
TOPIC_NAMES = dict(TOPICS)
BTN_OPEN = "📋 آزمون‌های باز من"
BTN_TOPICS = "⚙️ تغییر علاقه‌ها"
BTN_APP = "📲 اپ آزمون یار"
BTN_TEST = "🧠 تست رایگان"
BTN_INVITE = "👥 دعوت دوستان (جایزه)"
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "estekhdam_news_bot")
# ادمین‌ها: شناسه‌ی عددی تلگرام (با /myid در ربات)، جدا با کاما؛ برای بله: bale:123
ADMINS = {a if ":" in a else f"tg:{a}"
          for a in re.split(r"[,\s]+", os.environ.get("ASSISTANT_ADMINS", "")) if a}
REF_GOAL = 3              # تعداد دعوت برای جایزه
REF_PRIZE = os.environ.get("REFERRAL_PRIZE", "کد تخفیف بسته‌های تست اپ «آزمون یار»")
REF_REWARD = os.environ.get("REFERRAL_REWARD", "")   # متن جایزه (مثلاً کد تخفیف) — فقط در Secrets
TESTS_PER_DAY = 5         # تست رایگان روزانه برای هر کاربر (با دکمه)
DAILY_TEST_HOUR = 17      # ساعت ارسال خودکار «تست روز» (وقت ایران)
LETTERS = ["الف", "ب", "ج", "د"]


def main_kb(p=None):
    rows = [[{"text": BTN_OPEN}], [{"text": BTN_TEST}]]
    if not p or p.name == "tg":
        rows[1].append({"text": BTN_INVITE})
    rows.append([{"text": BTN_TOPICS}, {"text": BTN_APP}])
    return {"keyboard": rows, "resize_keyboard": True}


MAIN_KB = main_kb()  # پیش‌فرض

_lock = threading.RLock()


# ---------- پلتفرم ----------
class Platform:
    def __init__(self, name, base):
        self.name, self.base = name, base

    def api(self, method, **payload):
        try:
            r = requests.post(f"{self.base}/{method}", json=payload, timeout=30)
            res = r.json()
            if not res.get("ok"):
                print(f"[assistant:{self.name}] {method}: {str(res)[:200]}")
            return res
        except Exception as e:
            print(f"[assistant:{self.name}] {method}: {e}"[:200])
            return {}


PLATFORMS = {}
if TG_TOKEN:
    PLATFORMS["tg"] = Platform("tg", f"https://api.telegram.org/bot{TG_TOKEN}")
if BALE_TOKEN:
    PLATFORMS["bale"] = Platform("bale", f"https://tapi.bale.ai/bot{BALE_TOKEN}")


# ---------- وضعیت ----------
def _fernet():
    key = base64.urlsafe_b64encode(hashlib.sha256(("leads|" + TG_TOKEN).encode()).digest())
    return Fernet(key)


def load():
    try:
        st = json.loads(_fernet().decrypt(STATE_FILE.read_bytes()))
    except (FileNotFoundError, InvalidToken, ValueError):
        st = {}
    st.setdefault("users", {})   # "tg:123" → {name, topics, src, joined, seen, reminded, ai}
    st.setdefault("known", [])   # آزمون‌هایی که خبر «آزمون تازه»شان داده شده
    return st


def save(st):
    with _lock:
        STATE_FILE.write_bytes(_fernet().encrypt(json.dumps(st, ensure_ascii=False).encode()))


def iran_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)


def _tracked():
    try:
        return json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def topics_of(title):
    return [tag for tag, words in extras.CATEGORIES
            if any(re.search(rf"(?<!\w){re.escape(w)}", title) for w in words)]


def open_exams(tracked=None):
    """[(عنوان، مهلت، روز مانده، اطلاعات کامل)] ثبت‌نام‌های باز، نزدیک‌ترین مهلت اول."""
    tracked = tracked if tracked is not None else _tracked()
    by_title = {v["title"]: v for v in tracked.values()}
    return [(t, d, left, by_title.get(t, {})) for t, d, left in extras.open_registrations(tracked, [])]


def _match(user, title):
    tps = user.get("topics") or []
    return "all" in tps or bool(set(tps) & set(topics_of(title)))


def _fa(x):
    return str(x).translate(FA)


def _left_words(left):
    return {0: "امروز آخرین مهلت", 1: "فردا آخرین مهلت"}.get(left, f"{_fa(left)} روز مانده")


def exam_line(title, deadline, left, info):
    end = followups.date_words(deadline)
    s = f"🔹 <b>{followups.subject(title)}</b>\n     📅 مهلت: تا {end or '—'} ({_left_words(left)})"
    if info.get("exam"):
        s += f"\n     📝 آزمون: {_fa(info['exam'])}"
    if info.get("reg_url"):
        s += f'\n     🔗 <a href="{info["reg_url"]}">ثبت‌نام</a>'
    return s


def app_line():
    return f'📲 برای تمرین تست‌های استخدامی، اپ «آزمون یار» رو نصب کن: <a href="{APP_URL}">دانلود از مایکت</a>'


# ---------- پیام‌ها ----------
def _topics_kb(user):
    sel = set(user.get("topics") or [])
    rows = [[{"text": ("✅ " if tag in sel else "▫️ ") + name, "callback_data": f"t|{tag}"}]
            for tag, name in TOPICS]
    rows.append([{"text": ("✅ " if "all" in sel else "▫️ ") + "همه‌ی آزمون‌های دولتی",
                  "callback_data": "t|all"}])
    rows.append([{"text": "✔️ ثبت انتخاب‌ها", "callback_data": "t|done"}])
    return {"inline_keyboard": rows}


TOPICS_Q = ("🎯 برای کدوم آزمون‌ها آماده میشی؟\n"
            "می‌تونی چند تا رو انتخاب کنی، بعد «ثبت انتخاب‌ها» رو بزن.")


def _welcome(name):
    hi = f"سلام {_esc(name)} 👋" if name else "سلام 👋"
    return (f"{hi}\nبه دستیار «آزمون یار» خوش اومدی!\n\n"
            "من اینجام که:\n"
            "• ثبت‌نام‌های باز استخدامی رشته‌ی خودت رو بهت بگم\n"
            "• قبل از تموم شدن مهلت ثبت‌نام بهت یادآوری کنم\n"
            "• به سؤال‌هات درباره‌ی آزمون‌ها جواب بدم\n"
            "• اگه بخوای، هر روز تست رایگان برات بفرستم 🧠\n\n" + TOPICS_Q)


def plain(text):
    """بله HTML را کامل پشتیبانی نمی‌کند: لینک‌ها کنار متن نوشته و تگ‌ها حذف می‌شوند."""
    text = re.sub(r'<a href="([^"]+)">([^<]+)</a>', r"\2: \1", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def _payload(p, text, **kw):
    if p.name == "bale":
        return {"text": plain(text), **kw}
    return {"text": text, "parse_mode": "HTML", "disable_web_page_preview": True, **kw}


def _send(p, chat_id, text, kb=None):
    payload = {"chat_id": chat_id, **_payload(p, text)}
    if kb:
        payload["reply_markup"] = kb
    return p.api("sendMessage", **payload)


def _send_open(p, chat_id, user):
    rows = [r for r in open_exams() if _match(user, r[0])]
    if not rows:
        txt = ("فعلاً ثبت‌نام بازی در دسته‌هایی که انتخاب کردی نداریم.\n"
               "به محض شروع ثبت‌نام آزمون تازه، خودم بهت خبر میدم 🔔")
    else:
        txt = "📋 <b>ثبت‌نام‌های باز برای تو</b>\n\n" + "\n\n".join(exam_line(*r) for r in rows[:12])
    _send(p, chat_id, txt + "\n\n" + app_line(), main_kb(p))


def handle_update(pname, upd, st):
    """True اگر وضعیت تغییر کرد."""
    if DISABLED:
        return False
    p = PLATFORMS.get(pname)
    if not p:
        return False
    with _lock:
        if "callback_query" in upd:
            return _on_callback(p, upd["callback_query"], st)
        msg = upd.get("message")
        if not msg or msg.get("chat", {}).get("type") != "private":
            return False
        return _on_message(p, msg, st)


def _user(st, pname, frm):
    key = f"{pname}:{frm['id']}"
    u = st["users"].get(key)
    new = u is None
    if new:
        u = st["users"][key] = {"topics": [], "joined": int(time.time()), "reminded": {}}
    u["name"] = (frm.get("first_name") or "")[:30]
    u["seen"] = int(time.time())
    u.pop("blocked", None)
    return key, u, new


def _on_message(p, msg, st):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip()
    key, u, new = _user(st, p.name, msg["from"])
    u["uname"] = (msg["from"].get("username") or "")[:40]
    if text.startswith("/start"):
        arg = text[6:].strip()
        if arg and not u.get("src"):
            u["src"] = re.sub(r"[^\w-]", "", arg)[:30]  # منبع ورود (برای آمار)
        if new and arg.startswith("r_"):
            _referral(p, st, key, u, arg[2:])
        _send(p, chat_id, _welcome(u["name"]), _topics_kb(u))
        return True
    if text == "/myid":
        _send(p, chat_id, f"شناسه‌ی شما: <code>{key}</code>", main_kb(p))
        return True
    if key in ADMINS and _admin_message(p, st, key, chat_id, text):
        return True
    if text in (BTN_TEST, "/test"):
        _send_test(p, chat_id, u)
        return True
    if text in (BTN_INVITE, "/invite"):
        _send_invite(p, chat_id, key, u)
        return True
    if text == "/daily":
        u["daily_on"] = not u.get("daily_on")
        _send(p, chat_id, "🔔 تست روزانه روشن شد؛ هر روز عصر یه تست برات میاد."
              if u["daily_on"] else "🔕 تست روزانه خاموش شد. با /daily دوباره روشنش کن.", main_kb(p))
        return True
    if text in (BTN_TOPICS, "/topics"):
        _send(p, chat_id, TOPICS_Q, _topics_kb(u))
        return True
    if text in (BTN_OPEN, "/open"):
        if not u.get("topics"):
            _send(p, chat_id, TOPICS_Q, _topics_kb(u))
        else:
            _send_open(p, chat_id, u)
        return True
    if text in (BTN_APP, "/app"):
        _send(p, chat_id, "📲 اپ «آزمون یار»: هزاران تست استخدامی با پاسخ تشریحی، "
                          f"دسته‌بندی‌شده بر اساس آزمون.\n\n<a href=\"{APP_URL}\">دانلود از مایکت</a>",
              main_kb(p))
        return True
    if not text:
        _send(p, chat_id, "فعلاً فقط پیام متنی رو می‌فهمم 🙂 سؤالت رو بنویس.", main_kb(p))
        return True
    _answer(p, chat_id, u, text)
    return True


def _on_callback(p, cq, st):
    data = cq.get("data", "")
    if data in ("d|yes", "d|no"):
        key, u, _ = _user(st, p.name, cq["from"])
        u["daily_on"] = data == "d|yes"
        p.api("answerCallbackQuery", callback_query_id=cq["id"])
        m = cq.get("message", {})
        p.api("editMessageText", chat_id=m.get("chat", {}).get("id"), message_id=m.get("message_id"),
              **_payload(p, "🔔 عالیه! هر روز عصر یه تست رایگان برات می‌فرستم. (خاموش کردن: /daily)"
                         if u["daily_on"] else
                         "باشه 🌸 تست روزانه نمی‌فرستم. هر وقت خواستی دکمه‌ی «🧠 تست رایگان» رو بزن "
                         "یا با /daily روشنش کن."))
        return True
    if data.startswith(("q|", "qn")):
        key, u, _ = _user(st, p.name, cq["from"])
        return _on_test_answer(p, cq, u, data)
    if data.startswith("b|"):
        key = f"{p.name}:{cq['from']['id']}"
        return key in ADMINS and _on_broadcast_cb(p, cq, st, key, data)
    if not data.startswith("t|"):
        return False
    key, u, _ = _user(st, p.name, cq["from"])
    tag = data[2:]
    m = cq.get("message", {})
    chat_id, mid = m.get("chat", {}).get("id"), m.get("message_id")
    if tag == "done":
        if not u.get("topics"):
            p.api("answerCallbackQuery", callback_query_id=cq["id"], text="حداقل یکی رو انتخاب کن")
            return True
        p.api("answerCallbackQuery", callback_query_id=cq["id"], text="ثبت شد ✅")
        names = "، ".join("همه‌ی آزمون‌ها" if t == "all" else TOPIC_NAMES.get(t, t) for t in u["topics"])
        p.api("editMessageText", chat_id=chat_id, message_id=mid, **_payload(
            p, f"✅ علاقه‌هات ثبت شد: <b>{names}</b>\n\n"
               "از این به بعد آزمون‌های تازه و یادآوری مهلت‌ها رو همین‌جا برات می‌فرستم 🔔\n"
               "هر سؤالی هم درباره‌ی آزمون‌ها داشتی، همین‌جا بپرس."))
        _send_open(p, chat_id, u)
        if not u.get("daily_asked"):
            u["daily_asked"] = True
            _ask_daily(p, chat_id)
        return True
    if tag != "all" and tag not in TOPIC_NAMES:
        return False
    sel = set(u.get("topics") or [])
    sel ^= {tag}
    u["topics"] = [t for t, _ in TOPICS if t in sel] + (["all"] if "all" in sel else [])
    p.api("answerCallbackQuery", callback_query_id=cq["id"])
    if p.name == "tg":
        p.api("editMessageReplyMarkup", chat_id=chat_id, message_id=mid, reply_markup=_topics_kb(u))
    else:  # بله: ویرایش متن همراه با دکمه‌ها
        p.api("editMessageText", chat_id=chat_id, message_id=mid,
              **_payload(p, TOPICS_Q, reply_markup=_topics_kb(u)))
    return True


# ---------- جواب سؤال ----------
SYSTEM = """تو «دستیار آزمون یار» هستی، دستیار یک کانال اخبار استخدامی دولتی ایران و اپلیکیشن تست‌های استخدامی «آزمون یار».
قوانین:
- فارسی روان، صمیمی و کوتاه جواب بده (حداکثر ۸ خط). از علائم نگارشی درست و نیم‌فاصله استفاده کن.
- تاریخ، مهلت، شرایط یا لینکی را که در «اطلاعات آزمون‌ها» نیست هرگز از خودت نساز. اگر نمی‌دانی، بگو این اطلاعات را نداری و پیشنهاد کن آگهی رسمی یا کانال {channel} را ببیند.
- فقط لینک‌های ثبت‌نام موجود در اطلاعات و لینک اپ را بده. نام یا لینک سایت‌های خبری دیگر را نیاور.
- اگر سؤال درباره‌ی آمادگی، منابع یا تست است، اپ «آزمون یار» را پیشنهاد کن: {app}
- سؤال‌های بی‌ربط به استخدام و آزمون را مؤدبانه رد کن.
- خروجی متن ساده باشد (بدون Markdown و ستاره)."""


def _context(user):
    rows = open_exams()
    lines = []
    for t, d, left, info in rows:
        parts = [f"عنوان: {t}", f"مهلت ثبت‌نام: {d} ({left} روز مانده)"]
        for k, label in (("exam", "تاریخ آزمون"), ("card", "کارت ورود"), ("reg_url", "لینک ثبت‌نام")):
            if info.get(k):
                parts.append(f"{label}: {info[k]}")
        lines.append(" | ".join(parts))
    tps = "، ".join(TOPIC_NAMES.get(t, "همه") for t in user.get("topics") or []) or "نامشخص"
    today = followups.today_jalali()
    return (f"امروز: {today[0]}/{today[1]:02d}/{today[2]:02d}\nعلاقه‌ی کاربر: {tps}\n"
            "اطلاعات آزمون‌ها (ثبت‌نام‌های باز):\n" + ("\n".join(lines) or "فعلاً موردی نیست."))


def ask_gemini(user, question):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent")
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM.format(channel=CHANNEL, app=APP_URL)}]},
        "contents": [{"role": "user", "parts": [{"text": _context(user) + "\n\nسؤال کاربر: " + question[:800]}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 600},
    }
    r = requests.post(url, json=body, timeout=40, headers={"x-goog-api-key": GEMINI_KEY})
    r.raise_for_status()
    parts = r.json()["candidates"][0]["content"]["parts"]
    return "".join(x.get("text", "") for x in parts).strip()


def _search(text):
    words = [w for w in re.findall(r"[\w‌]{3,}", text) if w not in followups.STOP]
    return [r for r in open_exams() if any(w in r[0] for w in words)]


def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# جواب‌های آماده برای سؤال‌های رایج (وقتی هوش مصنوعی در دسترس نیست)
FAQ = [
    (r"درس|بخون|مطالعه|قبول|آماده|برنامه|موفق|رتبه|نمره", (
        "📚 <b>چند توصیه برای قبولی در آزمون استخدامی:</b>\n\n"
        "۱. اول دفترچه‌ی آزمون رو بخون و ببین چه درس‌هایی و با چه ضریبی میاد.\n"
        "۲. «عمومی‌ها» (ادبیات، معارف، ریاضی و آمار، هوش، اطلاعات عمومی و ICDL) رو جدی بگیر؛ برای همه مشترکه و نمره‌ساز.\n"
        "۳. هر روز تست بزن و زمان بگیر؛ تست‌زنی از خوندن خالی مهم‌تره.\n"
        "۴. اشتباه‌هات رو یادداشت کن و دوباره مرور کن.\n"
        "۵. هفته‌ی آخر فقط مرور و آزمون آزمایشی.\n\n"
        "🎯 برای تمرین تست‌های واقعی دسته‌بندی‌شده با پاسخ تشریحی، اپ «آزمون یار» رو نصب کن:\n"
        '<a href="{app}">دانلود از مایکت</a>')),
    (r"منبع|منابع|کتاب|جزوه", (
        "📖 منابع هر آزمون در <b>دفترچه‌ی رسمی</b> همون آزمون اعلام میشه.\n"
        "معمولاً شامل «عمومی‌ها» (ادبیات، معارف، ریاضی و آمار، هوش، اطلاعات عمومی، ICDL) و «تخصصی‌های رشته»ست.\n\n"
        "📲 تست‌های هر دو بخش رو می‌تونی توی اپ «آزمون یار» تمرین کنی: "
        '<a href="{app}">دانلود از مایکت</a>')),
    (r"شرایط|سن|مدرک|سهمیه|بومی|ایثارگر", (
        "📝 شرایط سنی، مدرک، سهمیه و بومی بودن برای هر آزمون فرق داره و در <b>آگهی رسمی</b> همون آزمون اومده.\n"
        "اسم آزمون رو بنویس یا «📋 آزمون‌های باز من» رو بزن تا لینک ثبت‌نام رسمیش رو ببینی.")),
    (r"اپ|برنامه|نرم ?افزار|خرید|قیمت|بسته|تخفیف", (
        "📲 اپ «آزمون یار»: تست‌های استخدامی دسته‌بندی‌شده با پاسخ تشریحی.\n"
        '<a href="{app}">دانلود از مایکت</a>')),
    (r"^(سلام|درود|خوبی|ممنون|مرسی|تشکر)", (
        "سلام 🌸 در خدمتم! اسم آزمونی که دنبالشی رو بنویس، یا «📋 آزمون‌های باز من» رو بزن.")),
]


def _faq(text):
    for pattern, reply in FAQ:
        if re.search(pattern, text):
            return reply.format(app=APP_URL)
    return None


def _answer(p, chat_id, u, text):
    day = iran_now().strftime("%Y-%m-%d")
    ai = u.setdefault("ai", {})
    if ai.get("day") != day:
        ai.clear()
        ai["day"], ai["n"] = day, 0
    if GEMINI_KEY and ai["n"] < AI_PER_DAY:
        p.api("sendChatAction", chat_id=chat_id, action="typing")
        try:
            reply = ask_gemini(u, text)
            ai["n"] += 1
            if reply:
                _send(p, chat_id, _esc(reply), main_kb(p))
                return
        except Exception as e:
            print(f"[assistant] gemini failed: {e}"[:300])
    faq = _faq(text)
    greeting = re.match(r"(سلام|درود|خوبی|ممنون|مرسی|تشکر)", text)
    hits = [] if greeting else _search(text)
    if faq and not hits:
        _send(p, chat_id, faq, main_kb(p))
        return
    if hits:
        _send(p, chat_id, "این‌ها رو پیدا کردم:\n\n" + "\n\n".join(exam_line(*r) for r in hits[:6])
              + "\n\n" + app_line(), main_kb(p))
    else:
        _send(p, chat_id, "سؤالت رو گرفتم 🙏 فعلاً جواب دقیقی براش ندارم.\n"
                          f"آخرین اخبار استخدامی رو توی کانال {CHANNEL} ببین، "
                          f"یا «{BTN_OPEN}» رو بزن.", main_kb(p))


# ---------- تست رایگان ----------
_BANK = None


def _bank():
    global _BANK
    if _BANK is None:
        try:
            _BANK = json.loads((BASE / "quiz.json").read_text(encoding="utf-8"))
        except Exception:
            _BANK = []
    return _BANK


def _pick_question(u):
    bank = _bank()
    if not bank:
        return None
    used = u.setdefault("q_used", [])
    left = [q for q in bank if q["id"] not in used]
    if not left:  # همه را دیده؛ از اول
        used.clear()
        left = bank
    q = left[int(time.time() * 1000) % len(left)]
    used.append(q["id"])
    return q


def _question_msg(p, chat_id, q, head):
    opts = "\n".join(f"{LETTERS[i]}) {o}" for i, o in enumerate(q["options"]))
    kb = {"inline_keyboard": [[{"text": f"{LETTERS[i]}) {o}"[:60], "callback_data": f"q|{q['id']}|{i}"}]
                              for i, o in enumerate(q["options"])]}
    return _send(p, chat_id, f"{head} | {q.get('topic', '')}</b>\n\n❓ {q['q']}\n\n{opts}\n\n"
                             "👇 گزینه‌ی درست رو انتخاب کن:", kb)


def _ask_daily(p, chat_id):
    _send(p, chat_id, "🧠 دوست داری هر روز عصر یه <b>تست رایگان</b> از عمومی‌های آزمون استخدامی "
                      "(معارف، اطلاعات عمومی، قانون اساسی) برات بفرستم؟",
          {"inline_keyboard": [[{"text": "✅ آره، بفرست", "callback_data": "d|yes"},
                                {"text": "❌ نه، ممنون", "callback_data": "d|no"}]]})


def _send_test(p, chat_id, u):
    day = iran_now().strftime("%Y-%m-%d")
    qd = u.setdefault("q_day", {})
    if qd.get("day") != day:
        qd.clear()
        qd["day"], qd["n"] = day, 0
    if qd["n"] >= TESTS_PER_DAY:
        _send(p, chat_id, f"🎯 امروز {_fa(TESTS_PER_DAY)} تست رایگانت رو زدی، آفرین!\n"
                          "فردا دوباره تست تازه داری.\n\n"
                          "برای تمرین نامحدود با هزاران تست و پاسخ تشریحی، اپ «آزمون یار» رو نصب کن:\n"
                          f'<a href="{APP_URL}">دانلود از مایکت</a>', main_kb(p))
        return
    q = _pick_question(u)
    if not q:
        _send(p, chat_id, "فعلاً تستی در دسترس نیست.", main_kb(p))
        return
    qd["n"] += 1
    _question_msg(p, chat_id, q, f"🧠 <b>تست رایگان {_fa(qd['n'])} از {_fa(TESTS_PER_DAY)}")


def _on_test_answer(p, cq, u, data):
    m = cq.get("message", {})
    chat_id, mid = m.get("chat", {}).get("id"), m.get("message_id")
    if data == "qn":
        p.api("answerCallbackQuery", callback_query_id=cq["id"])
        _send_test(p, chat_id, u)
        return True
    _, qid, idx = data.split("|")
    q = next((x for x in _bank() if x["id"] == qid), None)
    if not q:
        p.api("answerCallbackQuery", callback_query_id=cq["id"], text="این سؤال دیگه در دسترس نیست")
        return False
    right = int(idx) == q["answer"]
    st_ = u.setdefault("q_stats", {"ok": 0, "all": 0})
    st_["all"] += 1
    st_["ok"] += int(right)
    p.api("answerCallbackQuery", callback_query_id=cq["id"], text="درست بود 🎉" if right else "نادرست ❌")
    ans = f"{LETTERS[q['answer']]}) {q['options'][q['answer']]}"
    head = "🎉 <b>آفرین! درست جواب دادی.</b>" if right else f"❌ <b>جوابت درست نبود.</b>\nپاسخ درست: {ans}"
    expl = f"\n💡 {q['explain']}" if q.get("explain") else ""
    score = f"\n\n📊 تا حالا {_fa(st_['ok'])} از {_fa(st_['all'])} تست رو درست زدی."
    kb = {"inline_keyboard": [[{"text": "➡️ تست بعدی", "callback_data": "qn"}],
                              [{"text": "📲 هزاران تست دیگه در اپ آزمون یار", "url": APP_URL}]]}
    p.api("editMessageText", chat_id=chat_id, message_id=mid,
          **_payload(p, f"❓ {q['q']}\n\n{head}{expl}{score}", reply_markup=kb))
    return True


def _daily_tests(st):
    """هر روز از ساعت ۱۷ یک «تست روز» برای هر کاربر (اگر خاموشش نکرده باشد)."""
    if not (DAILY_TEST_HOUR <= iran_now().hour < REMIND_HOURS[1]) or not _bank():
        return False
    day, sends, changed = iran_now().strftime("%Y-%m-%d"), 0, False
    for key, u in st["users"].items():
        if sends >= 150:
            break
        if u.get("blocked") or not u.get("daily_on") or u.get("last_daily") == day:
            continue
        if u.get("joined", 0) > time.time() - 3600:
            continue
        pname, uid = key.split(":", 1)
        p = PLATFORMS.get(pname)
        if not p:
            continue
        u["last_daily"] = day
        q = _pick_question(u)
        res = _question_msg(p, int(uid), q, "☀️ <b>تست روز")
        if not res.get("ok") and "block" in str(res.get("description", "")).lower():
            u["blocked"] = True
        sends += 1
        changed = True
        time.sleep(0.05)
    return changed


# ---------- دعوت دوستان ----------
def _send_invite(p, chat_id, key, u):
    if p.name != "tg":
        _send(p, chat_id, "دعوت دوستان فعلاً فقط در ربات تلگرام فعاله.", main_kb(p))
        return
    link = f"https://t.me/{BOT_USERNAME}?start=r_{key.split(':', 1)[1]}"
    n = u.get("refs", 0)
    status = ("✅ جایزه‌ات رو گرفتی، ممنون که دوستات رو آوردی! 🌸" if u.get("rewarded")
              else f"📊 تا حالا {_fa(n)} نفر از {_fa(REF_GOAL)} نفر.")
    _send(p, chat_id, f"👥 <b>دوستات رو دعوت کن، جایزه بگیر!</b>\n\n"
                      f"🎁 اگه {_fa(REF_GOAL)} نفر با لینک تو ربات رو استارت کنن، جایزه‌ات: <b>{REF_PRIZE}</b>\n\n"
                      f"{status}\n\n👇 لینک دعوت تو (برای دوستات بفرست):\n{link}", main_kb(p))
    share = ("من از این ربات مهلت ثبت‌نام آزمون‌های استخدامی رو می‌گیرم و تست رایگان می‌زنم. "
             f"تو هم استارتش کن 👇\n{link}")
    _send(p, chat_id, share)


def _referral(p, st, key, u, ref_id):
    ref_key = f"{p.name}:{re.sub(r'[^0-9]', '', ref_id)}"
    r = st["users"].get(ref_key)
    if not r or ref_key == key:
        return
    u["ref_by"] = ref_key
    r["refs"] = r.get("refs", 0) + 1
    rid = int(ref_key.split(":", 1)[1])
    if r["refs"] < REF_GOAL or r.get("rewarded"):
        if not r.get("rewarded"):
            _send(p, rid, f"🎉 یکی از دوستات با لینک تو اومد! ({_fa(r['refs'])} از {_fa(REF_GOAL)})")
        return
    r["rewarded"] = True
    if REF_REWARD:
        _send(p, rid, f"🏆 <b>تبریک! {_fa(REF_GOAL)} نفر رو دعوت کردی.</b>\n\n🎁 جایزه‌ات:\n{_esc(REF_REWARD)}")
    else:
        _send(p, rid, f"🏆 <b>تبریک! {_fa(REF_GOAL)} نفر رو دعوت کردی.</b>\n\n"
                      f"🎁 جایزه‌ات ({REF_PRIZE}) به‌زودی از طرف پشتیبانی «آزمون یار» برات فرستاده میشه.")
    who = f"{r.get('name', '')} " + (f"@{r['uname']}" if r.get("uname") else f"(شناسه {ref_key})")
    for a in ADMINS:
        ap = PLATFORMS.get(a.split(":", 1)[0])
        if ap:
            _send(ap, int(a.split(":", 1)[1]), f"🎁 برنده‌ی دعوت دوستان: {_esc(who)}"
                  + ("" if REF_REWARD else "\nجایزه رو دستی براش بفرست."))


# ---------- ادمین: آمار و پیام گروهی ----------
ADMIN_HELP = ("🛠 <b>دستورهای ادمین</b>\n"
              "/stats — آمار کاربرهای ربات\n"
              "/send — پیام گروهی به همه یا یک دسته\n"
              "/myid — شناسه‌ی خودت")


def stats_text(st):
    users = list(st["users"].values())
    week = time.time() - 7 * 86400
    topics = {}
    for u in users:
        for t in u.get("topics") or []:
            topics[t] = topics.get(t, 0) + 1
    srcs = {}
    for u in users:
        s_ = u.get("src") or "مستقیم"
        s_ = "دعوت دوستان" if s_.startswith("r_") else {"ch": "دکمه‌ی کانال"}.get(s_, s_)
        srcs[s_] = srcs.get(s_, 0) + 1
    plat = {}
    for k in st["users"]:
        n = "تلگرام" if k.startswith("tg:") else "بله"
        plat[n] = plat.get(n, 0) + 1
    lines = [
        "📊 <b>آمار ربات دستیار</b>\n",
        f"👥 کل کاربرها: <b>{_fa(len(users))}</b> ({'، '.join(f'{k}: {_fa(v)}' for k, v in plat.items()) or '—'})",
        f"🆕 عضو ۷ روز اخیر: {_fa(sum(1 for u in users if u.get('joined', 0) >= week))}",
        f"💬 فعال ۷ روز اخیر: {_fa(sum(1 for u in users if u.get('seen', 0) >= week))}",
        f"🚫 ربات رو بلاک کردن: {_fa(sum(1 for u in users if u.get('blocked')))}",
        f"🧠 تست‌های زده‌شده: {_fa(sum(u.get('q_stats', {}).get('all', 0) for u in users))}",
        f"👥 دعوت موفق: {_fa(sum(u.get('refs', 0) for u in users))}",
        "\n<b>علاقه‌ها:</b>",
    ]
    for t, n in sorted(topics.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {TOPIC_NAMES.get(t, 'همه‌ی آزمون‌ها')}: {_fa(n)}")
    lines.append("\n<b>از کجا اومدن:</b>")
    for t, n in sorted(srcs.items(), key=lambda kv: -kv[1]):
        lines.append(f"• {_esc(t)}: {_fa(n)}")
    return "\n".join(lines)


def _bcast_targets(st, topic):
    out = []
    for k, u in st["users"].items():
        if u.get("blocked"):
            continue
        if topic == "all" or topic in (u.get("topics") or []) or "all" in (u.get("topics") or []):
            out.append(k)
    return out


def _admin_message(p, st, key, chat_id, text):
    pend = st.setdefault("bcast", {})
    if text in ("/admin", "/help"):
        _send(p, chat_id, ADMIN_HELP, main_kb(p))
        return True
    if text == "/stats":
        _send(p, chat_id, stats_text(st), main_kb(p))
        return True
    if text == "/send":
        rows = [[{"text": f"همه ({_fa(len(_bcast_targets(st, 'all')))} نفر)", "callback_data": "b|all"}]]
        rows += [[{"text": f"{name} ({_fa(len(_bcast_targets(st, tag)))} نفر)", "callback_data": f"b|{tag}"}]
                 for tag, name in TOPICS]
        rows.append([{"text": "❌ لغو", "callback_data": "b|cancel"}])
        _send(p, chat_id, "📣 پیام گروهی برای کیا بفرستم؟", {"inline_keyboard": rows})
        return True
    if pend.get(key, {}).get("step") == "text" and text and not text.startswith("/"):
        pend[key].update(step="confirm", text=text)
        n = len(_bcast_targets(st, pend[key]["topic"]))
        _send(p, chat_id, f"👇 پیش‌نمایش (برای {_fa(n)} نفر):\n\n{_esc(text)}",
              {"inline_keyboard": [[{"text": "✅ ارسال", "callback_data": "b|go"},
                                    {"text": "❌ لغو", "callback_data": "b|cancel"}]]})
        return True
    return False


def _on_broadcast_cb(p, cq, st, key, data):
    pend = st.setdefault("bcast", {})
    m = cq.get("message", {})
    chat_id, mid = m.get("chat", {}).get("id"), m.get("message_id")
    arg = data[2:]
    p.api("answerCallbackQuery", callback_query_id=cq["id"])
    if arg == "cancel":
        pend.pop(key, None)
        p.api("editMessageText", chat_id=chat_id, message_id=mid, **_payload(p, "لغو شد."))
        return True
    if arg == "go":
        job = pend.pop(key, None)
        if not job or not job.get("text"):
            return True
        targets = _bcast_targets(st, job["topic"])
        p.api("editMessageText", chat_id=chat_id, message_id=mid,
              **_payload(p, f"⏳ در حال ارسال برای {_fa(len(targets))} نفر..."))
        ok = 0
        for k in targets:
            tp = PLATFORMS.get(k.split(":", 1)[0])
            if not tp:
                continue
            res = _send(tp, int(k.split(":", 1)[1]), _esc(job["text"]))
            if res.get("ok"):
                ok += 1
            elif "block" in str(res.get("description", "")).lower():
                st["users"][k]["blocked"] = True
            time.sleep(0.05)
        _send(p, chat_id, f"✅ پیام برای {_fa(ok)} نفر از {_fa(len(targets))} نفر فرستاده شد.", main_kb(p))
        return True
    if arg == "all" or arg in TOPIC_NAMES:
        pend[key] = {"step": "text", "topic": arg}
        name = "همه" if arg == "all" else TOPIC_NAMES[arg]
        p.api("editMessageText", chat_id=chat_id, message_id=mid,
              **_payload(p, f"📣 گیرنده‌ها: <b>{name}</b>\nحالا متن پیامت رو بفرست."))
        return True
    return False


# ---------- پیام‌های خودکار ----------
def _exam_key(title, deadline):
    return hashlib.sha1(f"{title}|{deadline}".encode()).hexdigest()[:10]


def tick(st):
    """آزمون تازه + یادآوری مهلت به کاربرهای علاقه‌مند. True اگر وضعیت تغییر کرد."""
    if DISABLED or not st["users"]:
        return False
    with _lock:
        daily = _daily_tests(st)
    return _deadline_tick(st) or daily


def _deadline_tick(st):
    hour = iran_now().hour
    if not (REMIND_HOURS[0] <= hour < REMIND_HOURS[1]):
        return False
    with _lock:
        rows = open_exams()
        known = set(st["known"])
        first_run = not known
        sends, changed = 0, False
        for title, deadline, left, info in rows:
            ek = _exam_key(title, deadline)
            is_new = ek not in known
            if is_new:
                st["known"].append(ek)
                changed = True
            if first_run:
                continue  # بار اول فقط فهرست فعلی ثبت می‌شود
            for key, u in st["users"].items():
                if sends >= SENDS_PER_TICK:
                    break
                if u.get("blocked") or not u.get("topics") or not _match(u, title):
                    continue
                rem = u.setdefault("reminded", {})
                if is_new and u.get("joined", 0) < time.time() - 60:
                    kind = "new"
                elif left in REMIND_LEFT:
                    kind = f"d{left}"
                else:
                    continue
                if kind in rem.get(ek, []):
                    continue
                head = ("🆕 <b>ثبت‌نام تازه در رشته‌ی مورد علاقه‌ی تو</b>" if kind == "new"
                        else "⏰ <b>" + {0: "امروز آخرین روز ثبت‌نامه!", 1: "فردا آخرین روز ثبت‌نامه!"}
                        .get(left, f"فقط {_fa(left)} روز تا پایان ثبت‌نام مونده") + "</b>")
                pname, uid = key.split(":", 1)
                p = PLATFORMS.get(pname)
                if not p:
                    continue
                res = _send(p, int(uid), f"{head}\n\n{exam_line(title, deadline, left, info)}\n\n{app_line()}")
                rem.setdefault(ek, []).append(kind)
                if kind == "new" and left in REMIND_LEFT:
                    rem[ek].append(f"d{left}")  # همان روز یادآوری تکراری نفرستد
                if not res.get("ok") and "block" in str(res.get("description", "")).lower():
                    u["blocked"] = True
                sends += 1
                changed = True
                time.sleep(0.05)
        st["known"] = st["known"][-300:]
        live = {_exam_key(t, d) for t, d, _, _ in rows}
        for u in st["users"].values():
            for k in [k for k in u.get("reminded", {}) if k not in live]:
                u["reminded"].pop(k)
        return changed


def stats(st):
    users = list(st["users"].values())
    return {"users": len(st["users"]),
            "with_topics": sum(1 for u in users if u.get("topics")),
            "blocked": sum(1 for u in users if u.get("blocked"))}
