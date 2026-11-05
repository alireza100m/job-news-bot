"""تقویم «استخدام‌های سراسری» ای‌استخدام: فهرست آزمون‌های دولتی با وضعیت و تاریخ‌ها."""
import hashlib
import html
import re

import requests

from details import today_jalali

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def _t(x):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", x))).strip()


def _full_date(md):
    """«۸/۱۶» → «۱۴۰۵/۰۸/۱۶» با حدس سال."""
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", md.translate(FA).strip())
    if not m:
        return None
    jy, jm, _ = today_jalali()
    mo, d = int(m.group(1)), int(m.group(2))
    y = jy + 1 if mo < jm - 3 else jy
    return f"{y}/{mo:02d}/{d:02d}"


def fetch_calendar(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    items = []
    for href, body in re.findall(r'<a class="item[^"]*" href="([^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        tm = re.search(r'class="title[^"]*">(.*?)</div>', body, re.S)
        sm = re.search(r'class="subtitle">(.*?)</div>', body, re.S)
        if not tm:
            continue
        name, status = _t(tm.group(1)), (_t(sm.group(1)) if sm else "")
        vals = [_t(v) for v in re.findall(r'class="v">(.*?)</div>', body, re.S)] + ["-"] * 4
        if status != "ثبت نام":
            continue  # فقط آزمون‌هایی که الان ثبت‌نامشان باز است
        reg = re.fullmatch(r"(\S+)\s*-\s*(\S+)", vals[0])
        if not reg:
            continue  # بدون تاریخ پایان ثبت‌نام
        start, end = _full_date(reg.group(1)), _full_date(reg.group(2))
        if not end:
            continue
        pre = {"status": "در حال ثبت‌نام",
               "deadline": f"{start} تا {end}" if start else f"تا {end}"}
        if vals[1] not in ("-", ""):
            pre["card"] = vals[1]
        if vals[2] not in ("-", ""):
            pre["exam"] = vals[2]
        title = name if name.startswith(("استخدام", "آزمون", "فراخوان")) else f"استخدام {name}"
        items.append({
            "id": hashlib.sha1((href + name).encode("utf-8")).hexdigest()[:16],
            "title": title, "summary": "", "link": href, "gov": True, "ts": 0, "pre": pre,
        })
    return items
