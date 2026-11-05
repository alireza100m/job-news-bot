"""قالب‌بندی هوشمند خبرها بدون نیاز به هوش مصنوعی (رایگان و همیشه در دسترس)."""
import re

FIELDS = [  # (برچسب در متن خبر, برچسب در پست)
    ("جنسیت", "👥 جنسیت"),
    ("مقطع تحصیلی", "🎓 مقطع"),
    ("رشته تحصیلی", "📚 رشته"),
    ("سابقه کاری", "⏳ سابقه"),
    ("ساعت کاری", "⏰ ساعت کاری"),
    ("حقوق", "💰 حقوق"),
    ("استان مورد نیاز", "📍 استان"),
    ("مهلت ثبت نام", "📅 مهلت ثبت‌نام"),
    ("مهلت ثبت‌نام", "📅 مهلت ثبت‌نام"),
]
STOP = ["عنوان شغلی", "شرایط احراز", "شهر مورد نیاز", "شهر", "محدوده", "نوع همکاری", "مزایا"]
PLACES = """تهران مشهد اصفهان کرج شیراز تبریز قم اهواز کرمانشاه ارومیه رشت زاهدان همدان کرمان یزد
اردبیل بندرعباس اراک زنجان سنندج قزوین خرم‌آباد گرگان ساری بجنورد بوشهر بیرجند ایلام شهرکرد یاسوج
سمنان آمل بابل کیش قشم کاشان""".split()


def _strip_repeated_prefix(s):
    """«استخدام فلانفلان در ...» → «فلان در ...» (ای استخدام اسم شرکت را دو بار می‌چسباند)."""
    if not s.startswith("استخدام "):
        return s
    rest = s[len("استخدام "):]
    for L in range(min(len(rest) // 2, 80), 3, -1):
        if rest[:L] in rest[L:L + L + 10]:
            return rest[L:].strip()
    return s


def _short(text, limit=260):
    text = text.strip()
    if len(text) <= limit:
        return text.rstrip(". ") + "."
    cut = text[:limit]
    for sep in [". ", "؛", "،"]:
        i = cut.rfind(sep)
        if i > limit * 0.5:
            return cut[:i].rstrip() + "."
    return cut.rsplit(" ", 1)[0] + " …"


def parse_title(title):
    """«استخدام منشی در شرکت X در محدوده Y» → (سمت, شرکت, محل)."""
    if not title.startswith("استخدام ") or " در " not in title:
        return None, None, None
    parts = title[len("استخدام "):].split(" در ")
    position, org, place = parts[0], None, None
    for p in parts[1:]:
        first = p.split()[0] if p.split() else ""
        if p.startswith("محدوده") or first in PLACES or p in PLACES:
            place = p.replace("محدوده ", "")
        elif org is None:
            org = p
    return position, org, place


def extract_fields(text):
    labels = [f for f, _ in FIELDS] + STOP
    pattern = "|".join(sorted(map(re.escape, labels), key=len, reverse=True))
    found = {}
    for m in re.finditer(rf"({pattern})\s*:", text):
        label = m.group(1)
        nxt = re.search(rf"({pattern})\s*:", text[m.end():])
        value = text[m.end(): m.end() + nxt.start()] if nxt else text[m.end():]
        value = value.strip(" .،")
        if not value or value.endswith("…") or value.endswith("...") or len(value) > 80:
            continue
        if label in dict(FIELDS) and label not in found:
            found[label] = value
    intro = re.split(r"عنوان شغلی|شرایط احراز|جنسیت\s*:", text)[0]
    return found, intro.strip()


def format_post(title, summary):
    summary = re.sub(r"(\.\.\.|…)\s*$", "…", summary.strip())  # فیلد بریده‌شده‌ی آخر حذف شود
    summary = _strip_repeated_prefix(summary).replace("...", "").strip()
    fields, intro = extract_fields(summary)
    position, org, place = parse_title(title)

    lines = [f"🔸 <b>{title}</b>", ""]
    if position:
        lines.append(f"💼 عنوان شغلی: {position}")
    if org:
        lines.append(f"🏢 محل کار: {org}")
    if place and "استان مورد نیاز" not in fields:
        lines.append(f"📍 محل: {place}")
    for key, label in FIELDS:
        if key in fields and label not in "\n".join(lines):
            lines.append(f"{label}: {fields[key]}")
    if intro:
        if lines[-1] != "":
            lines.append("")
        lines.append(f"📝 {_short(intro)}")
    return "\n".join(lines).strip()
