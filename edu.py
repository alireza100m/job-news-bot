"""محتوای آموزشی روزانه از بانک edu.json (بدون هوش مصنوعی، محتوای بازبینی‌شده):

  tip      نکته‌ی روز درسی (ادبیات، معارف، قانون اساسی، کامپیوتر، ریاضی، هوش، زبان)
  mistake  «اینو اکثراً غلط می‌زنن!»: سؤال دام‌دار با پاسخ پنهان و توضیح
  skill    مهارت تست‌زنی (مدیریت زمان، نمره‌ی منفی، ...)
  exam     سؤال به سبک آزمون‌های استخدامی با پاسخ تشریحی

هر نوع روزی یک بار در ساعت خودش (وقت ایران) منتشر می‌شود؛ موارد منتشرشده در
edu_state.json ثبت می‌شوند تا تا تمام شدن بانک تکرار نشوند.
"""
import html
import json
import random
from pathlib import Path

import extras
import quiz

BASE = Path(__file__).parent
BANK = BASE / "edu.json"
STATE = BASE / "edu_state.json"
# ساعت انتشار هر نوع (وقت ایران)؛ اگر اجرای گیت‌هاب دیر شد، تا WINDOW ساعت بعد هم منتشر می‌شود
SLOTS = {"tip": 9, "mistake": 14, "skill": 17, "exam": 22}
WINDOW = 3
LETTERS = quiz.LETTERS

HEAD = {"tip": "💡 <b>نکته‌ی روز</b>", "mistake": "🤯 <b>اینو اکثراً غلط می‌زنن!</b>",
        "skill": "🎯 <b>مهارت تست‌زنی</b>", "exam": "📝 <b>سؤال تستی با پاسخ تشریحی</b>"}
TAG = {"tip": "نکته_روز", "mistake": "اشتباه_رایج", "skill": "مهارت_تست_زنی",
       "exam": "سؤال_تشریحی"}
IMG_TITLE = {"mistake": "این سؤال رو بیشتر شرکت‌کننده‌ها غلط جواب می‌دن",
             "exam": "سؤال به سبک آزمون‌های استخدامی با پاسخ تشریحی"}


def _load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def hashtags(kind, item):
    tags = ["#" + TAG[kind]]
    if item.get("topic"):
        tags.append("#" + item["topic"].split(" (")[0].replace("‌", "_").replace(" ", "_"))
    return " ".join(tags + ["#آزمون_استخدامی"])


def shuffled(item):
    """گزینه‌ها را بُر بزن تا جواب همیشه یک گزینه نباشد؛ اندیس جواب و دام را به‌روز کن."""
    order = list(range(len(item["options"])))
    random.shuffle(order)
    out = dict(item, options=[item["options"][i] for i in order])
    out["answer"] = order.index(item["answer"])
    if item.get("trap") is not None:
        out["trap"] = order.index(item["trap"])
    return out


def _opt(item, i):
    return f"{LETTERS[i]}) {item['options'][i]}"


def texts(kind, item, channel):
    """(متن تلگرام با HTML، متن ساده‌ی بله و ایتا)"""
    raw = item
    esc = {k: (html.escape(v, quote=False) if isinstance(v, str) else
               [html.escape(o, quote=False) for o in v] if k == "options" else v)
           for k, v in item.items()}
    tg, _ = _texts(kind, esc, channel, True)
    _, plain = _texts(kind, raw, channel, False)
    return tg, plain


def _texts(kind, item, channel, _html):
    topic = f" | {item['topic']}" if item.get("topic") else ""
    head = HEAD[kind].replace("</b>", topic + "</b>")
    if kind in ("tip", "skill"):
        body = f"<b>{item['title']}</b>\n\n{item['body']}"
        tg = plain = f"{head}\n\n{body}"
    else:
        opts = "\n".join(_opt(item, i) for i in range(len(item["options"])))
        ans = f"✅ پاسخ درست: {_opt(item, item['answer'])}"
        if kind == "mistake":
            ans += f"\n❌ گزینه‌ی دام: {LETTERS[item['trap']]}) که بیشتر افراد انتخابش می‌کنند"
        ans += f"\n\n💡 {item['explain']}"
        ask = ("🤔 تو کدوم گزینه رو انتخاب می‌کنی؟" if kind == "mistake"
               else "✍️ اول خودت حل کن، بعد پاسخ تشریحی رو ببین.")
        q = f"❓ {item['q']}\n\n{opts}\n\n{ask}"
        tg = f"{head}\n\n{q}\n👇 برای دیدن پاسخ، روی قسمت تار بزن:\n<tg-spoiler>{ans}</tg-spoiler>"
        plain = f"{head}\n\n{q}\n👇 پاسخ پایین‌تره:\n.\n.\n.\n.\n{ans}"
    tags = hashtags(kind, item)
    tg += f"\n\n{quiz.app_promo()}\n\n{tags}\n🆔 {channel}"
    plain = plain.replace("<b>", "").replace("</b>", "")
    plain += f"\n\n{quiz.app_promo(False)}\n\n{tags}\n🆔 {channel}"
    return tg, plain


def image_args(kind, item):
    if kind in ("tip", "skill"):
        return item["title"], kind, item.get("topic")
    return IMG_TITLE[kind], kind, item.get("topic")


def due(state):
    now = extras.iran_now()
    today = now.strftime("%Y-%m-%d")
    done = state.get("slots", []) if state.get("day") == today else []
    for kind, h in sorted(SLOTS.items(), key=lambda x: x[1]):
        if h <= now.hour < h + WINDOW and kind not in done:
            return kind
    return None


def pick(bank, used):
    fresh = [x for x in bank if x["id"] not in used]
    if not fresh:  # همه منتشر شدند؛ از اول
        used.clear()
        fresh = bank
    return random.choice(fresh) if fresh else None


def post(send, make_image, channel, kind=None, dry=False):
    """send(text, photo, mirror_text): همان bot.send.  kind: انتشار دستی همین نوع، خارج از نوبت."""
    bank = _load(BANK, {})
    state = _load(STATE, {})
    slot = None
    if kind is None:
        kind = slot = due(state)
    if not kind or not bank.get(kind):
        return
    used = state.setdefault("used", {}).setdefault(kind, [])
    item = pick(bank[kind], used)
    if kind in ("mistake", "exam"):
        item = shuffled(item)
    tg, plain = texts(kind, item, channel)
    photo = make_image(*image_args(kind, item))
    send(tg, photo, plain)
    if dry:
        return
    used.append(item["id"])
    if slot:
        today = extras.iran_now().strftime("%Y-%m-%d")
        if state.get("day") != today:
            state["day"], state["slots"] = today, []
        state["slots"].append(slot)
    STATE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    print(f"[✓] edu posted: {kind} {item['id']}")
