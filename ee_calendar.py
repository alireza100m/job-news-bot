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


def _dates(vals):
    out = {}
    for key, v in (("card", vals[1]), ("exam", vals[2])):
        m = re.fullmatch(r"(\d{4})/(\d{1,2})/(\d{1,2})", v.translate(FA))
        if m:
            out[key] = f"{m.group(1)}/{int(m.group(2)):02d}/{int(m.group(3)):02d}"
    return out


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
        upcoming_status = "به زودی" in status or "به‌زودی" in status or "در انتظار ثبت" in status
        if status != "ثبت نام" and not upcoming_status:
            # برای انتشار فقط ثبت‌نام باز یا به‌زودی؛ بقیه (کارت، نتایج...) فقط برای پیگیری
            items.append({"id": "", "phase": "other", "raw_status": status, "title": name,
                          "link": href, "pre": _dates(vals), "summary": "", "gov": True, "ts": 0})
            continue
        reg = re.fullmatch(r"(\S+)\s*-\s*(\S+)", vals[0])
        one = re.fullmatch(r"از\s*(\S+)", vals[0])
        start = _full_date(reg.group(1)) if reg else (_full_date(one.group(1)) if one else None)
        end = _full_date(reg.group(2)) if reg else None
        today = "{}/{:02d}/{:02d}".format(*today_jalali())
        def _days(d):
            y, mo, dd = map(int, d.split("/"))
            return y * 365 + mo * 30 + dd
        if start and not upcoming_status and _days(start) - _days(today) > 60:
            start = None  # تاریخ شروع دور مال سال قبل است (ثبت‌نامِ از قبل باز)
        phase = "soon" if upcoming_status or (start and start > today) else "open"
        if phase == "open" and not end:
            continue  # ثبت‌نام باز ولی بدون تاریخ پایان
        if phase == "soon":
            pre = {"status": "به‌زودی (هنوز شروع نشده)", "phase": "soon"}
            if start:
                pre["start"] = start
            if end:
                pre["deadline"] = f"{start} تا {end}" if start else f"تا {end}"
        else:
            pre = {"status": "در حال ثبت‌نام",
                   "deadline": f"{start} تا {end}" if start else f"تا {end}"}
        pre.update(_dates(vals))
        title = name if name.startswith(("استخدام", "آزمون", "فراخوان")) else f"استخدام {name}"
        items.append({
            # «به‌زودی» و «ثبت‌نام باز» دو پست جدا هستند
            "id": hashlib.sha1((href + name + ("|soon" if phase == "soon" else "")).encode("utf-8")).hexdigest()[:16],
            "phase": phase, "raw_status": status,
            "title": title, "summary": "", "link": href, "gov": True, "ts": 0, "pre": pre,
        })
    return items
