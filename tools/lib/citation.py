"""قواعد رمز الاستشهاد — العقد بين الوكلاء وبوابة التحقق.

Citation marker grammar. Every legal reference an agent writes MUST carry a
machine-readable marker immediately after the Arabic prose reference:

    المادة (99) من قانون العمل في القطاع الأهلي ⟦BH:law:36/2012:م99⟧

The marker is what `tools/citation-gate` resolves against the local corpus.
Prose alone is never trusted — an unresolvable marker fails the stage.
Markers are stripped from the final deliverable by `render_clean()`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .arabic import article_key, normalize_digits

OPEN, CLOSE = "⟦", "⟧"

# أنواع الأدوات التشريعية
INSTRUMENT_TYPES = {
    "law": "قانون",
    "dl": "مرسوم بقانون",
    "dec": "مرسوم",
    "ord": "قرار",
    "reg": "لائحة",
}

_MARKER = re.compile(
    rf"{OPEN}\s*BH\s*:\s*"
    r"(?P<type>law|dl|dec|ord|reg)\s*:\s*"
    r"(?P<number>[\d٠-٩۰-۹]+)\s*/\s*(?P<year>[\d٠-٩۰-۹]{4})\s*"
    r"(?::\s*م\s*(?P<article>[\d٠-٩۰-۹]+)\s*(?P<bis>مكرر(?:ات|ا|اً|ًا)?)?\s*)?"
    rf"{CLOSE}",
    re.UNICODE,
)

# أي شيء يشبه العلامة لكنه لا يطابق القواعد — يجب أن يُبلَّغ عنه لا أن يُتجاهل
_MARKER_LOOSE = re.compile(rf"{OPEN}[^{CLOSE}]{{0,120}}{CLOSE}", re.UNICODE)


@dataclass(frozen=True)
class Citation:
    """استشهاد مُحلَّل."""
    type: str
    number: str
    year: str
    article: str | None
    bis: bool
    raw: str
    pos: int

    @property
    def instrument_id(self) -> str:
        """معرّف الأداة التشريعية: law:36/2012"""
        return f"{self.type}:{self.number}/{self.year}"

    @property
    def article_key(self) -> str | None:
        return article_key(self.article, "مكرر" if self.bis else None) if self.article else None

    @property
    def ref_id(self) -> str:
        """المعرّف الكامل للاستشهاد."""
        return f"{self.instrument_id}:{self.article_key}" if self.article else self.instrument_id

    def to_marker(self) -> str:
        art = f":م{self.article}{'مكرر' if self.bis else ''}" if self.article else ""
        return f"{OPEN}BH:{self.type}:{self.number}/{self.year}{art}{CLOSE}"

    def to_arabic(self, title: str | None = None) -> str:
        """صياغة الاستشهاد بالعربية كما يُكتب في المذكرة."""
        kind = INSTRUMENT_TYPES.get(self.type, "قانون")
        art = f"المادة ({self.article}{' مكرر' if self.bis else ''}) من " if self.article else ""
        name = title or f"{kind} رقم ({self.number}) لسنة {self.year}"
        return f"{art}{name}"


def parse_all(text: str) -> list[Citation]:
    """استخراج كل الاستشهادات الصحيحة من نص، بترتيب ورودها."""
    out: list[Citation] = []
    for m in _MARKER.finditer(text):
        out.append(Citation(
            type=m.group("type"),
            number=normalize_digits(m.group("number")).lstrip("0") or "0",
            year=normalize_digits(m.group("year")),
            article=(normalize_digits(m.group("article")).lstrip("0") or "0")
            if m.group("article") else None,
            bis=bool(m.group("bis")),
            raw=m.group(0),
            pos=m.start(),
        ))
    return out


def find_malformed(text: str) -> list[tuple[int, str]]:
    """العلامات المشوّهة: تبدو كاستشهاد لكنها لا تطابق القواعد.

    These must be surfaced, never silently ignored — a malformed marker is the
    most likely shape of a fabricated citation.
    """
    good = {(m.start(), m.group(0)) for m in _MARKER.finditer(text)}
    return [(m.start(), m.group(0)) for m in _MARKER_LOOSE.finditer(text)
            if (m.start(), m.group(0)) not in good]


def render_clean(text: str) -> str:
    """إزالة العلامات الآلية لإنتاج الوثيقة النهائية بالعربية فقط.

    سطرًا سطرًا لسببين، وكلاهما ظهر في وثيقة فعلية:

    * علامة في أول السطر تترك خلفها مسافة بادئة لم تكن فيه. وهي في Markdown
      ليست تجميلًا: مسافة تُزيح الفقرة عند التصدير إلى Word، وأربع تجعل السطر
      كتلة شفرة. فالمسافة البادئة لا تتجاوز ما كان في الأصل.
    * طيّ المسافات المتكررة على السطر كله كان يبتلع تنسيق القوائم المتداخلة:
      بند فرعي بأربع مسافات يعود بمسافة واحدة فيفقد تداخله. فالطيّ الآن على
      متن السطر وحده، وبادئته تُحفظ كما كتبها الكاتب.
    """
    lines = []
    for line in text.split("\n"):
        keep = len(line) - len(line.lstrip(" \t"))     # البادئة الأصلية
        cleaned = _MARKER.sub("", line)
        pad = len(cleaned) - len(cleaned.lstrip(" \t"))
        body = cleaned[pad:]
        body = re.sub(r"[ \t]+([،.؛:])", r"\1", body)   # مسافة قبل علامة ترقيم
        body = re.sub(r"[ \t]{2,}", " ", body)          # مسافات مزدوجة
        lines.append((cleaned[:min(pad, keep)] + body).rstrip())
    return "\n".join(lines)
