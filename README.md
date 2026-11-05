# ربات اخبار استخدامی آزمون یار

هر ۳۰ دقیقه اخبار استخدامی را از منابع داخل `sources.json` می‌خواند، با هوش مصنوعی GitHub خلاصه می‌کند و در کانال [@azmoonyar_estekhdam](https://t.me/azmoonyar_estekhdam) منتشر می‌کند.

- افزودن منبع جدید: یک خط به `sources.json` اضافه کنید (هر لینک RSS).
- اجرای دستی: تب **Actions** › «انتشار اخبار استخدامی» › **Run workflow**.
- توکن ربات در **Settings › Secrets and variables › Actions** با نام `TELEGRAM_BOT_TOKEN` ذخیره می‌شود.
