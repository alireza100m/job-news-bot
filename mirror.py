"""بازنشر پست‌های دستیِ کانال تلگرام در بله و ایتا.

ربات تلگرام پست‌هایی را که ادمین‌ها (نه خود ربات) در کانال می‌گذارند از طریق getUpdates
دریافت می‌کند. هر پست یک بار به بله و ایتا فرستاده می‌شود و سپس به تلگرام «تأیید» می‌شود
تا دوباره تحویل داده نشود. پست‌های خودکار ربات را bot.py خودش بازنشر می‌کند.
"""
import os
import sys
import time

import requests

TG = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
CHANNEL = os.environ.get("TELEGRAM_CHANNEL", "@azmoonyar_estekhdam").lstrip("@").lower()
BALE_TOKEN = os.environ.get("BALE_BOT_TOKEN", "")
BALE_CHANNEL = os.environ.get("BALE_CHANNEL", "")
EITAA_TOKEN = os.environ.get("EITAA_TOKEN", "")
EITAA_CHANNEL = os.environ.get("EITAA_CHANNEL", "")
# پست‌های قبل از این زمان (یونیکس) بازنشر نمی‌شوند تا پست‌های قدیمی تکراری نشوند
SINCE = int(os.environ.get("MIRROR_SINCE", "0"))
MAX_FILE = 20 * 1024 * 1024  # سقف دانلود فایل برای ربات تلگرام

MEDIA = [  # (نوع در تلگرام، متد بله، نام فیلد)
    ("photo", "sendPhoto", "photo"),
    ("video", "sendVideo", "video"),
    ("animation", "sendAnimation", "animation"),
    ("document", "sendDocument", "document"),
    ("audio", "sendAudio", "audio"),
    ("voice", "sendVoice", "voice"),
]


def with_links(text, entities):
    """لینک‌های پنهان زیر متن (text_link) را کنار متن می‌نویسد تا در بله و ایتا گم نشوند."""
    if not text or not entities:
        return text or ""
    raw = text.encode("utf-16-le")
    out, pos = [], 0
    for e in sorted(entities, key=lambda e: e["offset"]):
        if e.get("type") != "text_link":
            continue
        end = (e["offset"] + e["length"]) * 2
        if end < pos:
            continue
        out.append(raw[pos:end].decode("utf-16-le"))
        out.append(f" ({e['url']})")
        pos = end
    out.append(raw[pos:].decode("utf-16-le"))
    return "".join(out)


def download(file_id):
    r = requests.get(f"{TG}/getFile", params={"file_id": file_id}, timeout=30).json()
    if not r.get("ok"):
        raise RuntimeError(f"getFile: {r}")
    path = r["result"]["file_path"]
    data = requests.get(f"{TG.replace('/bot', '/file/bot')}/{path}", timeout=120).content
    return path.rsplit("/", 1)[-1], data


def post_bale(method, data, files=None):
    r = requests.post(f"https://tapi.bale.ai/bot{BALE_TOKEN}/{method}",
                      data=data, files=files, timeout=120)
    print(f"[bale] {method} {'ok' if r.ok else r.status_code} {'' if r.ok else r.text[:200]}")


def post_eitaa(method, data, files=None):
    r = requests.post(f"https://eitaayar.ir/api/{EITAA_TOKEN}/{method}",
                      data=data, files=files, timeout=120)
    print(f"[eitaa] {method} {'ok' if r.ok else r.status_code} {'' if r.ok else r.text[:200]}")


def mirror(msg):
    text = with_links(msg.get("text") or msg.get("caption"),
                      msg.get("entities") or msg.get("caption_entities"))
    media = None
    for kind, method, field in MEDIA:
        if kind in msg:
            obj = msg[kind][-1] if kind == "photo" else msg[kind]  # بزرگ‌ترین اندازه‌ی عکس
            media = (kind, method, field, obj)
            break

    blob = None
    if media and media[3].get("file_size", 0) <= MAX_FILE:
        try:
            blob = download(media[3]["file_id"])
        except Exception as e:
            print(f"[telegram] download failed: {e}"[:300])
    if media and not blob and not text:
        print("skip: media could not be downloaded and there is no text")
        return
    if not media and not text:
        print("skip: unsupported post type")
        return

    if BALE_TOKEN and BALE_CHANNEL:
        try:
            if blob:
                post_bale(media[1], {"chat_id": BALE_CHANNEL, "caption": text},
                          {media[2]: (blob[0], blob[1])})
            else:
                post_bale("sendMessage", {"chat_id": BALE_CHANNEL, "text": text})
        except Exception as e:
            print(f"[bale] failed: {e}"[:300])
    if EITAA_TOKEN and EITAA_CHANNEL:
        try:
            if blob:
                post_eitaa("sendFile", {"chat_id": EITAA_CHANNEL, "caption": text},
                           {"file": (blob[0], blob[1])})
            else:
                post_eitaa("sendMessage", {"chat_id": EITAA_CHANNEL, "text": text})
        except Exception as e:
            print(f"[eitaa] failed: {e}"[:300])


def main():
    r = requests.get(f"{TG}/getUpdates", params={
        "timeout": 0, "allowed_updates": '["channel_post"]'}, timeout=60).json()
    if not r.get("ok"):
        print(f"getUpdates error: {r}")
        sys.exit(1)
    last = None
    try:
        for upd in r["result"]:
            msg = upd.get("channel_post")
            if (msg and msg["chat"].get("username", "").lower() == CHANNEL
                    and msg.get("date", 0) >= SINCE):
                print(f"mirroring post {msg['message_id']}")
                mirror(msg)
                time.sleep(1)
            last = upd["update_id"]
    finally:
        if last is not None:  # تأیید دریافت تا همین پست، تا دوباره فرستاده نشود
            requests.get(f"{TG}/getUpdates", params={"offset": last + 1, "limit": 1,
                                                     "timeout": 0}, timeout=30)
    print(f"done, {len(r['result'])} update(s)")


if __name__ == "__main__":
    main()
