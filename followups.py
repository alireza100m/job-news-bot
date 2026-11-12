"""پیگیری آزمون‌هایی که قبلاً در کانال منتشر شده‌اند:
- یادآوری روزهای آخر مهلت ثبت‌نام («⏰ فقط ۲ روز تا پایان ثبت‌نام ...»)
- خبر انتشار کارت ورود به جلسه و اعلام نتایج همان آزمون

فهرست آزمون‌های منتشرشده در tracked.json نگه داشته می‌شود.
"""
import datetime
import json
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from details import deadline_end, fetch_details, today_jalali

TRACK_FILE = Path(__file__).parent / "tracked.json"
KEEP_DAYS = 150          # آزمون تا این مدت بعد از انتشار پیگیری می‌شود
RECHECK_HOURS = 6        # هر صفحه‌ی خبر حداکثر هر ۶ ساعت یک بار دوباره خوانده می‌شود
RECHECKS_PER_RUN = 6
REMIND_DAYS = 2          # یادآوری از ۲ روز مانده به پایان مهلت
REMIND_HOURS = (8, 21)   # یادآوری فقط در این ساعت‌ها (وقت ایران)

FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MONTH_NAMES = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
               "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
# کلمه‌هایی که در شناختن نام آزمون کمکی نمی‌کنند
STOP = set("""استخدام استخدامی آزمون آزمونهای آزمون‌های جذب فراخوان ثبت نام ثبت‌نام سال در و به از با برای
کارت ورود جلسه نتایج نتیجه اعلام منتشر شد شده توزیع دریافت چاپ اطلاعیه زمان برگزاری جدید کشور
سراسری نیرو نیروی پذیرش تمدید مهلت آغاز شروع ۱۴۰۴ ۱۴۰۵ ۱۴۰۶ 1404 1405 1406 دفترچه مرحله اول دوم""".split())


# ---------- تاریخ ----------
def jalali_to_date(y, m, d):
    """تبدیل تاریخ شمسی به میلادی (datetime.date)."""
    y += 1595
    days = -355668 + (365 * y) + ((y // 33) * 8) + (((y % 33) + 3) // 4) + d
    days += (m - 1) * 31 if m < 7 else ((m - 7) * 30) + 186
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0
    for gm, ml in enumerate([31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31], 1):
        if gd <= ml:
            return datetime.date(gy, gm, gd)
        gd -= ml
    return datetime.date(gy, 12, 31)


def days_left(deadline):
    end = deadline_end(deadline or "")
    if not end:
        return None
    try:
        return (jalali_to_date(*end) - jalali_to_date(*today_jalali())).days
    except ValueError:
        return None


def date_words(deadline):
    end = deadline_end(deadline or "")
    if not end:
        return None
    y, m, d = end
    return f"{d} {MONTH_NAMES[m - 1]} {y}".translate(FA_DIGITS)


def iran_hour():
    return (datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)).hour


# ---------- ذخیره ----------
def load():
    try:
        data = json.loads(TRACK_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    now = time.time()
    return {k: v for k, v in data.items() if now - v.get("posted", now) < KEEP_DAYS * 86400}


def save(data):
    TRACK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=0), encoding="utf-8")


def subject(title):
    t = re.sub(r"\s+", " ", title).strip()
    t = re.sub(r"^(ثبت ?‌?نام|شروع ثبت ?‌?نام|آغاز ثبت ?‌?نام|فراخوان)\s+", "", t)
    if t.startswith("آزمون"):
        return t
    if t.startswith("استخدام "):
        return "آزمون استخدامی " + t[len("استخدام "):]
    return "آزمون " + t


def track(data, item, det):
    """بعد از انتشار هر آگهی/آزمون، آن را برای پیگیری ثبت کن."""
    key = item["link"] or item["id"]
    old = data.get(key, {})
    data[key] = {
        **old,
        "title": old.get("title") or item["title"],
        "link": item["link"],
        "posted": old.get("posted") or time.time(),
        "deadline": det.get("deadline") or old.get("deadline"),
        "card": det.get("card") or old.get("card"),
        "exam": det.get("exam") or old.get("exam"),
        "reg_url": det.get("reg_url") or old.get("reg_url"),
        "status": det.get("status") or old.get("status"),
        "checked": time.time(),
    }
    # اگر آزمون همین حالا در مرحله‌ی کارت/نتایج است، خبر جدا لازم نیست
    st = stage_of(data[key]["status"])
    if st:
        data[key][st + "_done"] = True
        if st == "results":
            data[key]["card_done"] = True


# ---------- شناختن مرحله‌ی آزمون ----------
def stage_of(text):
    text = text or ""
    if "انتظار" in text:  # «در انتظار نتایج/دریافت کارت» یعنی هنوز منتشر نشده
        return None
    if re.search(r"نتایج|نتیجه|پذیرفته ?‌?شدگان|معرفی ?‌?شدگان", text):
        return "results"
    if re.search(r"کارت(?:\s|$)", text):  # نه «کارتن»
        return "card"
    return None


def name_tokens(title):
    words = re.findall(r"[\w‌]+", title.replace("‌", " "))
    return {w for w in words if len(w) > 1 and w not in STOP}


# کلمه‌های عمومی که خودشان آزمونی را مشخص نمی‌کنند («علوم پزشکی یاسوج» ≠ «علوم پزشکی اراک»)
WEAK = set("""دانشگاه علوم پزشکی شرکت شرکت‌های شرکتهای سازمان بانک اداره کل استان وزارت وزارتخانه
نیروی توزیع ایران دولتی دولت کارکنان کارمند کارشناس عنوان شغلی نفر""".split())


def same_exam(a, b):
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    sa, sb = ta - WEAK, tb - WEAK
    if not sa and not sb:
        return ta == tb
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    # همه‌ی کلمه‌های مشخص‌کننده‌ی نام کوتاه‌تر باید در دیگری باشد
    return bool(small) and small <= big

def find_tracked(data, title):
    best, score = None, 0
    for k, v in data.items():
        if same_exam(v["title"], title):
            s = SequenceMatcher(None, v["title"], title).ratio()
            if s > score:
                best, score = k, s
    return best


def mark_done(data, key, stage):
    """این مرحله برای این آزمون (و نسخه‌های تکراری‌اش از منبع دیگر) منتشر شد."""
    title = data[key]["title"]
    for k, v in data.items():
        if k == key or same_exam(v["title"], title):
            v[stage + "_done"] = True
            if stage == "results":
                v["card_done"] = True  # بعد از نتایج، خبر کارت دیگر لازم نیست


# ---------- متن پست‌ها ----------
def _lines(t, extra_intro=None):
    out = []
    if t.get("deadline") and extra_intro == "reminder":
        out.append(f"📅 مهلت ثبت‌نام: {t['deadline']}")
    if t.get("card") and extra_intro != "results":
        out.append(f"🪪 دریافت کارت آزمون: {t['card']}")
    if t.get("exam") and extra_intro != "results":
        out.append(f"✏️ تاریخ آزمون: {t['exam']}")
    return out


def reminder_post(t, left):
    s = subject(t["title"])
    if left <= 0:
        head = f"⏰ <b>امروز آخرین مهلت ثبت‌نام {s}</b>"
        intro = f"امروز آخرین روز ثبت‌نام {s} است؛ اگر هنوز ثبت‌نام نکرده‌اید، همین امروز اقدام کنید."
    elif left == 1:
        head = f"⏰ <b>فقط ۱ روز تا پایان ثبت‌نام {s}</b>"
        intro = f"فردا آخرین مهلت ثبت‌نام {s} است؛ اگر هنوز ثبت‌نام نکرده‌اید، این فرصت را از دست ندهید."
    else:
        n = str(left).translate(FA_DIGITS)
        end = date_words(t.get("deadline"))
        head = f"⏰ <b>فقط {n} روز تا پایان ثبت‌نام {s}</b>"
        intro = (f"مهلت ثبت‌نام {s} " + (f"در تاریخ {end} " if end else "")
                 + "به پایان می‌رسد؛ اگر هنوز ثبت‌نام نکرده‌اید، این فرصت را از دست ندهید.")
    return head, intro, _lines(t, "reminder"), "ورود به سایت رسمی ثبت‌نام"


def stage_post(t, stage):
    s = subject(t["title"])
    if stage == "card":
        head = f"🪪 <b>کارت ورود به جلسه‌ی {s} منتشر شد</b>"
        intro = (f"کارت ورود به جلسه‌ی {s} منتشر شد؛ داوطلبان می‌توانند با مراجعه به سامانه‌ی رسمی، "
                 "کارت خود را دریافت و چاپ کنند و همراه کارت شناسایی در جلسه‌ی آزمون حاضر شوند.")
        label = "دریافت کارت ورود به جلسه"
    else:
        head = f"📊 <b>نتایج {s} اعلام شد</b>"
        intro = (f"نتایج {s} اعلام شد؛ داوطلبان می‌توانند با مراجعه به سامانه‌ی رسمی، "
                 "نتیجه‌ی خود را مشاهده کنند.")
        label = "مشاهده‌ی نتایج در سایت رسمی"
    return head, intro, _lines(t, stage), label


# ---------- اجرای اصلی ----------
def update_from_calendar(data, calendar):
    """تقویم ای‌استخدام وضعیت و تاریخ‌های به‌روز هر آزمون را می‌دهد (تمدید، کارت، نتایج)."""
    by_link = {c["link"]: c for c in calendar}
    for k, v in data.items():
        c = by_link.get(v.get("link"))
        if not c:
            continue
        pre = c.get("pre", {})
        for f in ("deadline", "card", "exam"):
            if pre.get(f):
                v[f] = pre[f]
        v["status"] = c.get("raw_status") or v.get("status")
        v["checked"] = time.time()


def refresh_pages(data):
    """صفحه‌ی خبر آزمون‌های پیگیری‌شده را دوباره بخوان تا وضعیت جدید (کارت/نتایج/تمدید) معلوم شود."""
    now = time.time()
    due = [k for k, v in data.items()
           if not v.get("results_done") and "e-estekhdam" not in v.get("link", "")
           and now - v.get("checked", 0) > RECHECK_HOURS * 3600 and v.get("link")]
    due.sort(key=lambda k: data[k].get("checked", 0))
    for k in due[:RECHECKS_PER_RUN]:
        det = fetch_details(data[k]["link"])
        data[k]["checked"] = now
        for f in ("deadline", "card", "exam", "status", "reg_url"):
            if det.get(f):
                data[k][f] = det[f]


def seed_from_calendar(data, calendar, seen_ids):
    """آزمون‌هایی که قبل از این قابلیت منتشر شده بودند هم پیگیری شوند."""
    for c in calendar:
        if c["id"] in seen_ids and c["link"] not in data and c.get("phase") in ("open", "soon"):
            data[c["link"]] = {"title": c["title"], "link": c["link"],
                               "posted": time.time() - 86400, "checked": time.time(),
                               "status": c.get("raw_status"), **c.get("pre", {})}


def news_followup(data, item):
    """اگر خبر جدید درباره‌ی کارت/نتایج آزمونی است که قبلاً منتشر کرده‌ایم، کلید آن را برگردان."""
    stage = stage_of(item["title"])
    if not stage:
        return None, None
    key = find_tracked(data, item["title"])
    return key, stage


def pending(data):
    """پست‌های پیگیری که باید الان منتشر شوند: [(کلید, نوع, روزهای مانده)]"""
    out = []
    hour_ok = REMIND_HOURS[0] <= iran_hour() < REMIND_HOURS[1]
    for k, v in data.items():
        st = stage_of(v.get("status"))
        if st == "results" and not v.get("results_done"):
            out.append((k, "results", None))
            continue
        if st == "card" and not v.get("card_done"):
            out.append((k, "card", None))
            continue
        if st or not hour_ok or not v.get("deadline"):
            continue
        if re.search(r"پایان|به ?‌?زودی", v.get("status") or ""):
            continue
        left = days_left(v["deadline"])
        if left is None or not 0 <= left <= REMIND_DAYS:
            continue
        if v.get("reminded_for") == v["deadline"]:
            continue  # برای این مهلت قبلاً یادآوری شده (اگر تمدید شود، دوباره یادآوری می‌شود)
        if time.time() - v.get("posted", 0) < 20 * 3600:
            continue  # همین امروز خبرش را گذاشته‌ایم
        out.append((k, "reminder", left))
    return out
