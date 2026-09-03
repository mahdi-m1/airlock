"""المدونة القانونية المحلية — تخزين واسترجاع.

Local legal corpus: a SQLite store of official Bahraini legislation, segmented
into articles. This is the ONLY thing agents may cite. Nothing here is fetched
at query time — the corpus is built once by `tools/ingest`, and every search is
a local read with zero network.

Token economics: `search()` returns article snippets, never whole statutes.
That is what keeps a legal-research turn at hundreds of tokens instead of tens
of thousands.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .arabic import normalize, stem_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS instruments (
    id            TEXT PRIMARY KEY,   -- law:36/2012
    key           TEXT NOT NULL,      -- labour-private-sector
    type          TEXT NOT NULL,
    number        TEXT NOT NULL,
    year          TEXT NOT NULL,
    title         TEXT NOT NULL,
    source_url    TEXT,
    source_domain TEXT,
    retrieved_at  TEXT NOT NULL,
    sha256        TEXT NOT NULL,
    verified      INTEGER NOT NULL DEFAULT 0,
    title_match   REAL,
    gazette_issue TEXT,
    gazette_date  TEXT,
    amendments    TEXT NOT NULL DEFAULT '[]',
    consolidated  INTEGER NOT NULL DEFAULT 0,
    source_tier   TEXT,
    practice_areas TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS articles (
    instrument_id TEXT NOT NULL REFERENCES instruments(id) ON DELETE CASCADE,
    article_key   TEXT NOT NULL,
    number        TEXT NOT NULL,
    bis           INTEGER NOT NULL DEFAULT 0,
    label         TEXT NOT NULL,
    text          TEXT NOT NULL,
    PRIMARY KEY (instrument_id, article_key)
);
CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(
    body, instrument_id UNINDEXED, article_key UNINDEXED, tokenize='unicode61'
);
CREATE INDEX IF NOT EXISTS idx_articles_instrument ON articles(instrument_id);
"""

# أعمدة أُضيفت بعد الإصدار الأول من المخزن.
#
# `CREATE TABLE IF NOT EXISTS` لا يمسّ جدولًا قائمًا، فمدونة بُنيت بنسخة أقدم
# تبقى بلا هذه الأعمدة، ولا يظهر ذلك إلا حين يسقط أول استعلام يلمسها برسالة
# sqlite غامضة (`no such column`) في وجه من يبحث عن مادة. والمدونة تُبنى مرة
# وتُستعمل شهورًا، فالترحيل هو الحالة الطبيعية لا الاستثناء.
_ADDED_COLUMNS: dict[str, str] = {
    "title_match": "REAL",
    "gazette_issue": "TEXT",
    "gazette_date": "TEXT",
    "amendments": "TEXT NOT NULL DEFAULT '[]'",
    "consolidated": "INTEGER NOT NULL DEFAULT 0",
    "source_tier": "TEXT",
    "practice_areas": "TEXT NOT NULL DEFAULT '[]'",
}


def amendment_warning(inst) -> str | None:
    """تنبيه التعديلات غير المدمجة.

    أخطر عطب في المدونة، ولا تلتقطه أي بوابة: المادة موجودة ورقمها صحيح ونصها
    مطابق لما استُورد — لكنه النص الأصلي لا النافذ. والمحكمة تطبّق النافذ.
    """
    keys = inst.keys()
    if "amendments" not in keys:
        return None
    try:
        amends = json.loads(inst["amendments"] or "[]")
    except (ValueError, TypeError):
        return None
    if not amends or ("consolidated" in keys and inst["consolidated"]):
        return None
    names = "، ".join(f"{a.get('type', '?')} {a.get('number', '?')}/{a.get('year', '?')}"
                      for a in amends)
    return (f"نص أصلي غير مدمج التعديلات ({len(amends)}): {names} — "
            f"تحقق من المادة قبل الاستشهاد بها")


# رتبة المصدر: الجريدة وحدها ملزمة، وكل ما عداها — ولو كان جهة رسمية —
# مرجع ثانوي يُتحقق منه. هذا ما يجب أن يقرأه كاتب المذكرة مع كل استشهاد.
SOURCE_TIERS = {
    "gazette": "الجريدة الرسمية — المرجع الملزم",
    "primary": "هيئة التشريع — مرجع ثانوي رسمي، يُتحقق من الجريدة",
    "ministry": "جهة رسمية — مرجع ثانوي، يُتحقق من الجريدة",
    "authority": "جهة رسمية — مرجع ثانوي، يُتحقق من الجريدة",
    "legislature": "مجلس النواب — مرجع ثانوي، يُتحقق من الجريدة",
    "portal": "بوابة حكومية — مرجع ثانوي، يُتحقق من الجريدة",
}


def _col(inst, name):
    return (inst[name] if name in inst.keys() else None) or ""


def gazette_ref(inst) -> str | None:
    """مرجع الجريدة الرسمية كما يُكتب في المذكرة."""
    issue, date = _col(inst, "gazette_issue"), _col(inst, "gazette_date")
    if not issue and not date:
        return None
    parts = []
    if issue:
        parts.append(f"الجريدة الرسمية عدد ({issue})")
    if date:
        parts.append(f"بتاريخ {date}")
    return " ".join(parts)


def provenance_line(inst) -> str | None:
    """سطر التوثيق الكامل: المصدر ورتبته وتاريخ الوصول.

    ما يجب تسجيله مع كل استشهاد: من أين جاء النص، وهل هو الجريدة نفسها أم
    مرجع ثانوي رسمي، ومتى استُرجع — فالنسخة الإلكترونية قد تتغير بعد ذلك.
    """
    tier = _col(inst, "source_tier")
    when = _col(inst, "retrieved_at")[:10]
    parts = []
    if tier:
        parts.append(SOURCE_TIERS.get(tier, tier))
    if when:
        parts.append(f"استُرجع {when}")
    return " · ".join(parts) or None


@dataclass
class Hit:
    """نتيجة بحث — مقطع مادة مع إسنادها الكامل."""
    instrument_id: str
    instrument_title: str
    article_key: str
    label: str
    text: str
    marker: str
    source_url: str | None
    verified: bool
    gazette: str | None = None
    provenance: str | None = None
    amendment_note: str | None = None
    score: float = 0.0

    def snippet(self, max_chars: int = 700) -> str:
        t = self.text
        return t if len(t) <= max_chars else t[:max_chars].rsplit(" ", 1)[0] + " …"


class Corpus:
    """واجهة المدونة. للقراءة افتراضيًا؛ الكتابة للاستيراد فقط."""

    def __init__(self, db_path: str | Path, *, write: bool = False):
        self.path = Path(db_path)
        if write:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        elif not self.path.exists():
            raise FileNotFoundError(
                f"المدونة القانونية غير موجودة: {self.path}\n"
                "شغّل الاستيراد أولًا:  python3 tools/ingest/ingest.py --help"
            )
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        if write:
            self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> list[str]:
        """إضافة الأعمدة الناقصة في مدونة بُنيت بنسخة أقدم."""
        try:
            have = {r["name"] for r in self.db.execute("PRAGMA table_info(instruments)")}
        except sqlite3.DatabaseError:
            return []
        if not have:                      # مدونة جديدة تمامًا — لا شيء يُرحَّل
            return []
        added = []
        for name, decl in _ADDED_COLUMNS.items():
            if name in have:
                continue
            try:
                self.db.execute(f"ALTER TABLE instruments ADD COLUMN {name} {decl}")
            except sqlite3.OperationalError as exc:
                raise sqlite3.OperationalError(
                    f"المدونة في {self.path} بُنيت بنسخة أقدم وينقصها العمود "
                    f"«{name}»، وتعذّر ترحيلها ({exc}).\n"
                    f"أعد بناءها:  python3 scripts/build-corpus.py") from exc
            added.append(name)
        if added:
            self.db.commit()
        return added

    # ── الكتابة (الاستيراد) ───────────────────────────────────────────
    def put_instrument(self, *, id: str, key: str, type: str, number: str, year: str,
                       title: str, source_url: str | None, source_domain: str | None,
                       sha256: str, verified: bool, title_match: float | None,
                       practice_areas: list[str], gazette_issue: str | None = None,
                       gazette_date: str | None = None,
                       amendments: list[dict] | None = None,
                       consolidated: bool = False,
                       source_tier: str | None = None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO instruments (id,key,type,number,year,title,"
            "source_url,source_domain,retrieved_at,sha256,verified,title_match,"
            "gazette_issue,gazette_date,amendments,consolidated,source_tier,"
            "practice_areas)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (id, key, type, number, year, normalize(title), source_url, source_domain,
             datetime.now(timezone.utc).isoformat(timespec="seconds"), sha256,
             int(verified), title_match, gazette_issue or None, gazette_date or None,
             json.dumps(amendments or [], ensure_ascii=False), int(consolidated),
             source_tier, json.dumps(practice_areas, ensure_ascii=False)),
        )

    def put_articles(self, instrument_id: str, articles: list[dict]) -> int:
        self.db.execute("DELETE FROM articles WHERE instrument_id=?", (instrument_id,))
        self.db.execute("DELETE FROM articles_fts WHERE instrument_id=?", (instrument_id,))
        rows = [(instrument_id, a["key"], a["number"], int(a["bis"]), a["label"], a["text"])
                for a in articles]
        self.db.executemany(
            "INSERT OR REPLACE INTO articles (instrument_id,article_key,number,bis,label,text)"
            " VALUES (?,?,?,?,?,?)", rows)
        self.db.executemany(
            "INSERT INTO articles_fts (body,instrument_id,article_key) VALUES (?,?,?)",
            [(stem_text(f"{a['label']} {a['text']}"), instrument_id, a["key"]) for a in articles])
        return len(rows)

    def commit(self) -> None:
        self.db.commit()

    # ── القراءة ───────────────────────────────────────────────────────
    def instrument(self, instrument_id: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM instruments WHERE id=?", (instrument_id,)).fetchone()

    def article(self, instrument_id: str, article_key: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM articles WHERE instrument_id=? AND article_key=?",
            (instrument_id, article_key)).fetchone()

    def resolve(self, instrument_id: str, article_key: str | None) -> tuple[bool, str]:
        """هل يُحل الاستشهاد؟ يعيد (نجاح، سبب الفشل بالعربية)."""
        inst = self.instrument(instrument_id)
        if inst is None:
            return False, f"التشريع «{instrument_id}» غير موجود في المدونة المحلية"
        if not inst["verified"]:
            return False, f"التشريع «{inst['title']}» مستورد لكنه غير مُتحقق منه"
        if article_key is None:
            return True, ""
        if self.article(instrument_id, article_key) is None:
            return False, f"المادة ({article_key}) غير موجودة في «{inst['title']}»"
        return True, ""

    def search(self, query: str, *, practice_areas: list[str] | None = None,
               instruments: list[str] | None = None, limit: int = 8) -> list[Hit]:
        """بحث نصي كامل يعيد مقاطع المواد المطابقة فقط."""
        terms = [t for t in stem_text(query).split() if len(t) > 1]
        if not terms:
            return []
        # بادئة (term*) تلتقط بقية التصريفات؛ التنصيص يُبطل صيغة FTS الخاصة.
        # bm25 يرتّب، والمطابقة OR تتسامح مع اختلاف الصياغة.
        fts_query = " OR ".join(f'"{t}"*' for t in terms)
        sql = ("SELECT f.instrument_id, f.article_key, bm25(articles_fts) AS score "
               "FROM articles_fts f WHERE articles_fts MATCH ? ")
        params: list = [fts_query]
        if instruments:
            sql += f"AND f.instrument_id IN ({','.join('?' * len(instruments))}) "
            params += instruments
        sql += "ORDER BY score LIMIT ?"
        params.append(limit * 4)

        hits: list[Hit] = []
        seen: set[tuple[str, str]] = set()
        for row in self.db.execute(sql, params):
            inst = self.instrument(row["instrument_id"])
            art = self.article(row["instrument_id"], row["article_key"])
            if inst is None or art is None or not inst["verified"]:
                continue
            if practice_areas:
                areas = set(json.loads(inst["practice_areas"]))
                if areas and not areas & set(practice_areas):
                    continue
            k = (inst["id"], art["article_key"])
            if k in seen:
                continue
            seen.add(k)
            hits.append(Hit(
                instrument_id=inst["id"],
                instrument_title=inst["title"],
                article_key=art["article_key"],
                label=art["label"],
                text=art["text"],
                marker=f"⟦BH:{inst['type']}:{inst['number']}/{inst['year']}:م{art['number']}"
                       f"{'مكرر' if art['bis'] else ''}⟧",
                source_url=inst["source_url"],
                verified=bool(inst["verified"]),
                gazette=gazette_ref(inst),
                provenance=provenance_line(inst),
                amendment_note=amendment_warning(inst),
                score=-float(row["score"]),
            ))
            if len(hits) >= limit:
                break
        return hits

    def term_idf(self) -> dict[str, float]:
        """وزن ندرة كل مصطلح في المدونة (IDF) — لقياس التداخل الدلالي.

        Boilerplate that appears in most provisions («العامل»، «يستحق»،
        «أحكام») must not make an unrelated article look supportive. Rarity
        weighting is what separates a claim's distinctive terms from the
        vocabulary every labour article shares.
        """
        import math

        from .arabic import fold, stem
        df: dict[str, int] = {}
        total = 0
        for row in self.db.execute("SELECT a.text FROM articles a "
                                   "JOIN instruments i ON i.id=a.instrument_id "
                                   "WHERE i.verified=1"):
            total += 1
            for t in {stem(w) for w in fold(row["text"]).split() if len(w) > 2}:
                df[t] = df.get(t, 0) + 1
        if not total:
            return {}
        return {t: math.log((total + 1) / (n + 0.5)) for t, n in df.items()}

    def stats(self) -> dict:
        q = lambda s: self.db.execute(s).fetchone()[0]  # noqa: E731
        oldest = self.db.execute(
            "SELECT MIN(retrieved_at) FROM instruments WHERE verified=1").fetchone()[0]
        return {
            "instruments": q("SELECT COUNT(*) FROM instruments"),
            "verified": q("SELECT COUNT(*) FROM instruments WHERE verified=1"),
            "articles": q("SELECT COUNT(*) FROM articles"),
            "unconsolidated": q(
                "SELECT COUNT(*) FROM instruments WHERE verified=1 "
                "AND consolidated=0 AND amendments NOT IN ('[]','')"),
            "oldest_retrieved_at": oldest,
        }

    def export_jsonl(self, path: str | Path) -> int:
        """تصدير المدونة كسجلات JSONL — للتدقيق والنسخ الاحتياطي المحلي."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        n = 0
        with path.open("w", encoding="utf-8") as fh:
            for inst in self.db.execute("SELECT * FROM instruments ORDER BY id"):
                for art in self.db.execute(
                        "SELECT * FROM articles WHERE instrument_id=? ORDER BY CAST(number AS INTEGER)",
                        (inst["id"],)):
                    fh.write(json.dumps({
                        "instrument_id": inst["id"], "title": inst["title"],
                        "type": inst["type"], "number": inst["number"], "year": inst["year"],
                        "article_key": art["article_key"], "label": art["label"],
                        "text": art["text"], "source_url": inst["source_url"],
                        "retrieved_at": inst["retrieved_at"], "sha256": inst["sha256"],
                        "verified": bool(inst["verified"]),
                    }, ensure_ascii=False) + "\n")
                    n += 1
        return n

    def close(self) -> None:
        self.db.close()
