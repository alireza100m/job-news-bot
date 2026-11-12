"""هشتگ دسته‌بندی پست‌ها و جمع‌بندی هفتگی ثبت‌نام‌های باز."""
import datetime
import re

import followups

# (هشتگ, کلمه‌های عنوان) — ترتیب مهم است؛ حداکثر ۲ دسته برای هر پست
CATEGORIES = [
    ("آزمون_فراگیر", ["آزمون فراگیر", "آزمون‌های فراگیر", "آزمونهای فراگیر", "دستگاه‌های اجرایی", "دستگاه های اجرایی", "دستگاههای اجرایی"]),
    ("آموزش_و_پرورش", ["آموزش و پرورش", "آموزش‌وپرورش", "فرهنگیان", "معلم", "حق التدریس",
                       "حق‌التدریس", "تربیت معلم", "مدارس"]),
    ("بهداشت_و_درمان", ["بهداشت", "علوم پزشکی", "بیمارستان", "هلال احمر", "انتقال خون",
                        "پرستار", "اورژانس", "درمان", "دارو"]),
    ("بانک", ["بانک", "بیمه", "صندوق"]),
    ("نظامی", ["نظامی", "انتظامی", "فراجا", "ناجا", "پلیس", "سپاه", "ارتش", "بسیج", "دفاع",
               "مرزبانی", "نیروی هوایی", "نیروی دریایی", "نیروی زمینی", "پدافند", "آجا",
               "ستاد کل", "امام حسین", "افسری", "درجه‌داری", "درجه داری", "سرباز"]),
    ("قوه_قضاییه", ["قضاییه", "قضائیه", "دادگستری", "ثبت اسناد", "دیوان", "قضاوت", "قضات",
                    "زندان"]),
    ("شرکت_دولتی", ["نفت", "گاز", "پتروشیمی", "برق", "نیروگاه", "آب و فاضلاب", "آبفا",
                    "مخابرات", "اداره پست", "شرکت ملی پست", "راه آهن", "راه‌آهن", "فرودگاه", "شرکت ملی", "صدا و سیما"]),
    ("دانشگاه", ["دانشگاه", "هیئت علمی", "هیات علمی"]),
    ("شهرداری", ["شهرداری", "دهیاری", "استانداری", "فرمانداری"]),
]
KIND_TAGS = {"reminder": "یادآوری_مهلت", "card": "کارت_ورود_به_جلسه", "results": "نتایج_آزمون",
             "soon": "به_زودی", "weekly": "جمع_بندی_هفتگی"}

WEEKLY_DAY = 3        # پنجشنبه (Monday=0)
WEEKLY_HOUR = 10      # از ساعت ۱۰ صبح به بعد
WEEKLY_MAX = 30


def hashtags(title, kind=None):
    tags = []
    for tag, words in CATEGORIES:
        if any(re.search(rf"(?<!\w){re.escape(w)}", title) for w in words):
            tags.append(tag)
        if len(tags) == 2:
            break
    if kind in KIND_TAGS:
        tags.append(KIND_TAGS[kind])
    if not tags or kind in (None, "soon"):
        tags.insert(0, "استخدام_دولتی")
    return " ".join("#" + t for t in tags)


def iran_now():
    return datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)


def weekly_due(last):
    now = iran_now()
    return (now.weekday() == WEEKLY_DAY and now.hour >= WEEKLY_HOUR
            and last != now.strftime("%Y-%m-%d"))


def _end_words(deadline):
    end = followups.deadline_end(deadline or "")
    if not end:
        return None
    return f"{end[2]} {followups.MONTH_NAMES[end[1] - 1]}".translate(followups.FA_DIGITS)


def open_registrations(tracked, calendar):
    """ثبت‌نام‌های باز: آزمون‌های پیگیری‌شده + ردیف‌های باز تقویم سراسری، بدون تکرار."""
    rows = []
    cands = [(v["title"], v.get("deadline"), v.get("status")) for v in tracked.values()]
    cands += [(c["title"], c.get("pre", {}).get("deadline"), c.get("raw_status"))
              for c in calendar if c.get("phase") == "open"]
    for title, deadline, status in cands:
        if not deadline or followups.stage_of(status):
            continue
        if re.search(r"پایان|به ?‌?زودی", status or ""):
            continue
        left = followups.days_left(deadline)
        if left is None or left < 0:
            continue
        if any(followups.same_exam(title, r[0]) or title == r[0] for r in rows):
            continue
        rows.append((title, deadline, left))
    rows.sort(key=lambda r: r[2])
    return rows[:WEEKLY_MAX]


def weekly_post(rows):
    """متن جمع‌بندی (HTML تلگرام، بدون فوتر)."""
    lines = []
    for title, deadline, left in rows:
        end = _end_words(deadline)
        if left == 0:
            rest = "امروز آخرین مهلت"
        elif left == 1:
            rest = "فردا آخرین مهلت"
        else:
            rest = f"{str(left).translate(followups.FA_DIGITS)} روز مانده"
        lines.append(f"🔹 {followups.subject(title)}\n     📅 تا {end} ({rest})" if end
                     else f"🔹 {followups.subject(title)} ({rest})")
    n = str(len(rows)).translate(followups.FA_DIGITS)
    head = "🗓 <b>جمع‌بندی هفتگی: ثبت‌نام‌های باز استخدامی</b>"
    intro = (f"📝 فهرست {n} آزمون و استخدام دولتی که ثبت‌نامشان هنوز باز است، به ترتیب نزدیک‌ترین مهلت. "
             "برای جزئیات و لینک ثبت‌نام هر مورد، پست آن را در کانال جست‌وجو کنید.")
    return head, intro, lines
