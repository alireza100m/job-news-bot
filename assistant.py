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
MAIN_KB = {"keyboard": [[{"text": BTN_OPEN}], [{"text": BTN_TOPICS}, {"text": BTN_APP}]],
           "resize_keyboard": True}

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
            "• به سؤال‌هات درباره‌ی آزمون‌ها جواب بدم\n\n" + TOPICS_Q)


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
    _send(p, chat_id, txt + "\n\n" + app_line(), MAIN_KB)


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
    if text.startswith("/start"):
        arg = text[6:].strip()
        if arg and not u.get("src"):
            u["src"] = re.sub(r"[^\w-]", "", arg)[:30]  # منبع ورود (برای آمار)
        _send(p, chat_id, _welcome(u["name"]), _topics_kb(u))
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
              MAIN_KB)
        return True
    if not text:
        _send(p, chat_id, "فعلاً فقط پیام متنی رو می‌فهمم 🙂 سؤالت رو بنویس.", MAIN_KB)
        return True
    _answer(p, chat_id, u, text)
    return True


def _on_callback(p, cq, st):
    data = cq.get("data", "")
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
                _send(p, chat_id, _esc(reply), MAIN_KB)
                return
        except Exception as e:
            print(f"[assistant] gemini failed: {e}"[:300])
    faq = _faq(text)
    greeting = re.match(r"(سلام|درود|خوبی|ممنون|مرسی|تشکر)", text)
    hits = [] if greeting else _search(text)
    if faq and not hits:
        _send(p, chat_id, faq, MAIN_KB)
        return
    if hits:
        _send(p, chat_id, "این‌ها رو پیدا کردم:\n\n" + "\n\n".join(exam_line(*r) for r in hits[:6])
              + "\n\n" + app_line(), MAIN_KB)
    else:
        _send(p, chat_id, "سؤالت رو گرفتم 🙏 فعلاً جواب دقیقی براش ندارم.\n"
                          f"آخرین اخبار استخدامی رو توی کانال {CHANNEL} ببین، "
                          f"یا «{BTN_OPEN}» رو بزن.", MAIN_KB)


# ---------- پیام‌های خودکار ----------
def _exam_key(title, deadline):
    return hashlib.sha1(f"{title}|{deadline}".encode()).hexdigest()[:10]


def tick(st):
    """آزمون تازه + یادآوری مهلت به کاربرهای علاقه‌مند. True اگر وضعیت تغییر کرد."""
    if DISABLED or not st["users"]:
        return False
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
    users = st["users"].values()
    return {"users": len(st["users"]),
            "with_topics": sum(1 for u in users if u.get("topics")),
            "blocked": sum(1 for u in users if u.get("blocked"))}
