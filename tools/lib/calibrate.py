"""معايرة عتبة التداخل الدلالي من المدونة نفسها.

Calibrating the semantic overlap threshold empirically. The threshold decides
when a citation is routed to manual adjudication, and a guessed value is either
noise (too high — every sound draft gets flagged) or a hole (too low —
misattributions pass as supported). Neither is acceptable in legal work.

The corpus can measure it. Two populations are built from the articles
themselves:

  * **موجبة** — a claim restating part of an article, paired with that article.
    This is what a sound citation looks like: the drafter paraphrases a portion
    of the rule, not all of it.
  * **سالبة** — the same claim paired with a *different* article, weighted
    toward neighbours in the same instrument, because citing المادة (110)
    instead of (111) is the realistic mistake, not citing a random statute.

The threshold is then set where misattribution is caught, accepting the
adjudication load that follows: the cost of an extra worksheet is minutes, the
cost of a fabricated citation reaching a court is the office's credibility.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass
from pathlib import Path

from .semantic import overlap

# دون هذا العدد من المواد تكون المعايرة ضجيجًا لا قياسًا
MIN_ARTICLES = 150
# لا تُرفع العتبة فوق هذا الحد مهما قالت المعايرة: التداخل الموزون يتشبع،
# وعتبة قريبة من 1 تحيل كل شيء تقريبًا.
CEILING = 0.75
FLOOR = 0.25


@dataclass
class Calibration:
    """نتيجة المعايرة."""
    threshold: float
    articles: int
    samples: int
    # None حين تتعذّر القياس — لا NaN، فهي ليست JSON صالحة ولا يقرؤها غير بايثون
    miss_rate: float | None          # نسبة الإسناد المغلوط الذي يمر دون تحكيم
    adjudication_rate: float | None  # نسبة الإسناد السليم الذي يُحال للتحكيم
    reliable: bool
    note: str

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=2)


def _claim_from(words: list[str], rng: random.Random) -> str:
    """ادعاء يحاكي صياغة محامٍ: مقطع من المادة، لا نصها كاملًا.

    Pairing an article with its own full text would measure copying, not
    citing — and would calibrate a threshold no real draft could meet.
    """
    n = len(words)
    span = max(6, int(n * rng.uniform(0.45, 0.75)))
    start = rng.randint(0, max(0, n - span))
    chunk = words[start:start + span]
    # إسقاط بعض الكلمات: المحامي يعيد الصياغة ولا ينسخ
    keep = [w for w in chunk if rng.random() > 0.18]
    return " ".join(keep or chunk)


def calibrate(rows: list[tuple[str, str]], idf: dict[str, float], *,
              target_miss_rate: float = 0.05, samples: int = 600,
              seed: int = 20260903) -> Calibration:
    """يعيد العتبة المقيسة.

    ``rows`` is ``[(instrument_id, article_text), …]`` for verified articles.
    """
    rng = random.Random(seed)
    usable = [(iid, t) for iid, t in rows if len(t.split()) >= 12]
    n_articles = len(usable)

    if n_articles < 20:
        return Calibration(
            threshold=FLOOR, articles=n_articles, samples=0,
            miss_rate=None, adjudication_rate=None, reliable=False,
            note="المدونة أصغر من أن تُعاير. أبقِ العتبة عند الحد الأدنى "
                 "واستورد التشريعات الناقصة أولًا.")

    by_instrument: dict[str, list[int]] = {}
    for i, (iid, _) in enumerate(usable):
        by_instrument.setdefault(iid, []).append(i)

    pos: list[float] = []
    neg: list[float] = []
    for _ in range(samples):
        i = rng.randrange(n_articles)
        iid, text = usable[i]
        claim = _claim_from(text.split(), rng)
        pos.append(overlap(claim, text, idf))

        # الخلط المرجّح: المادة المجاورة في نفس التشريع هي الغلط الواقعي
        siblings = [j for j in by_instrument.get(iid, []) if j != i]
        if siblings and rng.random() < 0.6:
            j = min(siblings, key=lambda j: abs(j - i) + rng.random())
        else:
            j = rng.randrange(n_articles)
            if j == i:
                continue
        neg.append(overlap(claim, usable[j][1], idf))

    if not neg:
        return Calibration(FLOOR, n_articles, len(pos), None, None, False,
                           "تعذّر بناء أزواج سالبة.")

    # العتبة عند مئين السالبة المقابل لمعدل الفوات المستهدف: ما فوقها من
    # الإسناد المغلوط هو ما سيمر دون تحكيم.
    neg.sort()
    idx = min(len(neg) - 1, int(round((1 - target_miss_rate) * (len(neg) - 1))))
    raw = neg[idx]
    threshold = round(min(CEILING, max(FLOOR, raw)), 2)

    miss = sum(1 for x in neg if x >= threshold) / len(neg)
    adjud = sum(1 for x in pos if x < threshold) / len(pos) if pos else 0.0
    reliable = n_articles >= MIN_ARTICLES

    note = ("معايرة موثوقة." if reliable else
            f"المدونة صغيرة ({n_articles} مادة، والموصى به {MIN_ARTICLES}+). "
            f"العتبة إرشادية — أعد المعايرة بعد توسيع المدونة.")
    return Calibration(threshold, n_articles, len(pos), round(miss, 3),
                       round(adjud, 3), reliable, note)


def load(path: str | Path) -> float | None:
    """قراءة العتبة المُعايَرة إن وُجدت."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return float(json.loads(p.read_text(encoding="utf-8"))["threshold"])
    except (ValueError, KeyError, TypeError):
        return None
