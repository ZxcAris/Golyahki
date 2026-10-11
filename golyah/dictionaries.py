from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any, Callable

import ijson

from .models import Entry, Example, Sense, normalized
from .storage import Storage


def text(node: Any, skip: set[str] | None = None, skip_semantic: set[str] | None = None) -> str:
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "".join(text(n, skip, skip_semantic) for n in node)
    if isinstance(node, dict):
        if node.get("tag") in (skip or set()):
            return ""
        if node.get("data", {}).get("content") in (skip_semantic or set()):
            return ""
        if node.get("tag") == "br":
            return "\n"
        return text(node.get("content", ""), skip, skip_semantic)
    return ""


def walk(node):
    if isinstance(node, dict):
        yield node
        yield from walk(node.get("content"))
    elif isinstance(node, list):
        for child in node:
            yield from walk(child)


def section(node, name: str):
    return [n for n in walk(node) if n.get("data", {}).get("content") == name]


def parse_wty(row: list, title: str) -> tuple[Entry | None, list[tuple[str, str]]]:
    if len(row) != 8 or not isinstance(row[0], str) or not isinstance(row[5], list):
        raise ValueError("Неверная запись term_bank Yomitan v3.")
    word, reading, tags, rules, _, glossary, _, _ = row
    if "non-lemma" in tags.split():
        links = []
        for item in glossary:
            if isinstance(item, list) and item and isinstance(item[0], str):
                links.append((item[0], rules))
        return None, links
    entry = Entry(word=word, lemma=word, pos=tags, dictionary=title, raw=row)
    for item in glossary:
        if isinstance(item, str):
            entry.senses.append(Sense(translation=item))
            continue
        if not isinstance(item, dict):
            continue
        root = item.get("content", item)
        for group in section(root, "glosses"):
            children = group.get("content", [])
            children = children if isinstance(children, list) else [children]
            for child in children:
                if not isinstance(child, dict):
                    continue
                translation = text(child, {"details"}).strip()
                examples = []
                for ex in section(child, "example-sentence"):
                    a, b = section(ex, "example-sentence-a"), section(ex, "example-sentence-b")
                    en = text(a[0]).strip() if a else ""
                    ru = text(b[0]).strip() if b else ""
                    if en:
                        examples.append(Example(en=en, ru=ru))
                if translation:
                    entry.senses.append(Sense(translation=translation, examples=examples))
        entry.etymology += "\n".join(text(s).strip() for s in section(root, "Etymology-content"))
        entry.synonyms += [text(s).strip() for s in section(root, "synonym-item")]
        entry.sources += [n["href"] for n in walk(root) if n.get("tag") == "a" and
                          str(n.get("href", "")).startswith(("https://", "http://"))]
        if not section(root, "glosses"):
            fallback = text(root).strip()
            if fallback:
                entry.senses.append(Sense(translation=fallback))
        known = {"preamble", "glosses", "synonyms", "backlink"}
        if section(root, "glosses"):
            entry.extra += text(root, skip_semantic=known).strip()
    entry.sources = list(dict.fromkeys(entry.sources))
    entry.synonyms = list(dict.fromkeys(s for s in entry.synonyms if s))
    return entry, []


class DictionaryService:
    def __init__(self, storage: Storage):
        self.storage = storage

    def list(self):
        with self.storage.connect() as db:
            return [dict(r) for r in db.execute(
                "SELECT id,title,revision,enabled,priority,count FROM dictionaries ORDER BY priority DESC,title")]

    def ensure_builtin(self):
        path = Path(__file__).parent / 'data' / 'spoken-en-ru.json'
        title = json.loads(path.read_text(encoding='utf-8'))['name']
        exists = any(item['title'] == title for item in self.list())
        result = self.import_file(path)
        if not exists:
            item = next(item for item in self.list() if item['title'] == title)
            self.configure(item['id'], True, -100)
        return result

    def import_file(self, path: str | Path, progress: Callable[[int], None] | None = None):
        path = Path(path)
        digest = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint = "parser-v2:" + digest.hexdigest()
        if path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                meta = json.loads(archive.read("index.json"))
                if meta.get("format") != 3 or not isinstance(meta.get("title"), str):
                    raise ValueError("Поддерживаются словари Yomitan версии 3.")
                names = sorted((n for n in archive.namelist() if re.fullmatch(r"term_bank_\d+\.json", n)),
                               key=lambda n: int(re.search(r"\d+", n).group()))
                if not names:
                    raise ValueError("В архиве отсутствуют term_bank.")
                def rows():
                    for name in names:
                        with archive.open(name) as stream:
                            for row in ijson.items(stream, "item", use_float=True):
                                yield parse_wty(row, meta["title"]), row
                return self._import(meta, fingerprint, rows(), progress)
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if (not isinstance(payload, dict) or payload.get("schemaVersion") != 1
                or payload.get("kind") != "golyah-dictionary"):
            raise ValueError("Ожидается ZIP Yomitan v3 или JSON golyah-dictionary версии 1.")
        if not isinstance(payload.get('name'), str) or not payload['name'].strip():
            raise ValueError('Укажите название словаря в поле name.')
        if not isinstance(payload.get('entries'), list):
            raise ValueError('Поле entries должно содержать список словарных статей.')
        meta = {"title": payload["name"], "revision": payload.get("revision", "1"),
                "attribution": payload.get("attribution", "")}
        entries = [Entry.model_validate(r) for r in payload["entries"]]
        def rows():
            for e in entries:
                if not e.word.strip():
                    raise ValueError("Пустое слово в словаре.")
                e.dictionary = meta["title"]
                yield (e, []), e.model_dump()
        return self._import(meta, fingerprint, rows(), progress)

    def _import(self, meta, fingerprint, rows, progress):
        count = 0
        if progress:
            progress(0)
        with self.storage.connect() as db:
            old = db.execute("SELECT * FROM dictionaries WHERE title=?", (meta["title"],)).fetchone()
            if old and old["digest"] == fingerprint:
                return {"title": meta["title"], "count": old["count"], "unchanged": True}
            if old:
                dictionary_id = old["id"]
                db.execute("DELETE FROM entries WHERE dictionary_id=?", (dictionary_id,))
                db.execute("DELETE FROM forms WHERE dictionary_id=?", (dictionary_id,))
                db.execute("UPDATE dictionaries SET revision=?,digest=?,metadata=? WHERE id=?",
                           (meta.get("revision", ""), fingerprint, json.dumps(meta), dictionary_id))
            else:
                dictionary_id = db.execute("INSERT INTO dictionaries(title,revision,digest,metadata) VALUES(?,?,?,?)",
                    (meta["title"], meta.get("revision", ""), fingerprint, json.dumps(meta))).lastrowid
            for (entry, forms), raw in rows:
                count += 1
                if entry:
                    db.execute("INSERT INTO entries(dictionary_id,word,normalized,pos,data) VALUES(?,?,?,?,?)",
                        (dictionary_id, entry.word, normalized(entry.word), entry.pos, entry.model_dump_json()))
                    for form in entry.forms:
                        db.execute("INSERT INTO forms VALUES(?,?,?,?,?)",
                            (dictionary_id, normalized(form), normalized(entry.word), entry.pos, "{}"))
                else:
                    for lemma, pos in forms:
                        db.execute("INSERT INTO forms VALUES(?,?,?,?,?)",
                            (dictionary_id, normalized(raw[0]), normalized(lemma), pos,
                             json.dumps(raw, ensure_ascii=False)))
                if progress and count % 1000 == 0:
                    progress(count)
            if progress:
                progress(count)
            db.execute("UPDATE dictionaries SET count=? WHERE id=?", (count, dictionary_id))
        return {"title": meta["title"], "count": count, "unchanged": False}

    def lookup(self, word: str) -> list[Entry]:
        query = normalized(word.strip().strip("*\"'.,!?;:()[]{}“”‘’"))
        with self.storage.connect() as db:
            rows = db.execute("""SELECT e.*,d.title,d.priority FROM entries e
                JOIN dictionaries d ON e.dictionary_id=d.id
                WHERE e.normalized=? AND d.enabled=1 ORDER BY d.priority DESC,e.id""", (query,)).fetchall()
            form_rows = db.execute("""SELECT e.*,d.title,d.priority FROM forms f
                JOIN entries e ON e.dictionary_id=f.dictionary_id AND e.normalized=f.lemma
                JOIN dictionaries d ON d.id=f.dictionary_id
                WHERE f.form=? AND d.enabled=1 AND (f.pos='' OR e.pos=f.pos)
                ORDER BY d.priority DESC,e.id""", (query,)).fetchall()
        seen, result = set(), []
        for row in list(rows) + list(form_rows):
            if row["id"] not in seen:
                seen.add(row["id"])
                result.append(Entry.model_validate_json(row["data"]))
        return result

    def configure(self, dictionary_id: int, enabled: bool, priority: int):
        with self.storage.connect() as db:
            db.execute("UPDATE dictionaries SET enabled=?,priority=? WHERE id=?",
                       (int(enabled), priority, dictionary_id))

    def delete(self, dictionary_id: int):
        with self.storage.connect() as db:
            db.execute("DELETE FROM dictionaries WHERE id=?", (dictionary_id,))
