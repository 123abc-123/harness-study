"""Versioned section-oriented JSON adapter and SQLite record store.

Only this adapter knows the input JSON shape. The harness uses tools, not JSON paths.
"""

from collections import Counter
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3

from .json_stream import iter_document


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class NestedJSONAdapter:
    """Schema v1: stable_key is a semantic identity shared across revisions."""

    def read(self, path: Path):
        # Two bounded passes also support metadata appearing AFTER the sections array.
        metadata = {key: value for kind, key, value in iter_document(path)
                    if kind == "field" and key in ("schema_version", "standard", "version", "provenance")}
        def chapters():
            for kind, _, value in iter_document(path):
                if kind == "section":
                    yield value
        return metadata, chapters()

    def records(self, sections):
        def walk(section, pointer, parent=""):
            key = section["stable_key"]
            if not isinstance(key, str) or not key:
                raise ValueError("Every section needs a nonempty stable_key")
            body = {k: v for k, v in section.items()
                    if k not in ("subsections", "entities", "relations", "stable_key")}
            body["parent_key"] = parent
            yield "section", key, key, pointer, body
            for group, kind in (("entities", "entity"), ("relations", "relation")):
                for index, record in enumerate(section.get(group, [])):
                    record_key = record["stable_key"]
                    if not isinstance(record_key, str) or not record_key:
                        raise ValueError("Every entity/relation needs a stable_key")
                    record_body = {k: v for k, v in record.items() if k != "stable_key"}
                    record_body["section_key"] = key
                    yield kind, record_key, key, f"{pointer}/{group}/{index}", record_body
            for index, child in enumerate(section.get("subsections", [])):
                yield from walk(child, f"{pointer}/subsections/{index}", key)

        for index, section in enumerate(sections):
            yield from walk(section, f"/sections/{index}")


class KGStore:
    def __init__(self, database: Path, adapter=None):
        self.database = database
        self.adapter = adapter or NestedJSONAdapter()
        database.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS versions(
                    version TEXT PRIMARY KEY, standard TEXT NOT NULL,
                    source TEXT NOT NULL, sha256 TEXT NOT NULL, provenance TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS records(
                    version TEXT NOT NULL, kind TEXT NOT NULL, key TEXT NOT NULL,
                    section_key TEXT NOT NULL, pointer TEXT NOT NULL,
                    body TEXT NOT NULL, digest TEXT NOT NULL, search_text TEXT NOT NULL,
                    PRIMARY KEY(version, kind, key));
                CREATE INDEX IF NOT EXISTS records_section ON records(version, section_key);
                CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(
                    version UNINDEXED, kind UNINDEXED, key UNINDEXED, text);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def import_file(self, path: Path) -> dict:
        metadata, sections = self.adapter.read(path)
        if metadata.get("schema_version") != 1:
            raise ValueError("Expected schema_version=1")
        standard, version = metadata.get("standard"), metadata.get("version")
        if not isinstance(standard, str) or not standard or not isinstance(version, str) or not version:
            raise ValueError("standard and version must be nonempty strings")
        digest = file_hash(path)
        count = 0
        with self.connect() as db:
            previous = db.execute("SELECT * FROM versions WHERE version=?", (version,)).fetchone()
            if previous:
                if previous["sha256"] == digest:
                    return {"version": version, "already_imported": True}
                raise ValueError("Version already exists with different content; use a new snapshot/version")
            db.execute("INSERT INTO versions VALUES(?,?,?,?,?)",
                       (version, standard, path.name, digest, encode(metadata.get("provenance") or {})))
            for kind, key, section_key, pointer, body in self.adapter.records(sections):
                text = encode(body)
                # Sources affect provenance, but not semantic equality of otherwise identical records.
                semantic = encode({k: v for k, v in body.items() if k != "source"})
                db.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?,?)",
                           (version, kind, key, section_key, pointer, text,
                            hashlib.sha256(semantic.encode()).hexdigest(), text.casefold()))
                db.execute("INSERT INTO record_fts VALUES(?,?,?,?)", (version, kind, key, text))
                count += 1
            if not count:
                raise ValueError("Input has no sections")
            # Dangling edges are a schema failure, not usable evidence.
            for row in db.execute("SELECT body FROM records WHERE version=? AND kind='relation'", (version,)):
                relation = json.loads(row["body"])
                for side in ("source_id", "target_id"):
                    target = relation.get(side)
                    if not target or not db.execute(
                        "SELECT 1 FROM records WHERE version=? AND kind='entity' AND key=?",
                        (version, target)
                    ).fetchone():
                        raise ValueError(f"Relation has missing or dangling {side}")
        return {"version": version, "records": count, "sha256": digest}

    def list_versions(self) -> dict:
        """List imported JEDEC-like versions and provenance; no real standard data is bundled."""
        with self.connect() as db:
            return {"versions": [dict(row) for row in db.execute("SELECT * FROM versions ORDER BY version")]}

    def _require_version(self, db, version):
        row = db.execute("SELECT * FROM versions WHERE version=?", (version,)).fetchone()
        if row is None:
            raise ValueError(f"Unknown version: {version}")
        return row

    @staticmethod
    def _record(row):
        return {"version": row["version"], "kind": row["kind"], "key": row["key"],
                "pointer": row["pointer"], "body": json.loads(row["body"])}

    def search_kg(self, version: str, query: str, limit: int = 8) -> dict:
        """Search a pinned version by terms. Returns excerpts and identifiers, not exhaustive answers."""
        if not query.strip() or not 1 <= limit <= 30:
            raise ValueError("Nonempty query and limit 1..30 required")
        tokens = re.findall(r"[\w]+", query, flags=re.UNICODE)[:20]
        expression = " OR ".join('"' + token.replace('"', '""') + '"' for token in tokens)
        with self.connect() as db:
            self._require_version(db, version)
            rows = []
            if expression:
                rows = db.execute("""SELECT r.* FROM record_fts f JOIN records r
                    ON r.version=f.version AND r.kind=f.kind AND r.key=f.key
                    WHERE record_fts MATCH ? AND f.version=? ORDER BY rank LIMIT ?""",
                                  (expression, version, limit + 1)).fetchall()
            method = "fts5_terms"
            if not rows:
                method = "literal_substring_fallback"
                rows = db.execute("SELECT * FROM records WHERE version=? AND instr(search_text,?)>0 LIMIT ?",
                                  (version, query.casefold(), limit + 1)).fetchall()
            hits = [{"version": r["version"], "kind": r["kind"], "key": r["key"],
                     "pointer": r["pointer"], "excerpt": r["body"][:2400],
                     "excerpt_truncated": len(r["body"]) > 2400} for r in rows[:limit]]
        return {"hits": hits, "truncated": len(rows) > limit, "method": method,
                "note": "Keyword evidence retrieval, not semantic or exhaustive retrieval"}

    def get_record(self, version: str, kind: str, key: str, offset: int = 0, limit: int = 12000) -> dict:
        """Read a record body in character windows, with evidence pointer and owning section."""
        if offset < 0 or not 1 <= limit <= 32000:
            raise ValueError("Invalid window")
        with self.connect() as db:
            row = db.execute("SELECT * FROM records WHERE version=? AND kind=? AND key=?",
                             (version, kind, key)).fetchone()
            if row is None:
                raise ValueError("Record not found")
            return {"version": version, "kind": kind, "key": key, "pointer": row["pointer"],
                    "section_key": row["section_key"], "content": row["body"][offset:offset + limit],
                    "next_offset": offset + limit, "truncated": len(row["body"]) > offset + limit}

    def differences(self, old: str, new: str):
        """Exact stable-key alignment. Does not infer splits, merges or JEDEC semantic truth."""
        with self.connect() as db:
            a, b = self._require_version(db, old), self._require_version(db, new)
            if a["standard"] != b["standard"]:
                raise ValueError("Cannot compare different standards")
            keys = db.execute("""SELECT kind,key FROM records WHERE version=?
                UNION SELECT kind,key FROM records WHERE version=? ORDER BY kind,key""", (old, new))
            for entry in keys:
                before = db.execute("SELECT * FROM records WHERE version=? AND kind=? AND key=?",
                                    (old, entry["kind"], entry["key"])).fetchone()
                after = db.execute("SELECT * FROM records WHERE version=? AND kind=? AND key=?",
                                   (new, entry["kind"], entry["key"])).fetchone()
                if before and after and before["digest"] == after["digest"]:
                    continue
                change = "added" if before is None else "removed" if after is None else "modified"
                left = json.loads(before["body"]) if before else {}
                right = json.loads(after["body"]) if after else {}
                fields = [field for field in sorted(left.keys() | right.keys())
                          if field != "source" and (field not in left or field not in right or left[field] != right[field])]
                yield {"change": change, "kind": entry["kind"], "key": entry["key"],
                       "changed_fields": fields,
                       "before": self._record(before) if before else None,
                       "after": self._record(after) if after else None,
                       "alignment": "exact stable_key; dataset difference, verify against original standard"}

    def comparison_summary(self, old: str, new: str) -> dict:
        counts = Counter(item["change"] for item in self.differences(old, new))
        with self.connect() as db:
            sizes = {v: db.execute("SELECT COUNT(*) FROM records WHERE version=?", (v,)).fetchone()[0]
                     for v in (old, new)}
        return {"old": old, "new": new, "counts": dict(counts), "records": sizes,
                "alignment": "exact stable_key only", "scope": "all imported records",
                "warning": "Graph differences are not independently verified JEDEC changes"}

    def compare_versions(self, old: str, new: str, offset: int = 0, limit: int = 10) -> dict:
        """Page through exact-ID differences. Inspect both evidence sides before interpreting."""
        if offset < 0 or not 1 <= limit <= 30:
            raise ValueError("Invalid page")
        from itertools import islice
        page = list(islice(self.differences(old, new), offset, offset + limit + 1))
        return {"old": old, "new": new, "changes": page[:limit],
                "next_offset": offset + limit, "has_more": len(page) > limit}
