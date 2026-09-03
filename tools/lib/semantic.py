"""التدقيق الدلالي — هل تقول المادة فعلًا ما نُسب إليها؟

Semantic support checking. The deterministic gate proves an article *exists*.
This layer asks the harder question: does it *say* what the drafter attributed
to it. That is the one defect that passes the existence gate — the marker is
valid, the article is real, and the sentence around it still misstates the law.

Design: signals, not verdicts. Everything computable and high-precision is
decided here (quantities, permission-vs-prohibition). Everything genuinely
arguable is routed to a structured adjudication worksheet instead of being
guessed at, so the office never silently blesses an unchecked claim — and only
the ambiguous minority costs any model tokens.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .arabic import fold, stem
from .quantities import conflicts as quantity_conflicts

# ── الصيغ الحكمية ─────────────────────────────────────────────────────
# النفي في العربية سابق للفعل، فلا تكفي أسبقية الفحص: «لا يجوز» تطابق نمط
# الإباحة داخلها. لذلك تُبنى أنماط الإباحة والاستحقاق على نظرة خلفية تمنع
# مطابقتها بعد أداة نفي — وإلا قُرئت المادة الحاظرة مبيحةً وحاظرةً معًا،
# فتتعطل قاعدة التعارض بين الادعاء المبيح والنص الحاظر.
_NOT_NEGATED = r"(?<!لا )(?<!لم )(?<!لن )(?<!ولا )(?<!ألا )"

# الترتيب مهم أيضًا: الصيغ المنفية تُفحص أولًا.
FRAMES: list[tuple[str, str, re.Pattern]] = [
    ("حظر", "حظر أو منع", re.compile(
        r"(?:لا|لم|لن)\s+(?:يجوز|يحق|يصح|يسوغ)|يحظر|يمنع|محظور|ممنوع|لا\s+يجوز")),
    ("بطلان", "بطلان", re.compile(r"باطل|بطلان|يقع\s+باطل|لاغ|كأن\s+لم\s+يكن")),
    ("استثناء", "عدم سريان", re.compile(
        r"لا\s+تسري|لا\s+تنطبق|لا\s+يسري|يستثن|مع\s+عدم\s+الإخلال|فيما\s+عدا")),
    ("إيجاب", "وجوب أو إلزام", re.compile(
        r"يجب|يتعين|يلتزم|ملزم|وجوب|إلزام|على\s+\S+\s+أن")),
    ("إباحة", "إجازة أو جواز", re.compile(
        rf"{_NOT_NEGATED}(?:يجوز|يحق|جائز)|له\s+أن|للعامل\s+أن")),
    ("استحقاق", "استحقاق", re.compile(
        rf"{_NOT_NEGATED}(?:يستحق|تستحق|استحقاق)|له\s+الحق")),
]

# كلمات وظيفية لا تحمل معنى قانونيًا مميّزًا — تُستبعد من قياس التداخل
_STOP = {
    "من", "في", "على", "الى", "عن", "مع", "او", "ان", "انه", "التي", "الذي", "ما",
    "لا", "قد", "كل", "هذا", "هذه", "ذلك", "به", "بها", "له", "لها", "هو", "هي",
    "كان", "كانت", "يكون", "تكون", "لم", "لن", "غير", "بين", "عند", "بعد", "قبل",
    "حيث", "لما", "فان", "وان", "اذا", "الا", "سوي", "ايض", "كذلك", "ثم", "بموجب",
    "احكام", "حكم", "نص", "ماده", "قانون", "وفق", "طبق", "مقتضي", "مفاد", "شان",
}


@dataclass
class Support:
    """نتيجة فحص إسناد واحد."""
    verdict: str                              # مسنود | متعارض | يحتاج تحكيمًا
    overlap: float = 0.0
    conflicts: list[str] = field(default_factory=list)
    doubts: list[str] = field(default_factory=list)
    claim_frames: list[str] = field(default_factory=list)
    article_frames: list[str] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return self.verdict == "متعارض"


def claim_span(text: str, marker_pos: int, marker_len: int,
               others: list[tuple[int, int]] | None = None) -> str:
    """الجملة التي وردت فيها العلامة — وهي ما نسبه الصائغ إلى المادة.

    Arabic legal sentences are long («لما كان … وكان … فإنه»); the whole
    sentence is the unit of attribution.

    A single newline is NOT a boundary: Markdown soft-wraps, so breaking there
    would truncate the claim mid-sentence and hide exactly the misstatement
    this layer exists to catch — the wrong figure usually sits on the next
    visual line. Only sentence-final punctuation, a blank line, or a heading
    ends the span.

    A sentence often carries two markers («مفاد المادة (99) ⟦…⟧ … وكانت المادة
    (111) ⟦…⟧ …»). Each claim is therefore clamped to its neighbouring markers,
    so one citation is not judged against wording that belongs to the other —
    otherwise every marker inherits its neighbour's legal frame and the doubts
    become noise.
    """
    # يبتلع سطر العنوان كاملًا حتى لا يدخل في جملة الادعاء
    boundary = re.compile(r"[.؟!]|\n[ \t]*\n|\n[ \t]*#{1,6}[^\n]*|\n[ \t]*[-*>]\s")

    start = 0
    for m in boundary.finditer(text, 0, marker_pos):
        start = m.end()
    m = boundary.search(text, marker_pos + marker_len)
    end = m.start() if m else len(text)

    # سطر العنوان قد يقع في صدر المقطع، فيُزاح
    head = re.match(r"[ \t]*#{1,6}[^\n]*\n", text[start:end])
    if head:
        start += head.end()

    # القصر على المنطقة بين العلامتين المجاورتين
    for o_pos, o_len in others or []:
        if o_pos == marker_pos:
            continue
        if o_pos < marker_pos:
            start = max(start, o_pos + o_len)
        else:
            end = min(end, o_pos)

    # القصر إلى حدود الجملة الفرعية: العربية القانونية تركّب جُملًا بالفواصل
    # وواو العطف، والحكم المنسوب يلي العلامة عادةً («المادة (111) ⟦…⟧ تقضي بـ…»).
    # يُتجاهل التضييق إن أنتج مقطعًا أقصر من أن يُحكم عليه.
    # يُقاس الحد الأدنى على المقطع الناتج كاملًا، لا على ما قبل العلامة وحده:
    # الحكم المنسوب يلي العلامة، فالجزء السابق لها قصير بطبيعته.
    MIN = 25
    c_start = max((text.rfind(ch, start, marker_pos) for ch in ("،", "؛")), default=-1)
    c_end = min((p for ch in ("،", "؛")
                 if (p := text.find(ch, marker_pos + marker_len, end)) != -1), default=-1)
    n_start = c_start + 1 if c_start != -1 else start
    n_end = c_end if c_end != -1 else end
    if n_end - n_start >= MIN:
        start, end = n_start, n_end

    span = re.sub(r"⟦[^⟧]*⟧", " ", text[start:end])
    return re.sub(r"\s+", " ", span).strip()


def frames(text: str) -> list[str]:
    """الصيغ الحكمية الواردة في النص."""
    return [name for name, _, rx in FRAMES if rx.search(text)]


def content_terms(text: str) -> set[str]:
    """الكلمات الحاملة للمعنى، مُجذّعة."""
    return {stem(w) for w in fold(text).split()
            if len(w) > 2 and w not in _STOP and stem(w) not in _STOP}


def overlap(claim: str, article: str, idf: dict[str, float] | None = None) -> float:
    """نسبة مصطلحات الادعاء التي ترد في المادة، موزونة بندرة المصطلح.

    Unweighted overlap is misleading in legal Arabic: «يستحق العامل تعويضًا عن
    الفصل التعسفي» shares «يستحق» and «العامل» with almost any labour
    provision. Weighting by corpus rarity (IDF) makes the distinctive terms —
    «تعويض»، «فصل»، «تعسفي» — carry the judgement, which is what a reader
    actually checks.
    """
    c, a = content_terms(claim), content_terms(article)
    if not c:
        return 0.0
    if not idf:
        return len(c & a) / len(c)
    w = lambda t: idf.get(t, max(idf.values(), default=1.0))  # noqa: E731
    total = sum(w(t) for t in c)
    return sum(w(t) for t in c & a) / total if total else 0.0


def check(claim: str, article: str, *, min_overlap: float = 0.35,
          idf: dict[str, float] | None = None) -> Support:
    """فحص إسناد واحد: هل تسند المادة ما نُسب إليها؟"""
    cf, af = frames(claim), frames(article)
    ov = overlap(claim, article, idf)
    conflicts_: list[str] = []
    doubts: list[str] = []

    # ── تعارض قاطع 1: مقدار يؤكده الادعاء ولا يرد في المادة ──
    conflicts_ += quantity_conflicts(claim, article)

    # ── تعارض قاطع 2: الادعاء يبيح والمادة تحظر ──
    claim_permits = ("إباحة" in cf or "استحقاق" in cf) and "حظر" not in cf
    if claim_permits and "حظر" in af and "إباحة" not in af:
        conflicts_.append(
            "الادعاء يقرر جوازًا أو استحقاقًا، والمادة صيغتها حظر أو منع")

    # ── شك يستوجب تحكيمًا ──
    if ov < min_overlap:
        doubts.append(
            f"تداخل المصطلحات مع نص المادة ضعيف ({ov:.0%}) — قد تكون المادة "
            f"في موضوع آخر")
    labels = {name: label for name, label, _ in FRAMES}
    for strong in ("حظر", "بطلان", "إيجاب"):
        # نسبة حظر أو بطلان أو وجوب إلى مادة لا تحمله ادعاء ثقيل يستحق التحكيم.
        if strong in cf and strong not in af:
            doubts.append(
                f"الادعاء بصيغة «{labels[strong]}» ولا تحمل المادة هذه الصيغة"
                + (f" (صيغتها: {'، '.join(af)})" if af else " (بلا صيغة حكمية ظاهرة)"))
    if "استثناء" in af and "استثناء" not in cf:
        doubts.append("المادة تتضمن استثناءً أو عدم سريان لم يعكسه الادعاء")

    verdict = "متعارض" if conflicts_ else ("يحتاج تحكيمًا" if doubts else "مسنود")
    return Support(verdict=verdict, overlap=ov, conflicts=conflicts_,
                   doubts=doubts, claim_frames=cf, article_frames=af)
