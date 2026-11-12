"""ابزار دستی: فهرست یا حذف پست‌های کانال تلگرام.

CLEAN_MODE=list  → شناسه و شروع متن پست‌های عمومی کانال (از صفحه‌ی t.me/s) بعد از CLEAN_AFTER
CLEAN_MODE=delete → حذف شناسه‌های CLEAN_TG (جدا با ,) از تلگرام و CLEAN_BALE از بله
"""
import html
import os
import re

import requests

TG = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam")
BALE = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHANNEL = os.environ.get("BALE_CHANNEL", "")
mode = os.environ.get("CLEAN_MODE", "list")

if mode == "list":
    after = int(os.environ.get("CLEAN_AFTER", "0") or 0)
    page = requests.get(f"https://t.me/s/{CHANNEL.lstrip('@')}", timeout=30,
                        headers={"User-Agent": "Mozilla/5.0"}).text
    for block in re.split(r'(?=<div class="tgme_widget_message_wrap)', page):
        m = re.search(r'data-post="[^/]+/(\d+)"', block)
        if not m or int(m.group(1)) <= after:
            continue
        poll = "[POLL] " if "tgme_widget_message_poll" in block else ""
        t = re.search(r'tgme_widget_message_text[^>]*>(.*?)</div>', block, re.S)
        text = html.unescape(re.sub(r"<[^>]+>", " ", t.group(1))) if t else ""
        q = re.search(r'tgme_widget_message_poll_question[^>]*>(.*?)</div>', block, re.S)
        if q:
            text += html.unescape(re.sub(r"<[^>]+>", " ", q.group(1)))
        tm = re.search(r'datetime="([^"]+)"', block)
        print(m.group(1), tm.group(1) if tm else "", poll + re.sub(r"\s+", " ", text)[:90])
else:
    for i in [x for x in os.environ.get("CLEAN_TG", "").split(",") if x.strip()]:
        r = requests.post(f"{TG}/deleteMessage", json={"chat_id": CHANNEL, "message_id": int(i)}, timeout=30)
        print("tg", i, r.text[:120])
    for i in [x for x in os.environ.get("CLEAN_BALE", "").split(",") if x.strip()]:
        r = requests.post(f"https://tapi.bale.ai/bot{BALE}/deleteMessage",
                          json={"chat_id": BALE_CHANNEL, "message_id": int(i)}, timeout=30)
        print("bale", i, r.text[:120])
