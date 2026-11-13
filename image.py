"""تصویر ساده‌ی هر پست: لوگوی آزمون یار + عنوان خبر (Pillow، فونت وزیرمتن)."""
import io
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, features

ASSETS = Path(__file__).parent / "assets"
FONT_BOLD = str(ASSETS / "Vazirmatn-FD-Black.ttf")
FONT_MED = str(ASSETS / "Vazirmatn-FD-Medium.ttf")
W, H = 1280, 720
TOP, BOTTOM = (42, 104, 214), (11, 36, 98)   # همان آبی لوگو
YELLOW, WHITE = (250, 204, 21), (255, 255, 255)

BADGES = {None: "استخدام دولتی", "soon": "به‌زودی", "reminder": "⏰ یادآوری مهلت",
          "card": "کارت ورود به جلسه", "results": "اعلام نتایج", "weekly": "جمع‌بندی هفتگی"}
BADGES["reminder"] = "یادآوری مهلت"  # فونت ایموجی ندارد
BADGES.update({"tip": "نکته‌ی روز", "mistake": "اکثراً غلط می‌زنن", "skill": "مهارت تست‌زنی",
               "exam": "پاسخ تشریحی"})


def available():
    return features.check("raqm")  # برای چسباندن حروف فارسی لازم است


def _font(path, size):
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)


def _len(draw, text, font):
    return draw.textlength(text, font=font, direction="rtl", language="fa")


def _wrap(draw, text, font, width):
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if cur and _len(draw, t, font) > width:
            lines.append(cur)
            cur = w
        else:
            cur = t
    if cur:
        lines.append(cur)
    return lines


def _rtl(draw, xy_right, y, text, font, fill):
    """متن راست‌چین که لبه‌ی راستش روی xy_right باشد."""
    draw.text((xy_right - _len(draw, text, font), y), text, font=font, fill=fill,
              direction="rtl", language="fa")


def _center(draw, y, text, font, fill):
    draw.text(((W - _len(draw, text, font)) / 2, y), text, font=font, fill=fill,
              direction="rtl", language="fa")


def clean_title(title):
    t = re.sub(r"<[^>]+>", "", title)
    t = re.sub(r"[^\w\s‌،:()\-/«»]", "", t)  # ایموجی و نشانه‌های اضافه
    return re.sub(r"\s+", " ", t).strip()


def make_image(title, kind=None, subtitle=None, channel="@azmoonyar_estekhdam"):
    """PNG بایت‌ها را برمی‌گرداند."""
    img = Image.new("RGB", (W, H))
    px = img.load()
    for y in range(H):  # گرادیان مورب ساده
        for x in range(0, W, 8):
            k = min(1, max(0, (y / H) * 0.75 + (x / W) * 0.25))
            c = tuple(int(TOP[i] + (BOTTOM[i] - TOP[i]) * k) for i in range(3))
            for dx in range(8):
                px[x + dx, y] = c
    d = ImageDraw.Draw(img)

    # لوگو در گوشه‌ی بالا راست
    logo = Image.open(ASSETS / "logo.png").convert("RGB").resize((150, 150), Image.LANCZOS)
    mask = Image.new("L", logo.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 149, 149), 28, fill=255)
    img.paste(logo, (W - 60 - 150, 46), mask)

    # برچسب نوع خبر (زرد) در بالا چپ
    bf = _font(FONT_BOLD, 34)
    badge = BADGES.get(kind, BADGES[None])
    bw = _len(d, badge, bf) + 56
    d.rounded_rectangle((60, 70, 60 + bw, 70 + 64), 32, fill=YELLOW)
    d.text((60 + 28, 70 + 6), badge, font=bf, fill=BOTTOM, direction="rtl", language="fa")

    # عنوان: بزرگ‌ترین اندازه‌ای که در حداکثر ۳ خط جا شود
    title = clean_title(title)
    for size in (76, 68, 60, 54, 48, 42):
        tf = _font(FONT_BOLD, size)
        lines = _wrap(d, title, tf, W - 160)
        if len(lines) <= 3:
            break
    lines = lines[:3]
    lh = int(size * 1.55)
    block = lh * len(lines)
    y0 = 235 + (300 - block) / 2
    for i, line in enumerate(lines):
        _center(d, y0 + i * lh, line, tf, WHITE)

    if subtitle:
        sf = _font(FONT_MED, 38)
        _center(d, 560, subtitle, sf, YELLOW)

    # نوار پایین
    d.rectangle((0, H - 70, W, H), fill=(8, 26, 72))
    ff = _font(FONT_MED, 30)
    _rtl(d, W - 60, H - 60, "کانال اخبار استخدامی آزمون یار", ff, WHITE)
    d.text((60, H - 58), channel, font=_font(FONT_MED, 28), fill=YELLOW)

    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


if __name__ == "__main__":
    import sys
    Path(sys.argv[1] if len(sys.argv) > 1 else "sample.png").write_bytes(
        make_image("آزمون استخدامی دانشگاه علوم پزشکی یاسوج", "reminder", "مهلت ثبت‌نام: تا ۲۳ آبان ۱۴۰۵"))
