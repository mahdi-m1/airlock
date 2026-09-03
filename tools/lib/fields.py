"""الحقول الحرجة في مستندات القضايا — استخراجها وفحص تماسكها ومقابلة القراءات.

Critical-field verification for extracted documents. This exists because of one
specific failure the confidence score in `documents.py` cannot see:

    OCR reads «٣٠ يومًا» as «٣٧ يومًا». The text is fluent, the confidence is
    high, every quality heuristic passes — and the office now has a wrong
    limitation period in a case file.

No text-only reader can catch that, an AI reviewer included: the wrong digit is
gone from the text, and a model asked to «verify» the text will make it *more*
fluent, not more true. What does catch it:

1. **قراءتان مستقلتان** — the same page read twice with different settings
   (`pdftotext -layout` vs `-raw`, tesseract `--psm 6` vs `--psm 4`). A digit
   that two readers disagree on is exactly where the error lives.
2. **تماسك داخلي** — a date that is not a valid calendar date; a total that is
   not the sum of its parts; a duration that contradicts the span between two
   dates; a national ID whose date part is impossible; a number written in two
   digit scripts at once. Each is checkable without the original.
3. **تأكيد بشري للحقول الحرجة وحدها** — not the whole document: the dozen
   numbers a case actually turns on.

الغرض إذًا ليس رفع ثقة القراءة بل **حصر الشك في حقول معدودة** يُقابَل كل منها
بالأصل، بدل «راجع المستند» التي لا يفعلها أحد.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date

from . import quantities
from .arabic import fold, normalize_digits

# ── أسماء الشهور ──────────────────────────────────────────────────────
_GREG = {
    "يناير": 1, "كانون الثاني": 1, "فبراير": 2, "شباط": 2, "مارس": 3, "اذار": 3,
    "ابريل": 4, "أبريل": 4, "نيسان": 4, "مايو": 5, "ايار": 5, "يونيو": 6,
    "حزيران": 6, "يوليو": 7, "تموز": 7, "اغسطس": 8, "أغسطس": 8, "اب": 8,
    "سبتمبر": 9, "ايلول": 9, "اكتوبر": 10, "أكتوبر": 10, "تشرين الاول": 10,
    "نوفمبر": 11, "تشرين الثاني": 11, "ديسمبر": 12, "كانون الاول": 12,
}
_HIJRI = ("محرم", "صفر", "ربيع الاول", "ربيع الثاني", "جمادى الاولى",
          "جمادى الاخره", "رجب", "شعبان", "رمضان", "شوال", "ذو القعده",
          "ذو الحجه")

_MONTH_ALT = "|".join(sorted(_GREG, key=len, reverse=True))
_HIJRI_ALT = "|".join(sorted(_HIJRI, key=len, reverse=True))

_RE_NUM_DATE = re.compile(r"(?<!\d)(\d{1,4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})(?!\d)")
_RE_NAMED = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_MONTH_ALT})\s+(\d{{4}})(?!\d)")
_RE_HIJRI = re.compile(rf"(?<!\d)(\d{{1,2}})\s+({_HIJRI_ALT})\s+(\d{{3,4}})")
_RE_MONEY = re.compile(
    r"(?<![\d.])(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(دينار\w*|د\.?\s?ب|BHD|فلس\w*|ريال\w*|دولار\w*|درهم\w*)"
    r"|(BHD|د\.?\s?ب)\s*(\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)",
    re.IGNORECASE)
_RE_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|٪|بالمائة|في المائة|بالمئة)")
_RE_IDNUM = re.compile(r"(?<!\d)(\d{8,11})(?!\d)")
_TOTAL_WORDS = ("المجموع", "الاجمالي", "الإجمالي", "جمله", "جملة", "الكلي")
_UNIT_SURFACES = {
    "يوم": ("يوما", "أيام", "ايام", "يومين", "يومًا", "يوم"),
    "اسبوع": ("اسابيع", "أسابيع", "اسبوعين", "اسبوعا", "اسبوع"),
    "شهر": ("اشهر", "أشهر", "شهور", "شهرين", "شهرًا", "شهرا", "شهر"),
    "سنه": ("سنوات", "سنين", "سنتين", "اعوام", "أعوام", "عامين", "سنة", "سنه", "عام"),
    "ساعه": ("ساعات", "ساعتين", "ساعة", "ساعه"),
}


@dataclass(frozen=True)
class Field:
    """حقل حرج واحد، بموضعه وسياقه — ليُقابَل بالأصل."""
    kind: str          # date | money | duration | percent | idnum
    raw: str           # كما ورد في النص
    value: str         # مطبَّع للمقارنة بين القراءات
    line: int
    context: str

    @property
    def label(self) -> str:
        return {"date": "تاريخ", "money": "مبلغ", "duration": "مدة",
                "percent": "نسبة", "idnum": "رقم"}.get(self.kind, self.kind)


def _ctx(text: str, start: int, end: int, width: int = 48) -> str:
    a, b = max(0, start - width), min(len(text), end + width)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def _resolve_numeric(a: str, b: str, c: str) -> tuple[str | None, str]:
    """يفكّ 14/03/2024 و2024-03-14. يعيد (القيمة، ملاحظة)."""
    ia, ib, ic = int(a), int(b), int(c)
    if len(a) == 4:                       # سنة أولًا: ISO
        return _iso(ia, ib, ic), ""
    year = ic if len(c) == 4 else (2000 + ic if ic < 70 else 1900 + ic)
    iso = _iso(year, ib, ia)              # يوم/شهر/سنة — العُرف البحريني
    if iso:
        note = ("ترتيب اليوم والشهر ملتبس (كلاهما ≤ 12) — قابِله بالأصل"
                if ia <= 12 and ib <= 12 and ia != ib else "")
        return iso, note
    swapped = _iso(year, ia, ib)          # قد يكون شهر/يوم/سنة
    if swapped:
        return swapped, "قُرئ شهرًا/يومًا لأن اليوم/الشهر غير ممكن"
    return None, "تاريخ غير صحيح تقويميًا"


def _mixed_scripts(raw: str) -> bool:
    """رقم بخانتين من كتابتين — أثر تعرّف ضوئي لا كتابة بشرية."""
    return bool(re.search(r"[0-9]", raw)) and bool(re.search(r"[٠-٩۰-۹]", raw))


def find(text: str) -> list[Field]:
    """كل الحقول الحرجة في النص، بترتيب ورودها."""
    out: list[Field] = []
    seen: set[tuple[str, str, int]] = set()

    def add(kind: str, raw: str, value: str, start: int, end: int) -> None:
        key = (kind, value, _line_of(text, start))
        if key in seen:
            return
        seen.add(key)
        out.append(Field(kind, raw.strip(), value, _line_of(text, start),
                         _ctx(text, start, end)))

    norm = normalize_digits(unicodedata.normalize("NFC", text))

    for m in _RE_NAMED.finditer(norm):
        d, mon, y = int(m.group(1)), _GREG[m.group(2)], int(m.group(3))
        add("date", m.group(0), _iso(y, mon, d) or f"?{m.group(0)}", m.start(), m.end())
    for m in _RE_HIJRI.finditer(norm):
        add("date", m.group(0), f"هجري:{m.group(0)}", m.start(), m.end())
    for m in _RE_NUM_DATE.finditer(norm):
        iso, _ = _resolve_numeric(m.group(1), m.group(2), m.group(3))
        add("date", m.group(0), iso or f"?{m.group(0)}", m.start(), m.end())

    for m in _RE_MONEY.finditer(norm):
        amount = m.group(1) or m.group(4)
        cur = (m.group(2) or m.group(3) or "").strip()
        add("money", m.group(0), f"{amount.replace(',', '')} {fold(cur)}".strip(),
            m.start(), m.end())
    for m in _RE_PERCENT.finditer(norm):
        add("percent", m.group(0), m.group(1), m.start(), m.end())

    # المدد: ألفاظًا وأرقامًا — quantities يقرأ «خمسة وأربعين» و«يومين»
    # الموضع من لفظ الوحدة لا من الرقم: البحث عن «5» يقع على أول خمسة في الصفحة
    # فيُنسب الحقل إلى سطر لا علاقة له به، والسطر هو ما يُقابَل بالأصل.
    # سنوات التواريخ تبدو مددًا: «إلى 01/01/2021 لمدة ثلاث سنوات» تُقرأ منها
    # «2021 سنة». تُستبعد بسنوات التواريخ المكتشفة وبسقف معقول للمدد.
    date_years = {v.value[:4] for v in out if v.kind == "date"}
    caps = {"سنه": 150, "شهر": 1200, "اسبوع": 5200, "يوم": 36500, "ساعه": 100000}
    for value, unit in sorted(quantities.extract(text)):
        if unit not in ("يوم", "اسبوع", "شهر", "سنه", "ساعه"):
            continue
        if value > caps[unit]:
            continue
        if unit == "سنه" and f"{value:g}" in date_years:
            continue
        pos = -1
        for surface in _UNIT_SURFACES.get(unit, (unit,)):
            found = norm.find(surface)
            if found >= 0 and (pos < 0 or found < pos):
                pos = found
        pos = max(pos, 0)
        add("duration", f"{value:g} {unit}", f"{value:g} {unit}",
            pos, pos + len(unit))

    for m in _RE_IDNUM.finditer(norm):
        add("idnum", m.group(0), m.group(1), m.start(), m.end())
    return out


# ── التماسك الداخلي ───────────────────────────────────────────────────
def consistency(fields: list[Field], text: str) -> list[str]:
    """ما يمكن كشفه بلا الرجوع إلى الأصل."""
    notes: list[str] = []
    norm = normalize_digits(text)

    # يُفحص خلط الكتابتين على النص الأصلي: الحقول تُستخرج بعد تطبيع الأرقام،
    # فلو فُحصت لما بقي أثر للخلط أصلًا.
    for m in re.finditer(r"[\d٠-٩۰-۹]{2,}", text):
        if _mixed_scripts(m.group(0)):
            notes.append(f"«{m.group(0)}» يخلط الأرقام العربية واللاتينية — أثر "
                         f"تعرّف ضوئي لا كتابة بشرية (سطر {_line_of(text, m.start())})")

    for f in fields:
        if f.kind == "date" and f.value.startswith("?"):
            notes.append(f"«{f.raw}» ليس تاريخًا صحيحًا تقويميًا (سطر {f.line})")
        if f.kind == "date" and f.value.startswith("هجري:"):
            notes.append(f"«{f.raw}» تاريخ هجري — حوّله ميلاديًا قبل حساب أي مدة "
                         f"(سطر {f.line})")
        if f.kind == "percent" and float(f.value) > 100:
            notes.append(f"نسبة {f.value}% تتجاوز المائة (سطر {f.line})")

    # الدينار البحريني ثلاث خانات عشرية (١٠٠٠ فلس)، فخانة أو اثنتان مظنّة قراءة ناقصة
    for f in fields:
        if f.kind != "money" or "دينار" not in f.value and "bhd" not in f.value.lower():
            continue
        if "." in f.value.split()[0]:
            dec = len(f.value.split()[0].split(".")[1])
            if dec in (1, 2):
                notes.append(f"«{f.raw}» بـ{dec} خانة عشرية، والدينار البحريني "
                             f"ثلاث (فلس) — قد تكون خانة ساقطة (سطر {f.line})")
            elif dec > 3:
                notes.append(f"«{f.raw}» بـ{dec} خانات عشرية — أكثر من الدينار "
                             f"(سطر {f.line})")

    # الرقم الشخصي البحريني تسع خانات وأولها ست خانات تاريخ ميلاد
    for f in fields:
        if f.kind == "idnum" and len(f.value) == 9:
            yy, mm, dd = f.value[:2], f.value[2:4], f.value[4:6]
            if not _iso(1900 + int(yy), int(mm) or 13, int(dd) or 32):
                notes.append(f"«{f.value}» تسع خانات كالرقم الشخصي، لكن أول ست "
                             f"خانات ليست تاريخًا ممكنًا (سطر {f.line})")

    # المجموع مقابل مفرداته
    amounts = [f for f in fields if f.kind == "money"]
    totals = [f for f in amounts if any(w in norm[max(0, norm.find(f.raw) - 60):
                                                  norm.find(f.raw) + len(f.raw)]
                                        for w in _TOTAL_WORDS)]
    if totals and len(amounts) - len(totals) >= 2:
        for t in totals:
            try:
                tv = float(t.value.split()[0])
                parts = [float(a.value.split()[0]) for a in amounts if a is not t]
            except ValueError:
                continue
            if parts and abs(sum(parts) - tv) > max(0.5, tv * 0.005):
                notes.append(f"«{t.raw}» معلَّم مجموعًا، ومجموع المبالغ الأخرى "
                             f"{sum(parts):g} — لا يتطابقان (سطر {t.line})")

    # المدة مقابل المسافة بين تاريخين — في السطر نفسه وحده.
    #
    # مقابلة كل مدة بكل تاريخين في الوثيقة تُنتج تنبيهات كاذبة بلا حساب: خطاب
    # إنهاء خدمة يحمل تاريخ الإشعار وتاريخ النفاذ ومدة خدمة خمس سنوات، ولا
    # علاقة بين الثلاثة. التعارض الحقيقي يقع حيث تُذكر المدة مع حدّيها:
    # «من 1/1/2020 إلى 1/1/2021 لمدة ثلاث سنوات».
    for ln, line in enumerate(text.split("\n"), 1):
        if not re.search(r"من|خلال|لمده|لمدة|حتى|الى|إلى", line):
            continue
        line_fields = find(line)
        ds = sorted({f.value for f in line_fields if f.kind == "date"
                     and re.fullmatch(r"\d{4}-\d{2}-\d{2}", f.value)})
        if len(ds) < 2:
            continue
        span = (date.fromisoformat(ds[-1]) - date.fromisoformat(ds[0])).days
        for f in line_fields:
            if f.kind != "duration":
                continue
            n, unit = f.value.split()
            days = {"يوم": 1, "اسبوع": 7, "شهر": 30.44, "سنه": 365.25}.get(unit)
            if not days:
                continue
            want = float(n) * days
            if want > 25 and abs(want - span) > max(45.0, want * 0.25):
                notes.append(f"مدة «{f.raw}» (~{want:.0f} يومًا) لا توافق المسافة "
                             f"بين {ds[0]} و{ds[-1]} ({span} يومًا) في السطر {ln} — "
                             f"راجع أيهما المقروء خطأً")
    return notes


# ── مقابلة القراءات المستقلة ──────────────────────────────────────────
def compare(passes: dict[str, str]) -> list[str]:
    """اختلاف الحقول الحرجة بين قراءتين أو أكثر للملف نفسه.

    الاختلاف هو الإشارة: قارئان يختلفان على رقم هو موضع الخطأ بعينه. والاتفاق
    ليس ضمانًا — قد يخطئ القارئان الخطأ نفسه — لكنه يحصر الشك.
    """
    if len(passes) < 2:
        return []
    per: dict[str, dict[str, set[str]]] = {}
    for label, text in passes.items():
        per[label] = {}
        for f in find(text):
            per[label].setdefault(f.kind, set()).add(f.value)

    notes: list[str] = []
    kinds = sorted({k for d in per.values() for k in d})
    for kind in kinds:
        sets = {lab: d.get(kind, set()) for lab, d in per.items()}
        union = set().union(*sets.values())
        common = set.intersection(*sets.values()) if sets else set()
        for value in sorted(union - common):
            where = [lab for lab, s in sets.items() if value in s]
            missing = [lab for lab in sets if lab not in where]
            notes.append(f"{kind}: «{value}» قرأته {' و'.join(where)} "
                         f"ولم تقرأه {' و'.join(missing)}")
    return notes
