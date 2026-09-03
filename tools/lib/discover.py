"""مطابقة روابط فهرس رسمي بالتشريعات الناقصة في سجل المصادر.

Matches links harvested from an official catalogue page against the
instruments still missing a URL. Deliberately structure-agnostic: it reads
`<a href>` elements and their text, and nothing about any particular site's
markup. A scraper written against one page's structure breaks the week that
page changes, and its silence looks identical to «لا نتائج».

الأهم: هذه الوحدة **تقترح ولا تقرّر**. المطابقة على نص الرابط لا على متن
التشريع، فقد يحمل الفهرس عنوانًا مختصرًا أو معدّلًا أو يشير إلى مرسوم تعديل
بعنوان أصله. القرار للمشغّل، والتحقق النهائي عند الاستيراد من متن النص نفسه.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from .arabic import fold, normalize_digits, stem

_SKIP_SCHEMES = ("javascript:", "mailto:", "tel:", "data:", "#")
_TYPE_WORDS = {
    "law": ("قانون",),
    "dl": ("مرسوم بقانون", "مرسوم رقم", "بقانون"),
    "dec": ("مرسوم",),
    "ord": ("قرار",),
    "reg": ("لائحة", "نظام"),
}


@dataclass
class Link:
    url: str
    text: str


@dataclass
class Candidate:
    url: str
    text: str
    score: float
    reasons: list[str] = field(default_factory=list)
    number_year: bool = False
    coverage: float = 0.0

    @property
    def strong(self) -> bool:
        """هل يكفي للتسجيل الآلي؟ ثلاثة شروط مجتمعة، لا واحد منها."""
        return self.score >= 0.9 and self.number_year and self.coverage >= 0.6


class _LinkParser(HTMLParser):
    """يجمع كل رابط ونصه الظاهر — بلا افتراض عن بنية الصفحة."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._stack: list[list] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        a = dict(attrs)
        href = (a.get("href") or "").strip()
        if not href or href.lower().startswith(_SKIP_SCHEMES):
            return
        # نص الرابط قد يكون في صورة أو سمة title — يُلتقط الاثنان
        self._stack.append([href, [a.get("title") or ""]])

    def handle_data(self, data):
        if self._stack:
            self._stack[-1][1].append(data)

    def handle_startendtag(self, tag, attrs):
        if tag == "img" and self._stack:
            self._stack[-1][1].append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            href, parts = self._stack.pop()
            text = re.sub(r"\s+", " ", " ".join(parts)).strip()
            self.links.append(Link(href, text))


def links(html: str, base_url: str, *, same_host_only: bool = True) -> list[Link]:
    """استخراج روابط الصفحة، مُطلقة ومُنقّاة من التكرار."""
    p = _LinkParser()
    try:
        p.feed(html)
        p.close()
    except Exception:  # noqa: BLE001 — صفحات حكومية قديمة تخالف المحلل المتساهل
        pass
    host = (urlparse(base_url).hostname or "").lower()
    out, seen = [], set()
    for ln in p.links:
        url = urljoin(base_url, ln.url)
        if urlparse(url).scheme not in ("http", "https"):
            continue
        if same_host_only and (urlparse(url).hostname or "").lower() != host:
            continue
        url = url.split("#", 1)[0]
        if url in seen:
            continue
        seen.add(url)
        out.append(Link(url, ln.text))
    return out


def _tokens(text: str) -> set[str]:
    return {stem(w) for w in fold(text).split() if len(w) > 1}


def _digit_hit(haystack: str, value: str) -> bool:
    """رقم قائم بذاته لا جزءًا من رقم أطول: «36» لا تطابق «1936»."""
    return re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", haystack) is not None


def score(inst: dict, link: Link) -> Candidate:
    """ترجيح رابط لتشريع، مع أسباب الترجيح معلنة."""
    hay = normalize_digits(f"{link.text} {link.url}")
    title_tokens = _tokens(inst["title"])
    cov = (len(title_tokens & _tokens(link.text)) / len(title_tokens)
           if title_tokens else 0.0)

    year_hit = _digit_hit(hay, inst["year"])
    num_hit = _digit_hit(hay, inst["number"])
    type_hit = any(w in fold(link.text) or w in link.text
                   for w in _TYPE_WORDS.get(inst["type"], ()))

    s, why = 0.5 * cov, []
    if cov:
        why.append(f"العنوان {cov:.0%}")
    if year_hit and num_hit:
        s += 0.30
        why.append("الرقم والسنة")
    elif year_hit:
        s += 0.15
        why.append("السنة فقط")
    elif num_hit:
        s += 0.05
        why.append("الرقم فقط")
    if type_hit:
        s += 0.10
        why.append("النوع مطابق")
    # صفحة الفهرس نفسها ليست صفحة تشريع
    if len(link.text) < 4:
        s *= 0.5
        why.append("نص رابط شحيح")
    return Candidate(url=link.url, text=link.text, score=min(round(s, 3), 1.0),
                     reasons=why, number_year=year_hit and num_hit, coverage=cov)


def match(instruments: list[dict], found: list[Link], *, floor: float = 0.4,
          top: int = 4) -> dict[str, list[Candidate]]:
    """أفضل المرشّحات لكل تشريع. لا يعيد شيئًا دون العتبة — الصمت أصدق من ترشيح ضعيف."""
    out: dict[str, list[Candidate]] = {}
    for inst in instruments:
        cands = [c for c in (score(inst, ln) for ln in found) if c.score >= floor]
        cands.sort(key=lambda c: (-c.score, len(c.text)))
        if cands:
            out[inst["key"]] = cands[:top]
    return out
