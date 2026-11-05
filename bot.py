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
from pathlib import Path

import feedparser
import requests

BASE = Path(__file__).parent
SEEN_FILE = BASE / "seen.json"
SOURCES_FILE = BASE / "sources.json"

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODEL = os.environ.get("AI_MODEL", "openai/gpt-4o-mini")
MAX_POSTS_PER_RUN = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))
FIRST_RUN_POSTS = 3  # در اولین اجرا فقط چند خبر آخر منتشر شود
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
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        print(f"[+] {src['name']}: {len(feed.entries)} items")
    items.sort(key=lambda x: x["ts"])  # قدیمی‌تر اول، تا ترتیب انتشار درست باشد
    return items


# فقط خبرهای دولتی / اداری / کارمندی (هر کلمه‌ای که در عنوان باشد کافی است)
KEYWORDS = [
    "آزمون", "استخدامی", "دولتی", "وزارت", "سازمان", "اداره", "شهرداری", "بانک",
    "آموزش و پرورش", "دانشگاه", "نیروی انتظامی", "فراجا", "سپاه", "ارتش", "نظامی",
    "کارمند", "اداری", "منشی", "فراخوان", "پیمانی", "قراردادی", "شرکت ملی",
    "بیمارستان", "علوم پزشکی", "دادگستری", "قوه قضاییه", "تامین اجتماعی", "تأمین اجتماعی",
    "نفت", "گاز", "برق", "مخابرات", "پست", "گمرک", "مالیات", "ثبت نام", "ثبت‌نام", "نتایج",
]


def is_relevant(item):
    return any(k in item["title"] for k in KEYWORDS)


def plain_post(item):
    """قالب ساده وقتی هوش مصنوعی در دسترس نیست."""
    text = item["summary"]
    if len(text) > 450:
        text = text[:450].rsplit(" ", 1)[0] + " …"
    post = f"🔸 <b>{item['title']}</b>"
    if text and text != item["title"]:
        post += f"\n\n📝 {text}"
    return {"relevant": True, "post": post}


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


def main():
    sources = load_json(SOURCES_FILE, [])
    seen = load_json(SEEN_FILE, {"ids": [], "titles": []})
    first_run = not seen["ids"]

    new = [i for i in fetch_items(sources)
           if i["id"] not in seen["ids"] and norm_title(i["title"]) not in seen["titles"]]
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
        text = (safe_html(res["post"]).strip()
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
