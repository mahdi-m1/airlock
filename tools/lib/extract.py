"""استخراج النص من الملفات الرسمية — HTML ونص عادي، بمكتبة قياسية فقط.

Text extraction from official files. Stdlib only (html.parser) so the office
runs on an isolated box with no package installs.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

_DROP = {"script", "style", "head", "noscript", "svg", "nav", "footer", "header", "form"}
_BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6",
          "section", "article", "table", "td", "blockquote"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _DROP:
            self._skip += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in _DROP:
            self._skip = max(0, self._skip - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        out = "".join(self.parts)
        out = re.sub(r"[ \t]+", " ", out)
        return re.sub(r"\n\s*\n\s*\n+", "\n\n", out).strip()


def from_html(html: str) -> tuple[str, str]:
    """يعيد (النص، عنوان الصفحة)."""
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:
        pass  # محللات HTML المتساهلة قد تعترض على صفحات حكومية قديمة
    return p.text(), p.title.strip()


def from_file(path: str | Path) -> tuple[str, str]:
    """استخراج النص من ملف مُجهَّز. يعيد (النص، العنوان المستنتج)."""
    path = Path(path)
    raw = path.read_bytes()
    # ترميزات شائعة في الوثائق الحكومية العربية
    for enc in ("utf-8", "utf-8-sig", "windows-1256", "cp1256"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    if path.suffix.lower() in {".html", ".htm", ".xhtml"} or "<html" in text[:2000].lower():
        return from_html(text)
    return text.strip(), ""


SUPPORTED_SUFFIXES = (".html", ".htm", ".xhtml", ".txt", ".md")


def unsupported_reason(path: Path) -> str | None:
    """سبب عدم دعم الملف، أو None إذا كان مدعومًا."""
    if path.suffix.lower() == ".pdf":
        return ("ملفات PDF غير مدعومة بالمكتبة القياسية. حوّله إلى نص أولًا:\n"
                f"      pdftotext -enc UTF-8 -layout '{path}' '{path.with_suffix('.txt')}'")
    if path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return f"امتداد غير مدعوم ({path.suffix}) — المدعوم: {', '.join(SUPPORTED_SUFFIXES)}"
    return None
