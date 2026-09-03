"""استخراج المقادير من النص القانوني العربي — أرقامًا وألفاظًا.

Quantity extraction from Arabic legal text. Periods, amounts and percentages
are where fabricated citations do the most damage: «ثلاثين يومًا» silently
becoming «خمسة وأربعين يومًا» changes a limitation period and can lose a case,
while every word around it still reads correctly.

Deliberately conservative — it must not invent a quantity that is not written.
"""
from __future__ import annotations

import re

from .arabic import fold, normalize_digits

# ── ألفاظ الأعداد ─────────────────────────────────────────────────────
_ONES = {
    "واحد": 1, "واحده": 1, "احد": 1, "اول": 1,
    "اثنان": 2, "اثنين": 2, "ثنتان": 2, "ثنتين": 2,
    "ثلاث": 3, "ثلاثه": 3, "ثالث": 3,
    "اربع": 4, "اربعه": 4, "رابع": 4,
    "خمس": 5, "خمسه": 5, "خامس": 5,
    "ست": 6, "سته": 6, "سادس": 6,
    "سبع": 7, "سبعه": 7, "سابع": 7,
    "ثمان": 8, "ثمانيه": 8, "ثماني": 8, "ثامن": 8,
    "تسع": 9, "تسعه": 9, "تاسع": 9,
    "عشر": 10, "عشره": 10, "عاشر": 10,
}
_TENS = {
    "عشرون": 20, "عشرين": 20,
    "ثلاثون": 30, "ثلاثين": 30,
    "اربعون": 40, "اربعين": 40,
    "خمسون": 50, "خمسين": 50,
    "ستون": 60, "ستين": 60,
    "سبعون": 70, "سبعين": 70,
    "ثمانون": 80, "ثمانين": 80,
    "تسعون": 90, "تسعين": 90,
}
_HUNDREDS = {
    "مايه": 100, "مئه": 100, "مايتان": 200, "مايتين": 200, "مئتان": 200, "مئتين": 200,
    "ثلاثمايه": 300, "اربعمايه": 400, "خمسمايه": 500,
    "ستمايه": 600, "سبعمايه": 700, "ثمانمايه": 800, "تسعمايه": 900,
}
_THOUSANDS = {"الف": 1000, "الفان": 2000, "الفين": 2000, "الاف": 1000}
_NUM_WORDS = {**_ONES, **_TENS, **_HUNDREDS, **_THOUSANDS}

# ── الوحدات، وصيغ المثنى التي تعني «اثنين» ────────────────────────────
_UNITS = {
    "يوم": "يوم", "ايام": "يوم", "يوما": "يوم",
    "اسبوع": "اسبوع", "اسابيع": "اسبوع", "اسبوعا": "اسبوع",
    "شهر": "شهر", "اشهر": "شهر", "شهور": "شهر", "شهرا": "شهر",
    "سنه": "سنه", "سنوات": "سنه", "سنين": "سنه", "عام": "سنه", "اعوام": "سنه",
    "ساعه": "ساعه", "ساعات": "ساعه",
    "دينار": "دينار", "دنانير": "دينار", "دينارا": "دينار",
}
_DUALS = {
    "يومين": ("يوم", 2), "يومان": ("يوم", 2),
    "اسبوعين": ("اسبوع", 2), "اسبوعان": ("اسبوع", 2),
    "شهرين": ("شهر", 2), "شهران": ("شهر", 2),
    "سنتين": ("سنه", 2), "سنتان": ("سنه", 2), "عامين": ("سنه", 2),
    "ساعتين": ("ساعه", 2), "ساعتان": ("ساعه", 2),
}

_TOKEN = re.compile(r"[^\W\d_]+|\d+(?:[.,]\d+)?|%|٪", re.UNICODE)


def _norm_tokens(text: str) -> list[str]:
    """توحيد ثم تقطيع، مع فك واو العطف الملتصقة بلفظ العدد.

    Two Arabic specifics the naive path gets wrong:
      * `fold` drops «%», so it is spelled out before folding.
      * «و» is a *prefix*, so «وأربعين» arrives as one token and a compound
        like «خمسة وأربعين» (45) would otherwise read as 5.
    """
    text = re.sub(r"[%٪]", " بالمائة ", normalize_digits(text))
    toks = _TOKEN.findall(fold(text))
    out: list[str] = []
    for t in toks:
        if len(t) > 1 and t.startswith("و") and (t[1:] in _NUM_WORDS or t[1:] in _DUALS):
            out += ["و", t[1:]]
        else:
            out.append(t)
    return out


def extract(text: str) -> set[tuple[float, str]]:
    """يعيد مجموعة (القيمة، الوحدة). الوحدة "" إن لم تُذكر.

    Reads both digits («30 يومًا») and words («ثلاثين يومًا»), including
    compounds joined by «و» («خمسة وأربعين») and duals («يومين» = 2).
    """
    toks = _norm_tokens(text)
    out: set[tuple[float, str]] = set()
    i = 0
    while i < len(toks):
        t = toks[i]

        # صيغة المثنى تحمل العدد والوحدة معًا
        if t in _DUALS:
            unit, val = _DUALS[t]
            out.add((float(val), unit))
            i += 1
            continue

        value: float | None = None
        if re.fullmatch(r"\d+(?:[.,]\d+)?", t):
            value = float(t.replace(",", "."))
            i += 1
        elif t in _NUM_WORDS:
            # جمع المركّبات: «خمسة وأربعين» = 45، «مائة وعشرين» = 120
            value = float(_NUM_WORDS[t])
            i += 1
            while i + 1 < len(toks) and toks[i] == "و" and toks[i + 1] in _NUM_WORDS:
                value += _NUM_WORDS[toks[i + 1]]
                i += 2
            # «ثلاثمائة ألف»
            if i < len(toks) and toks[i] in _THOUSANDS and value < 1000:
                value *= _THOUSANDS[toks[i]]
                i += 1
        else:
            i += 1
            continue

        # الوحدة تلي العدد عادةً، وقد يفصلها حرف جر أو نعت واحد
        unit = ""
        for look in range(i, min(i + 3, len(toks))):
            tok = toks[look]
            if tok in ("%", "٪") or tok == "بالمايه" or tok == "بالمئه":
                unit = "%"
                break
            if tok in _UNITS:
                unit = _UNITS[tok]
                break
            if tok in _DUALS:
                break
        out.add((value, unit))
    return out


def conflicts(claim: str, article: str) -> list[str]:
    """المقادير التي يؤكدها الادعاء ولا تَرِد في المادة، بوحدة موجودة فيها.

    Only flags a quantity when the article does use that unit — otherwise the
    claim is likely drawing the figure from elsewhere in the case, not
    misquoting the article.
    """
    cq, aq = extract(claim), extract(article)
    a_by_unit: dict[str, set[float]] = {}
    for v, u in aq:
        a_by_unit.setdefault(u, set()).add(v)

    out = []
    for v, u in sorted(cq):
        if not u or u not in a_by_unit:
            continue
        if v not in a_by_unit[u]:
            have = "، ".join(f"{x:g}" for x in sorted(a_by_unit[u]))
            out.append(f"المقدار «{v:g} {u}» غير وارد في المادة (الوارد فيها: {have} {u})")
    return out
