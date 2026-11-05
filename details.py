"""خواندن صفحه‌ی کامل خبر و درآوردن مهلت، تاریخ آزمون و لینک رسمی ثبت‌نام."""
import html
import re
from urllib.parse import urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
NOT_OFFICIAL = ["iranestekhdam", "e-estekhdam", "estekhdam", "t.me", "telegram", "instagram",
                "eitaa", "bale.ai", "rubika", "aparat", "youtube", "google", "cafebazaar", "myket"]
STATUSES = ["در حال ثبت نام", "در حال ثبت‌نام", "تمدید ثبت نام", "تمدید ثبت‌نام", "پایان ثبت نام",
            "پایان ثبت‌نام", "اعلام نتایج", "توزیع کارت", "برگزاری آزمون", "مصاحبه", "به زودی"]


def _text(h):
    h = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h)))


def _val(text, label, nxt):
    m = re.search(rf"{label}\s*:\s*(.{{1,40}}?)\s*(?:{nxt})", text)
    if not m:
        return None
    v = m.group(1).strip(" -")
    return v.replace("الی", "تا") if v else None


def fetch_details(url):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
    except Exception as e:
        print(f"[!] details: {e}")
        return {}
    page = r.text
    text = _text(page)
    d = {}
    d["deadline"] = _val(text, "مهلت ثبت ?‌?نام", "ارائه کارت|برگزاری|آخرین وضعیت")
    d["card"] = _val(text, "ارائه کارت آزمون", "برگزاری|آخرین وضعیت")
    d["exam"] = _val(text, "برگزاری آزمون", "آخرین وضعیت|دفترچه")
    m = re.search(r"آخرین وضعیت\s*:\s*(" + "|".join(STATUSES) + ")", text)
    d["status"] = m.group(1) if m else None
    if not d["deadline"]:
        m = re.search(r"می[‌ ]?توانند[^.]{0,60}?(تا (?:ساعت \S+ )?(?:روز \S+ )?[\d۰-۹]{1,2} \S+(?: ماه)? [\d۰-۹]{4})", text)
        if m:
            d["deadline"] = m.group(1)
    # جمله‌ی اصلی خبر، مثل «ثبت نام ... شروع شد؛ علاقمندان ... تا ... اقدام نمایند»
    start = text.find("آخرین وضعیت")
    m = re.search(r"([^.!؟:]{10,220}?(?:شروع شد|آغاز شد|تمدید شد|آغاز گردید|تمدید گردید)\s*(?:[؛،]| و )[^.!؟]{10,260}?(?:نمایند|کنند|نماید|باشند))",
                  text[max(start, 0):])
    if m:
        lead = m.group(1).strip()
        # از آخرین «ثبت نام» قبل از فعل شروع کن تا تیترهای اضافه حذف شوند
        verb = re.search(r"شروع شد|آغاز شد|تمدید شد|آغاز گردید|تمدید گردید", lead).start()
        starts = [x.start() for x in re.finditer(r"ثبت ?‌?نام", lead[:verb])]
        if starts:
            lead = lead[starts[-1]:]
        junk = "|".join(map(re.escape, STATUSES + ["دفترچه", "(جدید)", "جدید", "-"]))
        for _ in range(5):
            lead = re.sub(rf"^(?:{junk})\s*", "", lead)
        d["lead"] = lead
    m = re.search(r'<meta[^>]+(?:name|property)="(?:og:)?description"[^>]+content="([^"]+)"', page)
    if m:
        d["desc"] = html.unescape(m.group(1)).strip()
    # لینک رسمی ثبت‌نام: لینکی بیرون از سایت خبری که متنش «ثبت نام» است
    for href, label in re.findall(r'<a[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', page, re.S):
        label = _text(label).strip()
        host = urlparse(href).netloc.lower()
        if re.search(r"ثبت ?‌?نام", label) and not any(b in host for b in NOT_OFFICIAL):
            d["reg_url"] = href
            break
    return {k: v for k, v in d.items() if v}


def details_lines(d):
    lines = []
    if d.get("status"):
        lines.append(f"📌 وضعیت: {d['status']}")
    if d.get("deadline"):
        lines.append(f"📅 مهلت ثبت‌نام: {d['deadline']}")
    if d.get("card"):
        lines.append(f"🪪 دریافت کارت آزمون: {d['card']}")
    if d.get("exam"):
        lines.append(f"✏️ تاریخ آزمون: {d['exam']}")
    if d.get("reg_url"):
        lines.append("🖊 نحوه‌ی ثبت‌نام: فقط اینترنتی، از سامانه‌ی رسمی زیر")
    return lines


# ---------- تاریخ شمسی ----------
MONTHS = {"فروردین": 1, "اردیبهشت": 2, "خرداد": 3, "تیر": 4, "مرداد": 5, "شهریور": 6,
          "مهر": 7, "آبان": 8, "آذر": 9, "دی": 10, "بهمن": 11, "اسفند": 12}


def _to_latin(t):
    return t.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))


def today_jalali():
    import datetime
    g = datetime.datetime.utcnow() + datetime.timedelta(hours=3, minutes=30)
    gy, gm, gd = g.year, g.month, g.day
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    gy2 = gy + 1 if gm > 2 else gy
    days = 355666 + (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) + gd + g_d_m[gm - 1]
    jy = -1595 + (33 * (days // 12053))
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + days // 31 if days < 186 else 7 + (days - 186) // 30
    jd = 1 + (days % 31 if days < 186 else (days - 186) % 30)
    return (jy, jm, jd)


def deadline_end(deadline):
    """آخرین تاریخ مهلت را به (سال، ماه، روز) تبدیل کن؛ اگر نشد None."""
    t = _to_latin(deadline)
    dates = re.findall(r"(\d{4})/(\d{1,2})/(\d{1,2})", t)
    if dates:
        y, m, d = dates[-1]
        return (int(y), int(m), int(d))
    m = re.search(r"(\d{1,2})\s+(" + "|".join(MONTHS) + r")(?:\s*ماه)?\s+(\d{4})", t)
    if m:
        return (int(m.group(3)), MONTHS[m.group(2)], int(m.group(1)))
    return None


def is_expired(deadline):
    end = deadline_end(deadline or "")
    return bool(end) and end < today_jalali()
