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


# عناصر تُعدّ كتلة مستقلة: أصغر واحدة تحيط بالرابط هي «سياقه».
_BLOCKS = {"li", "tr", "td", "th", "p", "div", "article", "section", "dd", "dt",
           "h1", "h2", "h3", "h4", "h5", "h6", "figcaption", "caption"}
_MAX_CONTEXT = 300


@dataclass
class Link:
    url: str
    text: str
    context: str = ""

    @property
    def haystack(self) -> str:
        """نص الرابط، وسياقه إن كان نصه شحيحًا."""
        return f"{self.text} {self.context}".strip() if self.context else self.text


@dataclass
class Candidate:
    url: str
    text: str
    score: float
    reasons: list[str] = field(default_factory=list)
    number_year: bool = False
    coverage: float = 0.0
    from_context: bool = False

    @property
    def strong(self) -> bool:
        """هل يكفي للتسجيل الآلي؟ أربعة شروط مجتمعة، لا واحد منها.

        `from_context` يمنع التسجيل الآلي عمدًا: ترشيح مبني على نص مجاور
        للرابط — لا على نص الرابط نفسه — قد يلتقط رابط تشريع مجاور في
        الجدول. يُعرض ليُراجَع، ولا يُكتب في السجل بلا عين.
        """
        return (self.score >= 0.9 and self.number_year and self.coverage >= 0.6
                and not self.from_context)


class _LinkParser(HTMLParser):
    """يجمع كل رابط ونصه الظاهر — بلا افتراض عن بنية الصفحة."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[Link] = []
        self._stack: list[list] = []
        self._blocks: list[list[str]] = []
        self._pending: list[tuple[Link, list[list[str]]]] = []

    def handle_starttag(self, tag, attrs):
        if tag in _BLOCKS:
            self._blocks.append([])
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
        for blk in self._blocks:
            blk.append(data)

    def handle_startendtag(self, tag, attrs):
        if tag == "img" and self._stack:
            self._stack[-1][1].append(dict(attrs).get("alt") or "")

    def handle_endtag(self, tag):
        if tag == "a" and self._stack:
            href, parts = self._stack.pop()
            text = re.sub(r"\s+", " ", " ".join(parts)).strip()
            link = Link(href, text)
            self.links.append(link)
            # السياق يُحسم بعد الفراغ من الصفحة: نص الكتلة قد يكتمل بعد الرابط
            self._pending.append((link, list(reversed(self._blocks))))
        elif tag in _BLOCKS and self._blocks:
            self._blocks.pop()

    def close(self):
        super().close()
        for link, ancestors in self._pending:
            anchor = len(link.text)
            for blk in ancestors:          # من الأضيق إلى الأوسع
                txt = re.sub(r"\s+", " ", "".join(blk)).strip()
                if not txt or len(txt) <= anchor:
                    continue               # كتلة لا تحوي غير الرابط: لا تضيف شيئًا
                if len(txt) > _MAX_CONTEXT:
                    break                  # والأوسع منها أكبر — لا سياق مفيد
                link.context = txt
                break
        self._pending.clear()


def links(html: str, base_url: str, *, same_host_only: bool = True) -> list[Link]:
    """استخراج روابط الصفحة، مُطلقة ومُنقّاة من التكرار."""
    p = _LinkParser()
    try:
        p.feed(html)
    except Exception:  # noqa: BLE001 — صفحات حكومية قديمة تخالف المحلل المتساهل
        pass
    try:
        p.close()      # وفيه يُحسم سياق كل رابط — يُستدعى ولو تعثّر التحليل
    except Exception:  # noqa: BLE001
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
        out.append(Link(url, ln.text, ln.context))
    return out


def _tokens(text: str) -> set[str]:
    return {stem(w) for w in fold(text).split() if len(w) > 1}


def _digit_hit(haystack: str, value: str) -> bool:
    """رقم قائم بذاته لا جزءًا من رقم أطول: «36» لا تطابق «1936»."""
    return re.search(rf"(?<!\d){re.escape(str(value))}(?!\d)", haystack) is not None


def _coverage(title_tokens: set[str], text: str) -> float:
    return (len(title_tokens & _tokens(text)) / len(title_tokens)
            if title_tokens else 0.0)


def score(inst: dict, link: Link) -> Candidate:
    """ترجيح رابط لتشريع، مع أسباب الترجيح معلنة.

    الفهارس الرسمية كثيرًا ما تضع عنوان التشريع في الصف أو البند، والرابط
    نفسه كلمة واحدة («تحميل»، «PDF»). فحين يعجز نص الرابط، يُجرَّب سياقه —
    أضيق كتلة تحيط به — مع خصم، ومع منع التسجيل الآلي على أساسه.
    """
    own = normalize_digits(f"{link.text} {link.url}")
    title_tokens = _tokens(inst["title"])
    cov = _coverage(title_tokens, link.text)

    year_hit, num_hit = _digit_hit(own, inst["year"]), _digit_hit(own, inst["number"])
    type_hit = any(w in fold(link.text) for w in _TYPE_WORDS.get(inst["type"], ()))
    from_context = False

    # نص الرابط لا يعرّف تشريعًا: جرّب سياقه
    if link.context and cov < 0.5 and not (year_hit and num_hit):
        ctx = normalize_digits(link.context)
        c_cov = _coverage(title_tokens, link.context)
        c_year, c_num = _digit_hit(ctx, inst["year"]), _digit_hit(ctx, inst["number"])
        if c_cov > cov or (c_year and c_num):
            cov, year_hit, num_hit, from_context = max(cov, c_cov), c_year, c_num, True
            type_hit = type_hit or any(w in fold(link.context)
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
    if from_context:
        s *= 0.85
        why.append("من سياق الصفحة لا من نص الرابط")
    elif len(link.text) < 4:
        s *= 0.5
        why.append("نص رابط شحيح")
    # ما يُعرض هو ما طابق فعلًا: نص الرابط، أو السياق حين كان هو الدليل
    shown = (link.context if from_context else link.text) or link.context
    return Candidate(url=link.url, text=shown,
                     score=min(round(s, 3), 1.0), reasons=why,
                     number_year=year_hit and num_hit, coverage=cov,
                     from_context=from_context)


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
