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


def clean(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


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
                "title": clean(e.get("title")),
                "summary": clean(e.get("summary", ""))[:2500],
                "link": e.get("link", ""),
                "source": src["name"],
                "ts": time.mktime(e.published_parsed) if e.get("published_parsed") else 0,
            })
        print(f"[+] {src['name']}: {len(feed.entries)} items")
    items.sort(key=lambda x: x["ts"])  # قدیمی‌تر اول، تا ترتیب انتشار درست باشد
    return items


def ai_summarize(item):
    if not GITHUB_TOKEN:
        return {"relevant": True, "post": f"🔸 <b>{item['title']}</b>"}
    prompt = PROMPT.replace("{title}", item["title"]).replace("{summary}", item["summary"])
    r = requests.post(
        "https://models.github.ai/inference/chat/completions",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        json={"model": MODEL, "temperature": 0.2,
              "messages": [{"role": "user", "content": prompt}]},
        timeout=60,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"]
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0))


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
        try:
            res = ai_summarize(item)
        except Exception as e:
            print(f"[!] AI failed for {item['title']}: {e}")
            continue  # دفعه‌ی بعد دوباره امتحان می‌شود
        seen["ids"].append(item["id"])
        seen["titles"].append(norm_title(item["title"]))
        if not res.get("relevant"):
            print(f"[-] skip: {item['title']}")
            continue
        text = (safe_html(res["post"]).strip()
                + f"\n\n🔗 <a href=\"{html.escape(item['link'])}\">مشاهده‌ی متن کامل</a> | {html.escape(item['source'])}"
                + f"\n\n📚 برای آمادگی آزمون‌های استخدامی: <b>آزمون یار</b>"
                + f"\n🆔 {CHANNEL}")
        try:
            send(text)
            posted += 1
            print(f"[✓] posted: {item['title']}")
            time.sleep(3)
        except Exception as e:
            print(f"[!] {e}")

    # فقط ۲۰۰۰ مورد آخر نگه داشته شود
    seen["ids"] = seen["ids"][-2000:]
    seen["titles"] = seen["titles"][-2000:]
    SEEN_FILE.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    print(f"done, posted {posted}")


if __name__ == "__main__":
    sys.exit(main())
