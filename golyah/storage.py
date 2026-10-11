from __future__ import annotations

import json
import sqlite3
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .models import StudyRecord, normalized, utc_now


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS dictionaries(
                    id INTEGER PRIMARY KEY, title TEXT NOT NULL UNIQUE,
                    revision TEXT NOT NULL, digest TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1, priority INTEGER NOT NULL DEFAULT 0,
                    metadata TEXT NOT NULL, count INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS entries(
                    id INTEGER PRIMARY KEY, dictionary_id INTEGER NOT NULL
                        REFERENCES dictionaries(id) ON DELETE CASCADE,
                    word TEXT NOT NULL, normalized TEXT NOT NULL, pos TEXT NOT NULL,
                    data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS entry_word ON entries(normalized, dictionary_id);
                CREATE TABLE IF NOT EXISTS forms(
                    dictionary_id INTEGER NOT NULL REFERENCES dictionaries(id) ON DELETE CASCADE,
                    form TEXT NOT NULL, lemma TEXT NOT NULL, pos TEXT NOT NULL, data TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS form_word ON forms(form, dictionary_id);
                CREATE TABLE IF NOT EXISTS records(
                    uid TEXT PRIMARY KEY, term TEXT NOT NULL, sentence TEXT NOT NULL,
                    status TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cache(key TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, data TEXT NOT NULL);
                PRAGMA user_version=1;
            """)
            # An additive index keeps older app versions and existing exports
            # compatible. Triggers also cover imports and writes by other instances.
            db.executescript("""
                CREATE TABLE IF NOT EXISTS record_summaries(
                    uid TEXT PRIMARY KEY REFERENCES records(uid) ON DELETE CASCADE,
                    term TEXT NOT NULL, sentence TEXT NOT NULL, status TEXT NOT NULL,
                    updated_at TEXT NOT NULL, translation TEXT NOT NULL, error TEXT NOT NULL,
                    destination TEXT NOT NULL, complete INTEGER NOT NULL, has_anki INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS summary_updated ON record_summaries(updated_at DESC);
                CREATE INDEX IF NOT EXISTS summary_status ON record_summaries(status,updated_at DESC);
            """)
            values = self._summary_values('NEW')
            db.executescript(f"""
                CREATE TRIGGER IF NOT EXISTS record_summary_insert AFTER INSERT ON records BEGIN
                    INSERT OR REPLACE INTO record_summaries SELECT {values};
                END;
                CREATE TRIGGER IF NOT EXISTS record_summary_update
                    AFTER UPDATE OF term,sentence,status,updated_at,data ON records BEGIN
                    INSERT OR REPLACE INTO record_summaries SELECT {values};
                END;
            """)
            db.execute(f"""INSERT INTO record_summaries SELECT {self._summary_values('r')}
                FROM records r WHERE NOT EXISTS(SELECT 1 FROM record_summaries s WHERE s.uid=r.uid)""")

    @staticmethod
    def _summary_values(prefix):
        return f"""{prefix}.uid,{prefix}.term,{prefix}.sentence,{prefix}.status,{prefix}.updated_at,
            COALESCE(json_extract({prefix}.data,'$.translation'),''),
            COALESCE(json_extract({prefix}.data,'$.error'),''),
            COALESCE(json_extract({prefix}.data,'$.destination'),'dictionary'),
            COALESCE(json_type({prefix}.data,'$.explain'),'null')='object' AND
                (trim({prefix}.sentence,char(9,10,11,12,13,28,29,30,31,32,133,160,5760,
                    8192,8193,8194,8195,8196,8197,8198,8199,8200,8201,8202,8232,8233,8239,8287,12288))=''
                    OR COALESCE(json_type({prefix}.data,'$.context'),'null')='object'),
            COALESCE(json_type({prefix}.data,'$.anki_note_id'),'null')<>'null' OR
                COALESCE(json_extract({prefix}.data,'$.anki_note_ids'),'{{}}')<>'{{}}'"""

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def setting(self, key: str, default=None):
        with self.connect() as db:
            row = db.execute("SELECT data FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))

    def cache_get(self, key: str):
        with self.connect() as db:
            row = db.execute("SELECT data FROM cache WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def cache_put(self, key: str, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES(?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def save_record(self, record: StudyRecord):
        if not record.term.strip():
            raise ValueError("Укажите слово или фразу.")
        record.updated_at = utc_now()
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)",
                       (record.uid, record.term, record.sentence, record.status, record.updated_at, record.model_dump_json()))

    def get_record(self, uid: str) -> StudyRecord | None:
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE uid=?", (uid,)).fetchone()
        return StudyRecord.model_validate_json(row[0]) if row else None

    def record_state(self, uid: str) -> dict | None:
        with self.connect() as db:
            row = db.execute('SELECT status,complete,has_anki FROM record_summaries WHERE uid=?', (uid,)).fetchone()
        return dict(row) if row else None

    def preferred_record_uid(self) -> str | None:
        with self.connect() as db:
            row = db.execute('SELECT uid FROM record_summaries ORDER BY complete DESC,updated_at DESC LIMIT 1').fetchone()
        return row[0] if row else None

    def records(self, query: str = "", drafts: bool = False) -> list[dict]:
        # Searching never reads or parses the much larger dictionary JSON.
        sql = 'SELECT uid,term,sentence,status,translation,error,destination FROM record_summaries'
        if drafts:
            sql += " WHERE status IN ('draft','pending_anki','preview')"
        sql += " ORDER BY updated_at DESC"
        with self.connect() as db:
            rows = db.execute(sql).fetchall()
        needle = normalized(query) if query else ''
        return [dict(row) for row in rows if not needle or needle in normalized(
            row['term'] + ' ' + row['sentence'] + ' ' + row['translation'])]

    def delete_record(self, uid: str):
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE uid=?", (uid,))

    def export_records(self, path: str | Path):
        with self.connect() as db:
            rows = db.execute("SELECT data FROM records ORDER BY updated_at").fetchall()
        payload = {"schemaVersion": 1, "kind": "golyah-study", "records": [json.loads(r[0]) for r in rows]}
        destination = Path(path)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=destination.parent,
                    prefix=destination.name + '.', suffix='.tmp', delete=False) as output:
                temporary = Path(output.name)
                json.dump(payload, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()

    def import_records(self, path: str | Path) -> int:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        if (not isinstance(payload, dict) or payload.get("schemaVersion") != 1
                or payload.get("kind") != "golyah-study"):
            raise ValueError("Ожидается экспорт личного Dictionary версии 1.")
        if not isinstance(payload.get('records'), list):
            raise ValueError('Поле records должно содержать список записей.')
        # Validate the entire file before replacing any existing record.
        records = [StudyRecord.model_validate(r) for r in payload["records"]]
        with self.connect() as db:
            for r in records:
                if not r.term.strip():
                    raise ValueError("Пустое слово в файле.")
                if r.status == "saved" and not r.complete:
                    r.status = "draft"
                db.execute("INSERT OR REPLACE INTO records VALUES(?,?,?,?,?,?)",
                           (r.uid, r.term, r.sentence, r.status, r.updated_at, r.model_dump_json()))
        return len(records)
