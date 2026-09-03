"""استخراج النص من مستندات العملاء — بأمان ودقة معلنة.

Safe text extraction from client documents. Two threat models meet here, and
both are real for a legal office:

**الأمان.** Case files arrive from outside: a contract PDF, a scanned letter, a
DOCX from the opposing party. These are untrusted input. Office formats are zip
archives of XML, so they carry zip bombs, path traversal, and entity-expansion
attacks; legacy formats carry macros. Extraction therefore never trusts a file
extension, never resolves an XML entity, never runs a macro, and never reaches
the network.

**الدقة.** A silently bad extraction is worse than a failed one. A scanned PDF
with no text layer yields an empty string; Arabic PDFs frequently yield glyph
presentation forms or letter-by-letter fragments that *look* like text and are
unusable. Either way the office would treat garbage as the client's facts — a
misread date or amount is as damaging as a fabricated citation. So every
extraction carries a measured confidence, and low confidence is quarantined
rather than passed on.

Stdlib-only for the formats that allow it (DOCX, ODT, RTF, HTML, text), so
those work on an isolated machine with nothing installed. PDF and images need a
backend; when none is present the tool says exactly what to install and fails
loudly instead of returning an empty string.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from .arabic import normalize
from .extract import from_html

# ── حدود الموارد ──────────────────────────────────────────────────────
MAX_FILE_BYTES = 80 * 1024 * 1024        # 80 ميغابايت
MAX_UNPACKED_BYTES = 400 * 1024 * 1024   # سقف الحجم بعد فك الضغط
MAX_ZIP_MEMBERS = 3_000
MAX_COMPRESSION_RATIO = 120              # قنبلة ضغط
MAX_TEXT_CHARS = 4_000_000
SUBPROCESS_TIMEOUT = 180


class DocumentError(Exception):
    """فشل استخراج — يُبلَّغ ولا يُبتلع."""


@dataclass
class Extraction:
    """نتيجة استخراج، بمصدرها وجودتها معلنتين."""
    text: str
    fmt: str
    method: str
    sha256: str
    bytes: int
    pages: int = 0
    confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False

    @property
    def ok(self) -> bool:
        """هل تُقبل هذه الاستخراجة كوقائع؟"""
        return self.confidence >= 0.6 and bool(self.text.strip())


# ── كشف الصيغة بالتوقيع لا بالامتداد ─────────────────────────────────
# الامتداد يتحكم فيه من أرسل الملف، فلا يصلح أساسًا لقرار أمني.
_MAGIC: list[tuple[bytes, str]] = [
    (b"%PDF-", "pdf"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpeg"),
    (b"GIF87a", "gif"), (b"GIF89a", "gif"),
    (b"II*\x00", "tiff"), (b"MM\x00*", "tiff"),
    (b"BM", "bmp"),
    (b"{\\rtf", "rtf"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "ole"),   # doc/xls قديم
]
IMAGE_FORMATS = {"png", "jpeg", "gif", "tiff", "bmp", "webp"}


def detect_format(path: Path) -> str:
    """الصيغة الحقيقية من محتوى الملف."""
    head = path.open("rb").read(4096)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "webp"
    for sig, fmt in _MAGIC:
        if head.startswith(sig):
            return fmt
    if head[:4] == b"PK\x03\x04":
        try:
            with zipfile.ZipFile(path) as z:
                names = set(z.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "content.xml" in names:
                return "odt"
            return "zip"
        except zipfile.BadZipFile:
            return "unknown"
    low = head[:512].lstrip().lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html") or b"<body" in low:
        return "html"
    return "text" if decode_text(head)[0] is not None else "unknown"


def decode_text(raw: bytes) -> tuple[str | None, str]:
    """فك ترميز بايتات نصية. يعيد (النص أو None، اسم الترميز).

    ترتيب المحاولات مقصود، والفحص بعدها ضروري: windows-1256 يقبل كل بايت
    تقريبًا، وUTF-16 بلا علامة ترتيب يفك أي بايتات عشوائية إلى محارف سليمة
    الشكل. بلا فحص المعقولية يمر الملف الثنائي كأنه نص، وتُبنى عليه «وقائع»
    من ضجيج — وهو أسوأ من رفض الملف.
    """
    encodings = ["utf-8-sig", "utf-8"]
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        encodings.insert(0, "utf-16")
    encodings.append("windows-1256")
    for enc in encodings:
        try:
            decoded = raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
        if _looks_textual(decoded[:8192]):
            return decoded, enc
    return None, ""


def _looks_textual(s: str) -> bool:
    """هل الناتج نص فعلًا أم بايتات فُكّ ترميزها بلا معنى؟

    فحصان: قلة محارف التحكّم، ثم أن تكون المحارف من كتابة متوقعة. الثاني هو
    ما يميّز نصًا حقيقيًا عن بايتات عشوائية فُكّت إلى محارف سليمة الشكل.
    """
    if not s:
        return False
    ctrl = sum(1 for c in s if unicodedata.category(c) == "Cc" and c not in "\t\n\r")
    if ctrl / len(s) > 0.05:
        return False
    plausible = sum(
        1 for c in s
        if c.isspace() or c.isdigit()
        or "؀" <= c <= "ۿ"            # عربي
        or "ݐ" <= c <= "ݿ"            # عربي موسّع
        or "ﭐ" <= c <= "﻿"            # أشكال العرض العربية
        or c.isascii() and (c.isprintable())    # لاتيني وترقيم
        or unicodedata.category(c).startswith("P"))
    return plausible / len(s) >= 0.70


# ── دفاعات أرشيف مضغوط ────────────────────────────────────────────────
def _safe_zip_read(path: Path, members: tuple[str, ...]) -> dict[str, bytes]:
    """قراءة أعضاء محددة من أرشيف مع دفاعات القنبلة والانفلات.

    Only the members we name are ever read, so a crafted archive cannot get an
    unexpected file opened. Names are still validated because an entry may
    declare an absolute path or `..` segments.
    """
    out: dict[str, bytes] = {}
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise DocumentError(
                f"الأرشيف يحوي {len(infos)} عنصرًا (الحد {MAX_ZIP_MEMBERS}) — رُفض")
        total = sum(i.file_size for i in infos)
        if total > MAX_UNPACKED_BYTES:
            raise DocumentError(
                f"حجم المحتوى بعد فك الضغط {total // 1048576} ميغابايت "
                f"يتجاوز الحد — رُفض كقنبلة ضغط محتملة")
        for i in infos:
            name = i.filename
            if name.startswith("/") or ".." in Path(name).parts or ":" in name[:3]:
                raise DocumentError(f"مسار خطر داخل الأرشيف: «{name}» — رُفض")
            if i.compress_size and i.file_size / max(i.compress_size, 1) > MAX_COMPRESSION_RATIO:
                raise DocumentError(
                    f"نسبة ضغط غير طبيعية في «{name}» — رُفض كقنبلة ضغط محتملة")
        for m in members:
            if m in z.namelist():
                out[m] = z.read(m)
    return out


# ── دفاعات XML ────────────────────────────────────────────────────────
_DTD = re.compile(rb"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)


def _guard_xml(data: bytes, what: str) -> None:
    """رفض أي DTD أو كيان معرَّف — بابا XXE وتفجّر الكيانات."""
    if _DTD.search(data[:200_000]):
        raise DocumentError(
            f"{what} يحوي تعريف DTD أو كيانات XML — رُفض. هذا نمط هجمات "
            f"الكيانات الخارجية (XXE) ولا حاجة له في مستند سليم.")


_TAG = re.compile(r"<[^>]+>")


def _xml_to_text(data: bytes, para_tags: tuple[str, ...],
                 break_tags: tuple[str, ...] = ()) -> str:
    """استخراج نص من XML مكتبي دون تحليل شجري.

    Regex rather than a parser is deliberate: no parser is invoked on hostile
    input at all, and office XML needs only text runs and paragraph breaks.
    """
    xml = data.decode("utf-8", errors="replace")
    for t in para_tags:
        xml = re.sub(rf"</{t}>", "\n", xml)
    for t in break_tags:
        xml = re.sub(rf"<{t}\b[^>]*/?>", "\n", xml)
    xml = re.sub(r"<[^>]*\bxml:space=\"preserve\"[^>]*>", "", xml)
    text = _TAG.sub("", xml)
    for ent, ch in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&apos;", "'"), ("&#8217;", "’")):
        text = text.replace(ent, ch)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ── مستخرجات لكل صيغة ─────────────────────────────────────────────────
def _extract_docx(path: Path) -> tuple[str, str]:
    parts = _safe_zip_read(path, ("word/document.xml", "word/footnotes.xml"))
    if "word/document.xml" not in parts:
        raise DocumentError("ملف DOCX بلا word/document.xml — تالف أو مزوّر")
    for name, data in parts.items():
        _guard_xml(data, f"«{name}»")
    text = _xml_to_text(parts["word/document.xml"], ("w:p",), ("w:br", "w:cr"))
    if foot := parts.get("word/footnotes.xml"):
        if ft := _xml_to_text(foot, ("w:p",)):
            text += "\n\n[الحواشي]\n" + ft
    return text, "docx/zip+xml (مكتبة قياسية)"


def _extract_odt(path: Path) -> tuple[str, str]:
    parts = _safe_zip_read(path, ("content.xml",))
    if "content.xml" not in parts:
        raise DocumentError("ملف ODT بلا content.xml — تالف أو مزوّر")
    _guard_xml(parts["content.xml"], "«content.xml»")
    return (_xml_to_text(parts["content.xml"], ("text:p", "text:h"), ("text:line-break",)),
            "odt/zip+xml (مكتبة قياسية)")


_RTF_CTRL = re.compile(r"\\\*?\\?[a-zA-Z]{1,32}(-?\d{1,10})?[ ]?")
_RTF_UNI = re.compile(r"\\u(-?\d+)\??")


def _extract_rtf(path: Path) -> tuple[str, str]:
    raw = path.read_bytes().decode("latin-1", errors="replace")
    raw = _RTF_UNI.sub(lambda m: chr(int(m.group(1)) % 65536), raw)
    raw = re.sub(r"\\'([0-9a-fA-F]{2})",
                 lambda m: bytes([int(m.group(1), 16)]).decode("windows-1256", "replace"), raw)
    for group in ("fonttbl", "colortbl", "stylesheet", "info", "pict"):
        raw = re.sub(rf"\{{\\{group}.*?\}}", " ", raw, flags=re.DOTALL)
    raw = raw.replace("\\par", "\n").replace("\\line", "\n")
    raw = _RTF_CTRL.sub(" ", raw)
    raw = raw.replace("{", " ").replace("}", " ")
    return re.sub(r"[ \t]{2,}", " ", raw).strip(), "rtf (مكتبة قياسية)"


def _run(cmd: list[str], what: str) -> str:
    """تشغيل أداة خارجية بلا صدفة، بمهلة، وببيئة بلا شبكة."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
                        "ALL_PROXY", "ANTHROPIC_API_KEY")}
    env["HOME"] = env.get("TMPDIR", "/tmp")
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=SUBPROCESS_TIMEOUT,
                           env=env, check=False)
    except subprocess.TimeoutExpired:
        raise DocumentError(f"{what}: تجاوزت المهلة ({SUBPROCESS_TIMEOUT}ث) — "
                            f"قد يكون الملف ضخمًا أو تالفًا")
    except FileNotFoundError:
        raise DocumentError(f"{what}: الأداة غير مثبّتة")
    if r.returncode != 0:
        raise DocumentError(f"{what}: فشل ({r.returncode}) — "
                            f"{r.stderr.decode(errors='replace')[:200]}")
    return r.stdout.decode("utf-8", errors="replace")


def _extract_pdf(path: Path) -> tuple[str, str, int]:
    """PDF عبر أول خلفية متاحة."""
    pages = 0
    if shutil.which("pdfinfo"):
        try:
            m = re.search(r"Pages:\s+(\d+)", _run(["pdfinfo", str(path)], "pdfinfo"))
            pages = int(m.group(1)) if m else 0
        except DocumentError:
            pass
    if shutil.which("pdftotext"):
        return (_run(["pdftotext", "-enc", "UTF-8", "-layout", "-q", str(path), "-"],
                     "pdftotext"), "pdftotext (poppler)", pages)
    try:
        import pypdf  # noqa: PLC0415
        r = pypdf.PdfReader(str(path))
        return ("\n\n".join((p.extract_text() or "") for p in r.pages),
                "pypdf", len(r.pages))
    except BaseException as exc:  # noqa: BLE001 — انظر التعليق أدناه
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        # فحص خلفية اختيارية لا يجوز أن يُسقط الأداة. حزمة مثبّتة مكسورة
        # الاعتماديات ترمي ما ليس ImportError: pypdf فوق cryptography معطوبة
        # ترمي PanicException من امتداد Rust — وهي ترث BaseException لا
        # Exception، فلا يلتقطها `except Exception`. النتيجة كانت انهيارًا
        # بأثر Rust في وجه من سأل «ما الخلفيات المثبّتة؟».
        pass
    raise DocumentError(
        "لا خلفية لقراءة PDF. ثبّت إحداها:\n"
        "      sudo apt install poppler-utils      # الأدق للعربية\n"
        "      pip install pypdf                   # بديل نقي بايثون")


def _extract_image(path: Path, lang: str = "ara+eng") -> tuple[str, str]:
    """صورة عبر التعرّف الضوئي — محليًا فقط."""
    if not shutil.which("tesseract"):
        raise DocumentError(
            "لا محرك تعرّف ضوئي. ثبّته مع الحزمة العربية:\n"
            "      sudo apt install tesseract-ocr tesseract-ocr-ara\n"
            "    (محلي بالكامل — لا يرسل الصورة إلى أي خدمة)")
    return (_run(["tesseract", str(path), "stdout", "-l", lang], "tesseract"),
            f"tesseract OCR ({lang})")


# ── قياس جودة النص العربي المستخرج ────────────────────────────────────
_PRESENTATION = re.compile(r"[\uFB50-\uFDFF\uFE70-\uFEFF]")
_ARABIC = re.compile(r"[\u0600-\u06FF]")


def assess(text: str, fmt: str, *, expect_arabic: bool = True) -> tuple[float, list[str]]:
    """ثقة الاستخراج وأسباب الشك.

    Arabic extraction fails in ways that still *look* like text, which is why
    emptiness alone is not the test:
      * glyph presentation forms instead of logical characters,
      * every letter split into its own token,
      * mojibake from a mis-guessed legacy encoding.
    Each of these produces confident-looking output the office would otherwise
    treat as the client's facts.
    """
    warnings: list[str] = []
    conf = 1.0
    stripped = text.strip()

    if not stripped:
        return 0.0, ["النص المستخرج فارغ — الملف صورة ممسوحة بلا طبقة نصية، "
                     "أو محمي، أو تالف"]
    if len(stripped) < 20:
        conf -= 0.4
        warnings.append(f"النص قصير جدًا ({len(stripped)} حرفًا) — استخراج ناقص غالبًا")

    letters = [c for c in text if c.isalpha()]
    if letters:
        ar_ratio = len(_ARABIC.findall(text)) / len(letters)
        if expect_arabic and ar_ratio < 0.25:
            conf -= 0.3
            warnings.append(
                f"نسبة الحروف العربية {ar_ratio:.0%} فقط — قد يكون الترميز خاطئًا "
                f"أو المستند بلغة أخرى")

    if (n := len(_PRESENTATION.findall(text))) > len(text) * 0.02:
        conf -= 0.25
        warnings.append(
            f"{n} حرفًا بأشكال العرض المتصلة بدل الحروف المنطقية — عطب شائع في "
            f"استخراج PDF العربي. طُبّع تلقائيًا، لكن راجع الترتيب والاتصال")

    if (n := text.count("\ufffd")) > 3:
        conf -= 0.3
        warnings.append(f"{n} حرف استبدال (�) — ترميز غير صحيح")

    words = [w for w in re.split(r"\s+", stripped) if w]
    if len(words) > 30:
        avg = sum(len(w) for w in words) / len(words)
        if avg < 2.2:
            conf -= 0.35
            warnings.append(
                f"متوسط طول الكلمة {avg:.1f} حرفًا — الحروف مفصولة عن بعضها، "
                f"وهو عطب متكرر في PDF العربي يجعل النص غير صالح للاعتماد")
        ws = sum(c.isspace() for c in text) / max(len(text), 1)
        if ws > 0.55:
            conf -= 0.2
            warnings.append(f"المسافات {ws:.0%} من النص — تخطيط مشوّه")

    if fmt in IMAGE_FORMATS:
        conf -= 0.15
        warnings.append(
            "المصدر صورة: التعرّف الضوئي على العربية غير موثوق في الأرقام "
            "والتواريخ والأسماء. قابِل كل رقم بالأصل قبل اعتماده واقعة")

    return max(0.0, round(conf, 2)), warnings


# ── الواجهة ───────────────────────────────────────────────────────────
def extract(path: str | Path, *, expect_arabic: bool = True,
            ocr_lang: str = "ara+eng") -> Extraction:
    """استخراج نص مستند بأمان، مع ثقة معلنة."""
    path = Path(path)
    if not path.is_file():
        raise DocumentError(f"ليس ملفًا: {path}")
    size = path.stat().st_size
    if size == 0:
        raise DocumentError("الملف فارغ")
    if size > MAX_FILE_BYTES:
        raise DocumentError(
            f"حجم الملف {size // 1048576} ميغابايت يتجاوز الحد "
            f"({MAX_FILE_BYTES // 1048576} ميغابايت)")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    fmt = detect_format(path)
    warnings: list[str] = []
    pages = 0

    declared = path.suffix.lower().lstrip(".")
    alias = {"jpg": "jpeg", "tif": "tiff", "htm": "html", "md": "text", "txt": "text"}
    if declared and alias.get(declared, declared) != fmt and fmt != "unknown":
        warnings.append(
            f"الامتداد «.{declared}» لا يطابق المحتوى الحقيقي ({fmt}) — "
            f"عولج بحسب محتواه لا امتداده")

    if fmt == "pdf":
        text, method, pages = _extract_pdf(path)
    elif fmt == "docx":
        text, method = _extract_docx(path)
    elif fmt == "odt":
        text, method = _extract_odt(path)
    elif fmt == "rtf":
        text, method = _extract_rtf(path)
    elif fmt == "html":
        decoded, _ = decode_text(path.read_bytes())
        text, _ = from_html(decoded or path.read_bytes().decode("utf-8", "replace"))
        method = "html (مكتبة قياسية)"
    elif fmt == "text":
        decoded, enc = decode_text(path.read_bytes())
        if decoded is None:
            raise DocumentError("تعذّر فك ترميز الملف كنص سليم")
        text, method = decoded, f"نص ({enc})"
    elif fmt in IMAGE_FORMATS:
        text, method = _extract_image(path, ocr_lang)
    elif fmt == "ole":
        raise DocumentError(
            "صيغة Office قديمة (.doc/.xls) قد تحوي وحدات ماكرو. لا تُفتح مباشرة.\n"
            "      حوّلها في بيئة معزولة ثم مرّر الناتج:\n"
            "      soffice --headless --safe-mode --convert-to docx <الملف>")
    elif fmt == "zip":
        raise DocumentError("أرشيف مضغوط — فُكّه ومرّر كل مستند على حدة")
    else:
        raise DocumentError(
            f"صيغة غير معروفة أو غير مدعومة. المدعوم: PDF، DOCX، ODT، RTF، "
            f"HTML، نص، وصور (PNG/JPEG/TIFF/GIF/BMP/WebP)")

    # أشكال العرض المتصلة تُطبَّع إلى حروف منطقية قبل أي معالجة لاحقة
    text = unicodedata.normalize("NFKC", text)
    text = normalize(text)

    truncated = len(text) > MAX_TEXT_CHARS
    if truncated:
        text = text[:MAX_TEXT_CHARS]
        warnings.append(f"قُطع النص عند {MAX_TEXT_CHARS} حرفًا")

    conf, quality_warnings = assess(text, fmt, expect_arabic=expect_arabic)
    return Extraction(text=text, fmt=fmt, method=method, sha256=digest, bytes=size,
                      pages=pages, confidence=conf,
                      warnings=warnings + quality_warnings, truncated=truncated)


def available_backends() -> dict[str, str | None]:
    """ما هو مثبّت فعلًا لكل صيغة تحتاج أداة خارجية."""
    have_pypdf = False
    try:
        import pypdf  # noqa: F401,PLC0415
        have_pypdf = True
    except BaseException as exc:  # noqa: BLE001 — انظر التعليق في _extract_pdf
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
    return {
        "pdf": ("pdftotext (poppler)" if shutil.which("pdftotext")
                else "pypdf" if have_pypdf else None),
        "ocr": f"tesseract" if shutil.which("tesseract") else None,
        "legacy_doc": "soffice" if shutil.which("soffice") else None,
    }
