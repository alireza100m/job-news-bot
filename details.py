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
    m = re.search(r"([^.!؟:]{10,220}?(?:شروع شد|آغاز شد|تمدید شد|آغاز گردید|تمدید گردید)\s*[؛،][^.!؟]{10,260}?(?:نمایند|کنند|نماید|باشند))",
                  text[max(start, 0):])
    if m:
        lead = m.group(1).strip()
        junk = "|".join(map(re.escape, STATUSES + ["دفترچه", "(جدید)", "جدید", "-"]))
        for _ in range(5):
            lead = re.sub(rf"^(?:{junk})\s*", "", lead)
        d["lead"] = lead
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
