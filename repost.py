"""انتشار دوباره‌ی چند پست پیگیری (با قالب و عکس فعلی) — فقط اجرای دستی.

REPOST_REMINDERS: بخشی از عنوان آزمون‌ها، جدا با |   (یادآوری مهلت)
REPOST_WEEKLY=1: جمع‌بندی هفتگی
REPOST_QUIZ=1: یک سؤال کوییز همین الان (REPOST_TG_ONLY=1: بدون بله و ایتا)
"""
import os

import bot
import followups

tracked = followups.load()
bot.fetch_items(bot.load_json(bot.SOURCES_FILE, []))  # برای تقویم سراسری
followups.update_from_calendar(tracked, bot.CALENDAR)
for part in [w for w in os.environ.get("REPOST_REMINDERS", "").split("|") if w]:
    key = next((k for k, v in tracked.items() if part in v["title"]), None)
    left = followups.days_left(tracked[key].get("deadline")) if key else None
    if key is None or left is None or left < 0:
        print(f"[!] not found or expired: {part}")
        continue
    bot.send_followup(tracked, key, "reminder", left)
if os.environ.get("REPOST_QUIZ") == "1":
    import quiz
    tg_only = os.environ.get("REPOST_TG_ONLY") == "1"  # آزمایشی: فقط تلگرام
    quiz.post(bot.TELEGRAM_TOKEN, bot.CHANNEL,
              (lambda *a, **k: None) if tg_only else bot.send_mirrors, force=True)
if os.environ.get("REPOST_WEEKLY") == "1":
    bot.post_weekly(tracked)
followups.save(tracked)
