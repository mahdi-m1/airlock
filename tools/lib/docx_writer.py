"""إصدار المذكرات والمرافعات والاستشارات بصيغة Word.

Writes Arabic legal documents as .docx, with the standard library only — no
dependency to install on an isolated machine, matching the reader in
`documents.py`.

اتجاه النص هو جوهر المسألة. Word لا يستنتج العربية من المحتوى: المستند يخرج
مكسورًا ما لم تُضبط ثلاثة أشياء صراحةً في كل فقرة وكل تشغيلة —

  * ``w:bidi``  على الفقرة، و``w:rtl`` على التشغيلة،
  * ``w:szCs`` لحجم الخط، لا ``w:sz`` وحده: العربية «كتابة مركّبة»
    (complex script) ولها في Word مقاسات وخطوط منفصلة عن اللاتينية،
  * ``w:rFonts w:cs`` لاسم الخط العربي، لا ``w:ascii`` وحده.

إغفال أيٍّ منها يُنتج ملفًا يُفتح ويبدو سليمًا في القائمة، ثم يظهر بمحاذاة
يسار وأرقام مقلوبة عند الطباعة — وهو أسوأ من ملف لا يُفتح.

الترقيم يُكتب حرفيًا («1.» في متن الفقرة) بدل قوائم Word التلقائية: طلبات
المرافعة وبنودها يجب ألا يُعاد ترقيمها إذا حُرّر المستند أو فُتح ببرنامج آخر.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# ── قوالب الحزمة ──────────────────────────────────────────────────────
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>
<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
</Relationships>"""

DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>
</Relationships>"""

# ‏rtlGutter يضع هامش التجليد يمينًا، وbidi يجعل اتجاه المستند كله من اليمين
SETTINGS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:settings xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:defaultTabStop w:val="720"/>
<w:themeFontLang w:val="ar-BH" w:bidi="ar-BH"/>
</w:settings>"""

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


@dataclass
class Style:
    """مظهر المستند."""
    font_cs: str = "Traditional Arabic"   # خط الكتابة المركّبة (العربية)
    font_ascii: str = "Times New Roman"   # اللاتينية والأرقام الغربية
    size_pt: float = 14.0
    heading_pt: float = 16.0
    title_pt: float = 18.0
    line_spacing: float = 1.5


def _styles_xml(st: Style) -> str:
    half = int(st.size_pt * 2)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles {W_NS}>
<w:docDefaults><w:rPrDefault><w:rPr>
<w:rFonts w:ascii="{esc(st.font_ascii)}" w:hAnsi="{esc(st.font_ascii)}" w:cs="{esc(st.font_cs)}"/>
<w:sz w:val="{half}"/><w:szCs w:val="{half}"/><w:rtl/>
<w:lang w:val="ar-BH" w:bidi="ar-BH"/>
</w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:bidi/>
<w:spacing w:line="{int(st.line_spacing * 240)}" w:lineRule="auto" w:after="120"/>
<w:jc w:val="both"/></w:pPr></w:pPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal">
<w:name w:val="Normal"/></w:style>
</w:styles>"""


def _core_xml(title: str, author: str) -> str:
    today = date.today().isoformat()
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
<dc:title>{esc(title)}</dc:title><dc:creator>{esc(author)}</dc:creator>
<cp:lastModifiedBy>{esc(author)}</cp:lastModifiedBy>
<dcterms:created xsi:type="dcterms:W3CDTF">{today}T00:00:00Z</dcterms:created>
</cp:coreProperties>"""


# ── بناء الفقرات ──────────────────────────────────────────────────────
def _run(text: str, st: Style, *, bold=False, size: float | None = None,
         color: str | None = None) -> str:
    """تشغيلة نصية. ``w:rtl`` و``w:szCs`` إلزاميان للعربية."""
    half = int((size or st.size_pt) * 2)
    props = [f'<w:rFonts w:ascii="{esc(st.font_ascii)}" w:hAnsi="{esc(st.font_ascii)}"'
             f' w:cs="{esc(st.font_cs)}"/>']
    if bold:
        props.append("<w:b/><w:bCs/>")
    if color:
        props.append(f'<w:color w:val="{color}"/>')
    props.append(f'<w:sz w:val="{half}"/><w:szCs w:val="{half}"/><w:rtl/>')
    return (f"<w:r><w:rPr>{''.join(props)}</w:rPr>"
            f'<w:t xml:space="preserve">{esc(text)}</w:t></w:r>')


_BOLD = re.compile(r"\*\*(.+?)\*\*")


def _runs(text: str, st: Style, **kw) -> str:
    """تفكيك **العريض** إلى تشغيلات."""
    out, pos = [], 0
    for m in _BOLD.finditer(text):
        if m.start() > pos:
            out.append(_run(text[pos:m.start()], st, **kw))
        out.append(_run(m.group(1), st, bold=True, **{k: v for k, v in kw.items()
                                                     if k != "bold"}))
        pos = m.end()
    if pos < len(text):
        out.append(_run(text[pos:], st, **kw))
    return "".join(out) or _run("", st, **kw)


def _para(content: str, *, align="both", indent_start=0, space_before=0,
          keep_next=False, border=False) -> str:
    """فقرة. ترتيب عناصر ``w:pPr`` يتبع تسلسل المخطط حرفيًا.

    OOXML يعرّف ``CT_PPr`` تسلسلًا لا مجموعة: keepNext ثم pBdr ثم bidi ثم
    spacing ثم ind ثم jc. الخروج عن الترتيب يجعل الملف غير قابل للتحميل
    أصلًا — لا مشوّه العرض بل مرفوضًا من الأساس.
    """
    props = []
    if keep_next:
        props.append("<w:keepNext/>")
    if border:
        props.append('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="4"'
                     ' w:color="999999"/></w:pBdr>')
    props.append("<w:bidi/>")
    if space_before:
        props.append(f'<w:spacing w:before="{space_before}" w:after="120"/>')
    if indent_start:
        props.append(f'<w:ind w:start="{indent_start}"/>')
    props.append(f'<w:jc w:val="{align}"/>')
    return f"<w:p><w:pPr>{''.join(props)}</w:pPr>{content}</w:p>"


def _page_break() -> str:
    return '<w:p><w:pPr><w:bidi/></w:pPr><w:r><w:br w:type="page"/></w:r></w:p>'


# ── تحليل Markdown ────────────────────────────────────────────────────
def parse_blocks(md: str) -> list[tuple[str, str]]:
    """تحويل Markdown إلى كتل. مجموعة فرعية تكفي وثائق المكتب."""
    blocks: list[tuple[str, str]] = []
    para: list[str] = []

    def flush():
        if para:
            blocks.append(("p", " ".join(para).strip()))
            para.clear()

    for raw in md.splitlines():
        line = raw.rstrip()
        s = line.strip()
        if not s:
            flush()
        elif s in ("---", "***", "___"):
            flush()
            blocks.append(("rule", ""))
        elif m := re.match(r"^(#{1,4})\s+(.*)$", s):
            flush()
            blocks.append((f"h{len(m.group(1))}", m.group(2).strip()))
        elif m := re.match(r"^(\d+)[.)]\s+(.*)$", s):
            flush()
            blocks.append(("num", f"{m.group(1)}. {m.group(2).strip()}"))
        elif m := re.match(r"^[-*•]\s+(.*)$", s):
            flush()
            blocks.append(("bul", m.group(1).strip()))
        elif s.startswith(">"):
            flush()
            blocks.append(("quote", s.lstrip("> ").strip()))
        elif s.startswith("|") and s.endswith("|"):
            flush()
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue                       # سطر الفاصل في الجداول
            blocks.append(("row", " — ".join(c for c in cells if c)))
        else:
            para.append(s)
    flush()
    return blocks


def _body(blocks: list[tuple[str, str]], st: Style) -> str:
    out: list[str] = []
    for kind, text in blocks:
        if kind == "h1":
            out.append(_para(_runs(text, st, bold=True, size=st.title_pt),
                             align="center", space_before=240, keep_next=True))
        elif kind in ("h2", "h3", "h4"):
            size = st.heading_pt if kind == "h2" else st.size_pt + 1
            out.append(_para(_runs(text, st, bold=True, size=size),
                             align="right", space_before=200, keep_next=True))
        elif kind == "num":
            out.append(_para(_runs(text, st), indent_start=340))
        elif kind == "bul":
            out.append(_para(_runs("• " + text, st), indent_start=340))
        elif kind == "quote":
            out.append(_para(_runs(text, st), indent_start=567))
        elif kind == "row":
            out.append(_para(_runs(text, st), indent_start=170))
        elif kind == "rule":
            out.append(_para("", border=True))
        else:
            out.append(_para(_runs(text, st)))
    return "".join(out)


def _banner(notice: str, st: Style) -> str:
    """ترويسة المسودة — بارزة ولا يمكن إغفالها."""
    return (_para(_runs(notice, st, bold=True, size=st.size_pt, color="B00000"),
                  align="center", border=True) + _para(""))


# ── الواجهة ───────────────────────────────────────────────────────────
def write_docx(markdown: str, out_path: str | Path, *, title: str,
               draft_notice: str | None = None, author: str = "مكتب الاستشارات القانونية",
               style: Style | None = None) -> Path:
    """كتابة وثيقة Word عربية من Markdown."""
    st = style or Style()
    body = (_banner(draft_notice, st) if draft_notice else "") + \
        _body(parse_blocks(markdown), st)

    # ‏A4 مع bidi على المقطع: اتجاه المستند نفسه لا الفقرات وحدها
    # ‏CT_SectPr تسلسل أيضًا: pgSz ثم pgMar ثم … ثم bidi
    sect = ('<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
            '<w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418"'
            ' w:header="709" w:footer="709" w:gutter="0"/>'
            '<w:bidi/><w:docGrid w:linePitch="360"/></w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                f'<w:document {W_NS}><w:body>{body}{sect}</w:body></w:document>')

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("docProps/core.xml", _core_xml(title, author))
        z.writestr("word/_rels/document.xml.rels", DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _styles_xml(st))
        z.writestr("word/settings.xml", SETTINGS)
    return out
