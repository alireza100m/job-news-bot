"""ربات خودکار اخبار استخدامی - کانال آزمون یار

هر بار اجرا: خبرها را از منابع (RSS) می‌خواند، تکراری‌ها را حذف می‌کند،
با هوش مصنوعی (GitHub Models) بررسی و خلاصه می‌کند و در کانال تلگرام منتشر می‌کند.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import feedparser
from formatter import format_post, normalize_fa, sentence, strip_heading, _short
from details import fetch_details, details_lines, is_expired
from ee_calendar import fetch_calendar
import requests

BASE = Path(__file__).parent
SEEN_FILE = BASE / "seen.json"
SOURCES_FILE = BASE / "sources.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
# کانال‌های آینه در بله و ایتا (اختیاری؛ اگر خالی باشند ارسال نمی‌شود)
BALE_TOKEN = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHANNEL = os.environ.get("BALE_CHANNEL", "")
EITAA_TOKEN = os.environ.get("EITAA_TOKEN", "")
EITAA_CHANNEL = os.environ.get("EITAA_CHANNEL", "")
MODEL = os.environ.get("AI_MODEL", "openai/gpt-4o-mini")
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))
FIRST_RUN_POSTS = 3
MAX_AGE_DAYS = 3  # خبرهای قدیمی‌تر از ۳ روز منتشر نشوند  # در اولین اجرا فقط چند خبر آخر منتشر شود
DRY_RUN = os.environ.get("DRY_RUN") == "1"
AI_DISABLED = os.environ.get("AI_DISABLED") == "1"

UA = {"User-Agent": "Mozilla/5.0 (compatible; JobNewsBot/1.0)"}

PROMPT = """تو ویراستار یک کانال تلگرامی «اخبار استخدامی» هستی.
خبر زیر را بخوان و فقط JSON برگردان، بدون هیچ متن اضافه:
{"relevant": true/false, "post": "..."}

relevant فقط وقتی true است که خبر درباره‌ی یک فراخوان، آگهی، آزمون، نتایج یا اطلاعیه‌ی استخدامی واقعی باشد
(دولتی، اداری، کارمندی، نظامی، آموزش و پرورش، بانک‌ها، شرکت‌ها و ...). مطالب تبلیغاتی، آموزشی کلی یا بی‌ربط = false.

اگر relevant بود، post را به فارسی روان، کوتاه و مرتب با این قالب بنویس (هر مورد که در خبر نیست را حذف کن، چیزی از خودت نساز):
🔸 <b>عنوان کوتاه و گویا</b>

🏢 ارگان: ...
👥 جنسیت / مقطع / رشته: ...
📍 محل خدمت: ...
📅 مهلت ثبت‌نام: ...
📝 خلاصه: یک یا دو جمله

فقط از تگ <b> استفاده کن. هشتگ و لینک نگذار.

عنوان: {title}
متن: {summary}
"""


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# نام و نشانی سایت‌های منبع نباید در کانال دیده شود
SITE_NAMES = ["ایران استخدام", "ای استخدام", "ای‌استخدام", "iranestekhdam", "e-estekhdam",
              "استخدام دات آی آر", "سایت استخدام"]


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    text = re.sub(r"The post .*? appeared first on .*?\.", " ", text, flags=re.S)
    text = re.sub(r"(https?://|www\.)\S+", " ", text)
    text = re.sub(r"\S+\.(ir|com|org|net)\b\S*", " ", text)
    text = re.sub(r"\[(…|\.\.\.)\]|ادامه مطلب|ادامه‌ی مطلب|ادامه خبر", " ", text)
    for name in SITE_NAMES:
        text = re.sub(re.escape(name), " ", text, flags=re.I)
    text = re.sub(r"\s+([،.:])", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" -–|:،")


def item_id(entry):
    key = entry.get("link") or entry.get("id") or entry.get("title", "")
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def norm_title(t):
    return re.sub(r"[^\w]", "", t)[:60]


def fetch_items(sources):
    items = []
    for src in sources:
        if src.get("type") == "ee_calendar":
            try:
                cal = fetch_calendar(src["url"])
            except Exception as e:
                print(f"[!] {src['name']}: {e}")
                continue
            for it in cal:
                it["source"] = src["name"]
            items.extend(cal)
            print(f"[+] {src['name']}: {len(cal)} open registrations")
            continue
        try:
            r = requests.get(src["url"], headers=UA, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
        except Exception as e:  # یک منبع خراب نباید کل کار را متوقف کند
            print(f"[!] {src['name']}: {e}")
            continue
        for e in feed.entries[:20]:
            items.append({
                "id": item_id(e),
                # گوگل نیوز اسم سایت را با « - » به آخر عنوان می‌چسباند
                "title": clean(re.sub(r"\s+-\s+[^-]+$", "", e.get("title", ""))
                               if src.get("strip_suffix") else e.get("title")),
                "summary": clean(e.get("summary", ""))[:2500],
                "link": e.get("link", ""),
                "source": src["name"],
                "gov": src.get("gov", False),
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        print(f"[+] {src['name']}: {len(feed.entries)} items")
    # یک خبر ممکن است در چند فید باشد؛ یکی شود و اگر در فید دولتی بود، دولتی حساب شود
    merged = {}
    for it in items:
        if it["id"] in merged:
            merged[it["id"]]["gov"] = merged[it["id"]]["gov"] or it["gov"]
        else:
            merged[it["id"]] = it
    items = list(merged.values())
    items.sort(key=lambda x: x["ts"])  # قدیمی‌تر اول، تا ترتیب انتشار درست باشد
    return items


# فقط خبرهای دولتی و نیمه‌دولتی: عنوان باید یکی از این‌ها را داشته باشد
GOV_KEYWORDS = [
    # آزمون‌ها و استخدام دولتی
    "آزمون استخدامی", "آزمون فراگیر", "آزمون استخدام", "استخدام دولتی", "دستگاه‌های اجرایی",
    "دستگاه های اجرایی", "دستگاههای اجرایی", "پیمانی", "قراردادی", "رسمی آزمایشی", "دولتی",
    "سازمان سنجش", "رتبه بندی", "رتبه‌بندی", "ایثارگر", "بنیاد شهید", "شهدا", "جانبازان",
    "تسهیلات استخدامی", "استخدامی دولت", "کارکنان دولت",
    # آموزش، سلامت، قضایی
    "آموزش و پرورش", "آموزش‌وپرورش", "فرهنگیان", "معلم", "حق التدریس", "دانشگاه",
    "وزارت", "بهداشت", "علوم پزشکی", "هلال احمر", "قوه قضاییه", "قوه قضائیه", "دادگستری",
    "دیوان", "ثبت اسناد", "سازمان", "شهرداری", "استانداری", "فرمانداری", "دهیاری",
    # بانک‌ها و شرکت‌های دولتی
    "بانک", "تامین اجتماعی", "تأمین اجتماعی", "بیمه مرکزی", "شرکت ملی", "نفت", "پتروشیمی",
    "گاز", "توزیع برق", "نیروگاه", "آب و فاضلاب", "آبفا", "مخابرات", "اداره پست", "راه آهن",
    "فرودگاه", "گمرک", "امور مالیاتی", "صدا و سیما", "کمیته امداد", "بهزیستی",
    "منطقه آزاد", "محیط زیست", "منابع طبیعی", "هواشناسی",
    # نظامی و انتظامی
    "نظامی", "انتظامی", "فراجا", "ناجا", "پلیس", "سپاه", "ارتش", "بسیج", "وزارت دفاع",
    "مرزبانی", "نیروی هوایی", "نیروی دریایی", "نیروی زمینی", "پدافند", "آجا", "ستاد کل",
]
# نشانه‌های آگهی بخش خصوصی (حتی اگر کلمه‌ی بالا را داشته باشد)
PRIVATE_HINTS = ["یک گروه", "گروه آموزشی", "موسسه", "مؤسسه", "دعوت به همکاری", "آکادمی", "دانلود", "نمونه سوال", "سوالات استخدامی", "منابع آزمون", "کتاب", "یک مجموعه", "یک شرکت", "کلینیک", "فروشگاه", "رستوران", "کافه", "آموزشگاه",
                 "مطب", "داروخانه", "آرایشگاه", "سالن زیبایی", "شرکت خصوصی", "بانک اطلاعات"]


def is_relevant(item):
    t = item["title"]
    if any(k in t for k in PRIVATE_HINTS):
        return False
    # کلمه‌ی کامل: «دانشگاه» بله، «دانشگاهی» نه (اجازه‌ی «ها/های» در آخر)
    return item.get("gov") or any(
        re.search(rf"(?<!\w){re.escape(k)}(?:‌?ها|‌?های)?(?!\w)", t) for k in GOV_KEYWORDS)


# خبرهای اطلاع‌رسانی (نتایج، کارت، تمدید...) بدون مهلت هم منتشر شوند؛ بقیه حتماً مهلت داشته باشند
NEWS_WORDS = ["نتایج", "اطلاعیه", "ابلاغ", "تمدید", "کارت ورود", "زمان برگزاری", "رتبه بندی",
              "رتبه‌بندی", "اعلام", "پذیرفته", "معرفی شدگان", "مصاحبه", "بخشنامه"]


def plain_post(item):
    """قالب مرتب بدون هوش مصنوعی (formatter.py)."""
    return {"relevant": True, "post": format_post(item["title"], item["summary"])}


def ai_summarize(item):
    if not GITHUB_TOKEN or AI_DISABLED:
        return plain_post(item)
    prompt = PROMPT.replace("{title}", item["title"]).replace("{summary}", item["summary"])
    r = requests.post(
        "https://models.github.ai/inference/chat/completions",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        json={"model": MODEL, "temperature": 0.2,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    if r.status_code != 200 or not r.text.strip():
        raise RuntimeError(f"AI HTTP {r.status_code}: {r.text[:300]!r}")
    try:
        text = r.json()["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", text, re.S)
        return json.loads(m.group(0))
    except Exception as e:
        raise RuntimeError(f"{e} | HTTP {r.status_code} {r.headers.get('content-type')} | {r.text[:400]!r}")


def safe_html(post):
    """فقط <b> مجاز است؛ بقیه escape می‌شود تا تلگرام خطا ندهد."""
    post = html.escape(post, quote=False)
    return post.replace("&lt;b&gt;", "<b>").replace("&lt;/b&gt;", "</b>")


def send(text):
    if DRY_RUN:
        print("---- DRY RUN ----\n" + text)
        return
    r = requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
        json={"chat_id": CHANNEL, "text": text, "parse_mode": "HTML",
              "disable_web_page_preview": True},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram error: {r.text}")
    send_mirrors(text)


def plain_text(text):
    """متن بدون تگ HTML برای بله و ایتا."""
    return html.unescape(re.sub(r"</?b>", "", text))


def send_mirrors(text):
    """ارسال همان خبر به بله و ایتا؛ خطای آن‌ها انتشار در تلگرام را متوقف نمی‌کند."""
    plain = plain_text(text)
    if BALE_TOKEN and BALE_CHANNEL:
        try:
            r = requests.post(f"https://tapi.bale.ai/bot{BALE_TOKEN}/sendMessage",
                              json={"chat_id": BALE_CHANNEL, "text": plain}, timeout=30)
            print(f"[bale] {r.status_code} {r.text[:200]}" if not r.ok else "[bale] ok")
        except Exception as e:
            print(f"[bale] failed: {e}"[:300])
    if EITAA_TOKEN and EITAA_CHANNEL:
        try:
            r = requests.post(f"https://eitaayar.ir/api/{EITAA_TOKEN}/sendMessage",
                              data={"chat_id": EITAA_CHANNEL, "text": plain}, timeout=30)
            print(f"[eitaa] {r.status_code} {r.text[:200]}" if not r.ok else "[eitaa] ok")
        except Exception as e:
            print(f"[eitaa] failed: {e}"[:300])


def main():
    sources = load_json(SOURCES_FILE, [])
    seen = load_json(SEEN_FILE, {"ids": [], "titles": []})
    if os.environ.get("IGNORE_SEEN") == "1":  # فقط برای پیش‌نمایش
        seen = {"ids": ["x"], "titles": []}
    first_run = not seen["ids"]

    def is_dup(t, pool):
        # یک خبر از چند سایت با عنوان کمی متفاوت هم تکراری حساب شود
        return any(t == o or SequenceMatcher(None, t, o).ratio() > 0.85 for o in pool)

    new = []
    batch_titles = []
    only = [w for w in os.environ.get("ONLY_TITLES", "").split("|") if w]  # برای انتشار دستی چند خبر خاص
    for i in fetch_items(sources):
        if only and not any(w in i["title"] for w in only):
            continue
        t = norm_title(i["title"])
        if i["id"] in seen["ids"]:
            continue
        if i["ts"] and time.time() - i["ts"] > MAX_AGE_DAYS * 86400:
            continue  # خبر قدیمی؛ احتمالاً مهلتش گذشته
        if is_dup(t, seen["titles"][-500:]) or is_dup(t, batch_titles):
            seen["ids"].append(i["id"])
            continue
        batch_titles.append(t)
        new.append(i)
    print(f"new items: {len(new)}")

    if first_run:
        # همه را دیده‌شده علامت بزن و فقط چند خبر آخر را منتشر کن
        for i in new[:-FIRST_RUN_POSTS]:
            seen["ids"].append(i["id"])
            seen["titles"].append(norm_title(i["title"]))
        new = new[-FIRST_RUN_POSTS:]

    posted = 0
    for item in new:
        if posted >= MAX_POSTS_PER_RUN:
            break  # بقیه برای اجرای بعدی می‌مانند
        if not is_relevant(item):
            seen["ids"].append(item["id"])
            seen["titles"].append(norm_title(item["title"]))
            print(f"[-] not gov/office: {item['title']}")
            continue
        try:
            res = ai_summarize(item)
        except Exception as e:
            print(f"[!] AI failed, using plain format: {e}"[:300])
            res = plain_post(item)
        seen["ids"].append(item["id"])
        seen["titles"].append(norm_title(item["title"]))
        if not res.get("relevant"):
            print(f"[-] skip: {item['title']}")
            continue
        # صفحه‌ی کامل خبر: مهلت، تاریخ آزمون، وضعیت و لینک رسمی ثبت‌نام
        det = fetch_details(item["link"]) if ("iranestekhdam" in item["link"] or "e-estekhdam" in item["link"]) else {}
        det.update(item.get("pre", {}))  # تاریخ‌های تقویم ای‌استخدام دقیق‌ترند
        if det.get("status", "").startswith("پایان") or is_expired(det.get("deadline")):
            print(f"[-] registration closed: {item['title']}")
            continue
        # ترتیب: عنوان ← متن خبر ← مشخصات (عنوان شغلی، وضعیت، مهلت، تاریخ آزمون، نحوه‌ی ثبت‌نام)
        # آگهی استخدام/آزمون بدون مهلت ثبت‌نام به درد مخاطب نمی‌خورد
        if not det.get("deadline") and not any(w in item["title"] for w in NEWS_WORDS):
            print(f"[-] no deadline: {item['title']}")
            continue
        lines = res["post"].strip().split("\n")
        title_line = normalize_fa(lines[0])
        if det.get("lead"):
            intro_text = clean(det["lead"])
        else:
            intro_text = strip_heading(clean(item["summary"]).replace("...", ""), item["title"])
        intro = [f"📝 {sentence(_short(intro_text))}"] if intro_text else []
        info = [normalize_fa(l) for l in lines[1:] if l.strip() and not l.startswith("📝")] \
            + [normalize_fa(l) for l in details_lines(det)]
        body = title_line
        if intro:
            body += "\n\n" + "\n".join(intro)
        if info:
            body += "\n\n" + "\n".join(info)
        text = safe_html(body)
        if det.get("reg_url"):
            text += f'\n\n🔗 <a href="{html.escape(det["reg_url"])}">ورود به سایت رسمی ثبت‌نام</a>'
        text = (text
                + f"\n\n📚 برای آمادگی آزمون‌های استخدامی: <b>آزمون یار</b>"
                + f"\n🆔 {CHANNEL}")
        try:
            send(text)
            posted += 1
            print(f"[✓] posted: {item['title']}")
            time.sleep(3)
        except Exception as e:
            print(f"[!] {e}")
            # ارسال نشد؛ از فهرست دیده‌شده‌ها خارج شود تا دفعه‌ی بعد دوباره امتحان شود
            seen["ids"].remove(item["id"])
            seen["titles"].remove(norm_title(item["title"]))
            if "404" in str(e) or "401" in str(e):
                break  # توکن اشتباه است؛ بقیه را هم امتحان نکن

    # فقط ۲۰۰۰ مورد آخر نگه داشته شود
    seen["ids"] = seen["ids"][-2000:]
    seen["titles"] = seen["titles"][-2000:]
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    print(f"done, posted {posted}")


if __name__ == "__main__":
    sys.exit(main())
