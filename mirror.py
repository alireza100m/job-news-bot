"""بازنشر پست‌های دستیِ کانال تلگرام در بله و ایتا.

ربات تلگرام پست‌هایی را که ادمین‌ها (نه خود ربات) در کانال می‌گذارند از طریق getUpdates
دریافت می‌کند. هر پست یک بار به بله و ایتا فرستاده می‌شود و سپس به تلگرام «تأیید» می‌شود
تا دوباره تحویل داده نشود. پست‌های خودکار ربات را bot.py خودش بازنشر می‌کند.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

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
BASE = Path(__file__).parent
MAP_FILE = BASE / "mirror_map.json"          # پست‌های دستی: شناسه‌ی تلگرام ← شناسه‌ی بله
BOT_MAP_FILE = BASE / "mirror_map_bot.json"  # پست‌های خودکار (bot.py می‌نویسد)
CHECK_EVERY = 300   # هر ۵ دقیقه بررسی پست‌های حذف‌شده
KEEP_SECONDS = 2 * 86400  # فقط پست‌های ۴۸ ساعت اخیر بررسی می‌شوند

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
    return r.json().get("result", {}).get("message_id") if r.ok else None


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
        return None
    if not media and not text:
        print("skip: unsupported post type")
        return None

    bale_id = None
    if BALE_TOKEN and BALE_CHANNEL:
        try:
            if blob:
                bale_id = post_bale(media[1], {"chat_id": BALE_CHANNEL, "caption": text},
                          {media[2]: (blob[0], blob[1])})
            else:
                bale_id = post_bale("sendMessage", {"chat_id": BALE_CHANNEL, "text": text})
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
    return bale_id


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def git(*args):
    return subprocess.run(["git", *args], cwd=BASE, capture_output=True, text=True)


def save_map(data):
    """نقشه‌ی پست‌ها را در مخزن ذخیره می‌کند تا در اجرای بعدی هم بماند."""
    MAP_FILE.write_text(json.dumps(data), encoding="utf-8")
    git("add", MAP_FILE.name)
    if git("diff", "--cached", "--quiet").returncode == 0:
        return
    git("commit", "-q", "-m", "update mirror map")
    for _ in range(3):
        git("pull", "-q", "--rebase")
        if git("push", "-q").returncode == 0:
            return
        time.sleep(5)
    print("[git] push failed")


def tg_exists(msg_id):
    """تلگرام برای حذف پست در کانال رویدادی نمی‌فرستد؛ با یک ویرایش بی‌اثر وجود پست را می‌سنجیم.
    True: هست، False: حذف شده، None: نامعلوم."""
    try:
        r = requests.post(f"{TG}/editMessageReplyMarkup", timeout=30, json={
            "chat_id": "@" + CHANNEL, "message_id": int(msg_id)}).json()
    except Exception:
        return None
    desc = (r.get("description") or "").lower()
    if r.get("ok") or "not modified" in desc:
        return True
    if "not found" in desc:
        return False
    print(f"[check] {msg_id}: {desc[:150]}")
    return None


def check_deleted(data):
    """پست‌هایی که در تلگرام حذف شده‌اند را از بله هم حذف می‌کند (ایتایار حذف ندارد)."""
    git("pull", "-q", "--rebase")
    now = time.time()
    bot = load(BOT_MAP_FILE, {})
    posts = {**{k: v for k, v in bot.items() if k not in data["deleted"]}, **data["posts"]}
    changed = False
    for tg_id, info in posts.items():
        if now - info["date"] > KEEP_SECONDS:
            continue
        if tg_exists(tg_id) is False:
            print(f"post {tg_id} deleted in Telegram")
            if BALE_TOKEN and BALE_CHANNEL and info.get("bale"):
                post_bale("deleteMessage", {"chat_id": BALE_CHANNEL, "message_id": info["bale"]})
            data["posts"].pop(tg_id, None)
            data["deleted"].append(tg_id)
            changed = True
        time.sleep(0.2)
    old = [k for k, v in data["posts"].items() if now - v["date"] > KEEP_SECONDS]
    for k in old:
        data["posts"].pop(k)
    data["deleted"] = [k for k in data["deleted"]
                       if k in bot and now - bot[k]["date"] <= 3 * 86400]
    if changed or old:
        save_map(data)


def main():
    # اجرای پیوسته: با long polling هر پست چند ثانیه بعد بازنشر می‌شود
    deadline = time.time() + 60 * float(os.environ.get("MIRROR_MINUTES", "0"))
    offset = None
    data = load(MAP_FILE, {"posts": {}, "deleted": []})
    next_check = 0
    while True:
        if time.time() >= next_check:
            try:
                check_deleted(data)
            except Exception as e:
                print(f"[check] failed: {e}"[:300])
            next_check = time.time() + CHECK_EVERY
        params = {"timeout": 50 if deadline > time.time() else 0,
                  "allowed_updates": '["channel_post"]'}
        if offset is not None:
            params["offset"] = offset  # تأیید دریافت پست‌های قبلی
        try:
            r = requests.get(f"{TG}/getUpdates", params=params, timeout=70).json()
        except Exception as e:
            print(f"getUpdates failed: {e}"[:300])
            time.sleep(10)
            continue
        if not r.get("ok"):
            print(f"getUpdates error: {r}")
            sys.exit(1)
        for upd in r["result"]:
            offset = upd["update_id"] + 1
            msg = upd.get("channel_post")
            if (msg and msg["chat"].get("username", "").lower() == CHANNEL
                    and msg.get("date", 0) >= SINCE):
                print(f"mirroring post {msg['message_id']}", flush=True)
                try:
                    bale_id = mirror(msg)
                    if bale_id:
                        data["posts"][str(msg["message_id"])] = {"bale": bale_id,
                                                                 "date": msg["date"]}
                        save_map(data)
                except Exception as e:
                    print(f"mirror failed: {e}"[:300])
                time.sleep(1)
        if time.time() >= deadline:
            break
    if offset is not None:  # تأیید نهایی تا دوباره فرستاده نشود
        requests.get(f"{TG}/getUpdates", params={"offset": offset, "limit": 1,
                                                 "timeout": 0}, timeout=30)
    print("done")


if __name__ == "__main__":
    main()
