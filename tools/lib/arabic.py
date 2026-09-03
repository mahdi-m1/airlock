"""معالجة النصوص القانونية العربية — تطبيع وتقسيم إلى مواد.

Arabic legal-text handling: normalisation and segmentation into articles.
Standard library only, on purpose — the office must run on an isolated box.
"""
from __future__ import annotations

import re
import unicodedata

# ── الأرقام ───────────────────────────────────────────────────────────
# Arabic-Indic (٠-٩) and Extended Arabic-Indic (۰-۹) digits → ASCII.
_DIGIT_MAP = {ord("٠") + i: str(i) for i in range(10)}
_DIGIT_MAP.update({ord("۰") + i: str(i) for i in range(10)})

# ── تشكيل وعلامات ─────────────────────────────────────────────────────
# Arabic diacritics (harakat) and tatweel carry no lexical meaning here.
_TASHKEEL = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")

# أشكال الألف والياء والتاء المربوطة — توحيدها يرفع نسبة المطابقة
_ALEF_FORMS = re.compile(r"[إأآٱ]")
_TRANSLATE_LETTERS = str.maketrans({"ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})

# ── الأعداد الترتيبية العربية (للمواد المكتوبة بالحروف) ───────────────
ORDINALS: dict[str, int] = {
    "الأولى": 1, "الاولى": 1, "الأول": 1, "الاول": 1,
    "الثانية": 2, "الثاني": 2,
    "الثالثة": 3, "الثالث": 3,
    "الرابعة": 4, "الرابع": 4,
    "الخامسة": 5, "الخامس": 5,
    "السادسة": 6, "السادس": 6,
    "السابعة": 7, "السابع": 7,
    "الثامنة": 8, "الثامن": 8,
    "التاسعة": 9, "التاسع": 9,
    "العاشرة": 10, "العاشر": 10,
    "الحادية عشرة": 11, "الحادي عشر": 11,
    "الثانية عشرة": 12, "الثاني عشر": 12,
    "الثالثة عشرة": 13, "الثالث عشر": 13,
    "الرابعة عشرة": 14, "الرابع عشر": 14,
    "الخامسة عشرة": 15, "الخامس عشر": 15,
    "السادسة عشرة": 16, "السادس عشر": 16,
    "السابعة عشرة": 17, "السابع عشر": 17,
    "الثامنة عشرة": 18, "الثامن عشر": 18,
    "التاسعة عشرة": 19, "التاسع عشر": 19,
    "العشرون": 20, "العشرين": 20,
}
_ORDINAL_ALT = "|".join(sorted(map(re.escape, ORDINALS), key=len, reverse=True))


def normalize_digits(text: str) -> str:
    """توحيد الأرقام العربية والفارسية إلى أرقام لاتينية."""
    return text.translate(_DIGIT_MAP)


def strip_tashkeel(text: str) -> str:
    """إزالة التشكيل والتطويل."""
    return _TASHKEEL.sub("", text)


def normalize(text: str) -> str:
    """تطبيع كامل للعرض والتخزين: NFC + أرقام لاتينية + بلا تشكيل + مسافات موحدة."""
    text = unicodedata.normalize("NFC", text)
    text = strip_tashkeel(normalize_digits(text))
    text = text.replace(" ", " ").replace("‏", "").replace("‎", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fold(text: str) -> str:
    """تطبيع عدواني للمطابقة والبحث فقط (لا للعرض).

    Folds alef/ya/ta-marbuta variants so that «الشركة» matches «الشركه».
    """
    text = normalize(text).lower()
    text = _ALEF_FORMS.sub("ا", text)
    text = text.translate(_TRANSLATE_LETTERS)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


# ── تقسيم النص إلى مواد ───────────────────────────────────────────────
# يطابق: مادة (1) / المادة 1 / المادة رقم (١) / المادة (99 مكررًا) / المادة الأولى
_ARTICLE_HEAD = re.compile(
    r"(?:^|\n)[ \t]*"
    r"(?P<head>"
    r"(?:ال)?مادة"
    r"(?:\s*رقم)?"
    r"\s*"
    r"(?:"
    r"[(\[]?\s*(?P<num>\d+)\s*(?P<bis>مكرر(?:ات|ا|اً|ًا)?)?\s*[)\]]?"
    r"|"
    rf"(?P<ord>{_ORDINAL_ALT})"
    r")"
    r")"
    r"[ \t]*[:：.\-–—]?[ \t]*",
    re.UNICODE,
)


def article_label(number: str, bis: str | None = None) -> str:
    """صياغة عنوان المادة كما يُكتب في الوثائق."""
    return f"المادة ({number}{' مكرر' if bis else ''})"


def article_key(number: str, bis: str | None = None) -> str:
    """المفتاح الآلي للمادة داخل المدونة: 99 أو 99-مكرر."""
    return f"{number}-مكرر" if bis else str(number)


def segment_articles(text: str) -> list[dict]:
    """تقسيم نص تشريع إلى مواد.

    Returns a list of ``{"number", "bis", "key", "label", "text"}`` in document
    order. Text before the first article header (preamble, issuing decree) is
    not returned — it is not citable as an article.
    """
    text = normalize(text)
    matches = list(_ARTICLE_HEAD.finditer(text))
    if not matches:
        return []

    articles: list[dict] = []
    for i, m in enumerate(matches):
        if m.group("num"):
            number = m.group("num").lstrip("0") or "0"
            bis = m.group("bis")
        else:
            number = str(ORDINALS[m.group("ord")])
            bis = None

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end():end].strip()
        if not body:
            continue

        key = article_key(number, bis)
        # نص متكرر لنفس المفتاح: نبقي الأطول (بعض المصادر تكرر الفهرس قبل المتن)
        existing = next((a for a in articles if a["key"] == key), None)
        if existing:
            if len(body) > len(existing["text"]):
                existing["text"] = body
            continue

        articles.append({
            "number": number,
            "bis": bool(bis),
            "key": key,
            "label": article_label(number, bis),
            "text": body,
        })
    return articles


# ── تجذيع خفيف للبحث ──────────────────────────────────────────────────
# العربية لغة اشتقاقية: «الفصل التعسفي» و«فصلاً تعسفياً» جذعهما واحد.
# التجذيع هنا ليس صرفيًا دقيقًا — المطلوب **الاتساق** بين الفهرسة والاستعلام،
# لا الصحة اللغوية. يُطبَّق على الطرفين، فيتطابقان حتى لو كان الجذع غير قياسي.
_PREFIXES = ("والـ", "بال", "كال", "فال", "وال", "ال", "لل")
_SUFFIXES = ("اتها", "ياته", "اتهم", "ونها", "ات", "ون", "ين", "ان",
             "ها", "هم", "هن", "كم", "ية", "ه", "ي", "ا", "ه")
_MIN_STEM = 3


def stem(word: str) -> str:
    """تجذيع خفيف: إزالة أداة التعريف واللواحق الشائعة."""
    for p in _PREFIXES:
        if word.startswith(p) and len(word) - len(p) >= _MIN_STEM:
            word = word[len(p):]
            break
    for s in _SUFFIXES:
        if word.endswith(s) and len(word) - len(s) >= _MIN_STEM:
            word = word[: -len(s)]
            break
    return word


def stem_text(text: str) -> str:
    """طي + تجذيع كل كلمة — يُستعمل للفهرسة والاستعلام معًا."""
    return " ".join(stem(w) for w in fold(text).split())


def similarity(a: str, b: str) -> float:
    """تشابه تقريبي بين عنوانين (نسبة الكلمات المشتركة) — للتحقق من العناوين."""
    wa, wb = set(fold(a).split()), set(fold(b).split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)
