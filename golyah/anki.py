from __future__ import annotations

import html
import re
import threading
import time
from contextlib import contextmanager
from functools import wraps

import httpx

from .models import StudyRecord
from .appearance import Appearance
from .card_builder import (CardBuilder, MODEL_NAMES, TEMPLATE_NAMES, MODES,
                           gap_fields, templates, render_template)

MODEL = "Screen Vocabulary"
# Keep the original fields in place so existing notes and review history survive upgrades.
LEGACY_FIELDS = ["UID", "Term", "Lemma", "Translation", "DefinitionEN", "Sentence",
                 "SentenceTranslation", "ContextExplanation", "Examples", "Source"]
FIELDS = LEGACY_FIELDS + ["UsageEN", "PartOfSpeech", "IPA", "Register",
                          "DictionaryDefinitionEN", "Synonyms", "Etymology", "Notes"]
BASE_CSS = """/* Golyahki vocabulary · v3 */
.card {
  --bg:#161922; --surface:#20242e; --text:#e8ebf3; --muted:#a4adbf;
  --accent:#b7c3ff; --soft:#2c3245; --line:#363d4e;
  font-family:"Segoe UI",Arial,sans-serif; font-size:18px; line-height:1.6;
  text-align:left; color:var(--text); background:var(--bg); margin:0; padding:24px 16px;
  overflow-wrap:anywhere; -webkit-text-size-adjust:100%;
}
.golyah { max-width:680px; margin:0 auto; }
.hero, .answer { background:var(--surface); border:1px solid var(--line); border-radius:20px; padding:28px; }
.brand { display:flex; align-items:center; justify-content:space-between; gap:12px;
  color:var(--muted); font-size:11px; font-weight:600; letter-spacing:1.8px; }
.brand-name { color:var(--accent); }
.term { margin:20px 0 8px; font-size:42px; line-height:1.2; font-weight:650; letter-spacing:-1px; }
.metadata { display:flex; align-items:center; flex-wrap:wrap; gap:8px; color:var(--muted); font-size:15px; }
.badge { display:inline-block; border-radius:7px; background:var(--soft); color:var(--accent);
  padding:2px 9px; font-size:12px; font-weight:600; letter-spacing:.15px; }
.ipa { font-family:"Segoe UI","Arial Unicode MS",sans-serif; }
.section-label { color:var(--muted); font-size:11px; font-weight:600; letter-spacing:1.4px;
  margin-bottom:8px; text-transform:uppercase; }
.sentence-block { border-top:1px solid var(--line); margin-top:22px; padding-top:20px; }
.sentence { font-size:20px; line-height:1.65; }
mark { color:var(--accent); background:var(--soft); border-radius:4px; padding:1px 3px; font-weight:600; }
.answer { margin-top:14px; }
.translation { color:var(--accent); font-size:30px; line-height:1.35; font-weight:650; }
.lemma { color:var(--muted); font-size:13px; margin-top:8px; }
.section { margin-top:24px; }
.context { background:var(--soft); border-radius:12px; padding:17px 19px; }
.context-meaning { font-size:16px; color:var(--muted); margin-top:10px; }
.examples { margin:0; padding:0; list-style:none; }
.example { border-left:3px solid var(--line); padding-left:15px; margin:16px 0; }
.example:first-child { margin-top:0; }
.example-ru { color:var(--muted); font-size:16px; margin-top:4px; }
.synonym { display:inline-block; margin:0 6px 6px 0; padding:3px 10px;
  background:var(--soft); border-radius:7px; color:var(--accent); font-size:15px; }
.details { border-top:1px solid var(--line); margin-top:24px; padding-top:15px; color:var(--muted); font-size:14px; }
.details summary { cursor:pointer; color:var(--muted); font-size:12px; font-weight:600; letter-spacing:.5px; }
.details-content { margin-top:12px; overflow-wrap:anywhere; }
.builder-block { margin-top:20px; }
.builder-block .term, .builder-block .details { margin-top:0; }
.gap { color:var(--accent); padding:0 5px; border-bottom:2px solid var(--accent); white-space:nowrap; }
@media (max-width:480px) {
  .card { padding:12px 8px; font-size:17px; }
  .hero, .answer { padding:22px 20px; border-radius:16px; }
  .term { font-size:36px; } .sentence { font-size:18px; } .translation { font-size:27px; }
}
"""
_default_templates = templates()
FRONT, BACK = _default_templates['Front'], _default_templates['Back']


def card_css(appearance: Appearance | None = None) -> str:
    a = appearance or Appearance()
    # All interpolation is validated; text fields cannot inject CSS or HTML here.
    rgb = [int(a.cardBackground[i:i+2], 16) for i in (1, 3, 5)]
    accent = [int(a.cardAccent[i:i+2], 16) for i in (1, 3, 5)]
    soft = "#" + "".join(f"{round(c * .88 + ac * .12):02x}" for c, ac in zip(rgb, accent))
    background = (f"linear-gradient(145deg,{a.cardBackground},{a.cardBackgroundEnd})"
                  if a.cardGradient else a.cardBackground)
    return BASE_CSS + f"""
.card, .card.nightMode, .nightMode .card, .card.night_mode, .night_mode .card {{
  --bg:#161922; --surface:{a.cardBackground}; --text:{a.cardText}; --muted:{a.cardMuted};
  --accent:{a.cardAccent}; --soft:{soft}; --line:{a.cardBorder};
  color:var(--text); background:var(--bg); font-family:"{a.cardFont}",Arial,sans-serif;
  font-size:{a.cardFontSize}px; line-height:{a.cardLineHeight};
}}
.golyah {{ max-width:{a.cardWidth}px; }}
.hero, .answer {{ background:{background}; border-radius:{a.cardRadius}px; }}
.term {{ font-size:{round(a.cardFontSize * 2.25)}px; }}
.translation {{ font-size:{round(a.cardFontSize * 1.6)}px; }}
.sentence {{ font-size:{a.cardFontSize}px; line-height:{a.cardLineHeight}; }}
.section {{ margin-top:{a.cardSpacing + 8}px; }}
.builder-block {{ margin-top:{a.cardSpacing}px; }}
.example-ru, .context-meaning {{ font-size:{max(12, a.cardFontSize - 1)}px; }}
.ipa {{ font-family:"{a.cardFont}","Segoe UI",sans-serif; }}
@media (max-width:480px) {{
  .card {{ font-size:{a.cardFontSize}px; }}
  .term {{ font-size:{round(a.cardFontSize * 2.1)}px; }}
  .sentence {{ font-size:{a.cardFontSize}px; }}
  .translation {{ font-size:{round(a.cardFontSize * 1.5)}px; }}
}}
"""


CSS = card_css()


def escaped(value: str) -> str:
    return html.escape(value).replace("\n", "<br>")


def highlighted_sentence(record: StudyRecord) -> str:
    sentence = record.sentence
    positions = sorted((p[0], p[1]) for p in record.selected_positions
                       if len(p) == 2 and 0 <= p[0] < p[1] <= len(sentence))
    if not positions and record.term.strip():
        match = re.search(r"(?<!\w)" + re.escape(record.term.strip()) + r"(?!\w)", sentence, re.IGNORECASE)
        if match:
            positions = [match.span()]
    cursor, parts = 0, []
    for start, end in positions:
        if start < cursor:
            continue
        parts.extend([escaped(sentence[cursor:start]), "<mark>" + escaped(sentence[start:end]) + "</mark>"])
        cursor = end
    parts.append(escaped(sentence[cursor:]))
    return "".join(parts)


def note_fields(record: StudyRecord) -> dict[str, str]:
    # The raw source article can be huge; rendering only changes these small lists.
    record = record.model_copy(update={'examples': record.examples.copy(),
        'sources': record.sources.copy(), 'synonyms': record.synonyms.copy()})
    record.include_dictionary_content()
    sources = list(dict.fromkeys(s.strip() for s in record.sources if s.strip()))
    if record.llm_model:
        sources.append(f"Gemini: {record.llm_model}")
    examples, seen = [], set()
    for example in record.examples:
        if not example.en.strip() or (example.en, example.ru) in seen:
            continue
        seen.add((example.en, example.ru))
        translation = '<div class="example-ru">' + escaped(example.ru) + '</div>' if example.ru.strip() else ""
        examples.append('<li class="example"><div>' + escaped(example.en) + '</div>' + translation + '</li>')
    synonyms = list(dict.fromkeys(s.strip() for s in record.synonyms if s.strip()))
    dictionary_definition = record.dictionary_text('definition_en')
    def entry_values(field):
        return '\n'.join(dict.fromkeys(getattr(entry, field).strip() for entry in record.entries
                                      if getattr(entry, field).strip()))
    tags = list(dict.fromkeys(tag for entry in record.entries for tag in entry.tags if tag.strip()))
    return {
        "UID": record.uid, "Term": escaped(record.term), "Lemma": escaped(record.lemma),
        "Translation": escaped(record.translation), "DefinitionEN": escaped(record.definition_en.strip()),
        "Sentence": highlighted_sentence(record), "SentenceTranslation": escaped(record.sentence_translation),
        "ContextExplanation": escaped(record.context_explanation),
        "Examples": '<ul class="examples">' + "".join(examples) + '</ul>' if examples else "",
        "Source": escaped("\n".join(sources)), "UsageEN": escaped(record.usage_en.strip()),
        "PartOfSpeech": escaped(entry_values('pos')), "IPA": escaped(entry_values('ipa')),
        "Register": " ".join('<span class="badge">' + escaped(tag) + '</span>' for tag in tags),
        "DictionaryDefinitionEN": escaped(dictionary_definition),
        "Synonyms": "".join('<span class="synonym">' + escaped(s) + '</span>' for s in synonyms),
        "Etymology": escaped(entry_values('etymology')), "Notes": escaped(entry_values('extra')),
    }


def _batch(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self.session():
            return method(self, *args, **kwargs)
    return wrapped


class AnkiService:
    def __init__(self, endpoint="http://127.0.0.1:8765", transport=None, appearance: Appearance | None = None,
                 builder: CardBuilder | None = None):
        self.endpoint, self.transport = endpoint, transport
        self.appearance = appearance or Appearance()
        self.builder = builder or CardBuilder()
        self._local = threading.local()

    @contextmanager
    def session(self):
        """One bounded connection per operation; nested calls share it."""
        if getattr(self._local, 'client', None) is not None:
            yield
            return
        with httpx.Client(timeout=5.0, transport=self.transport, trust_env=False) as client:
            self._local.client = client
            self._local.deadline = time.monotonic() + 30
            try:
                yield
            finally:
                self._local.client = None

    @_batch
    def call(self, action: str, **params):
        try:
            remaining = self._local.deadline - time.monotonic()
            if remaining <= 0:
                raise httpx.TimeoutException('Anki operation deadline exceeded')
            response = self._local.client.post(self.endpoint, timeout=min(5.0, remaining),
                json={"action": action, "version": 6, "params": params})
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError("AnkiConnect недоступен. Запустите Anki и проверьте дополнение AnkiConnect.") from exc
        if not isinstance(data, dict) or "result" not in data or "error" not in data:
            raise RuntimeError("AnkiConnect вернул некорректный ответ. Проверьте дополнение и повторите отправку.")
        if data["error"]:
            raise RuntimeError(f"Anki: {data['error']}")
        return data["result"]

    @_batch
    def connect(self):
        version = self.call("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 6:
            raise RuntimeError("Обновите AnkiConnect до версии API 6.")
        decks = self.call('deckNames')
        if not isinstance(decks, list) or any(not isinstance(deck, str) for deck in decks):
            raise RuntimeError('AnkiConnect вернул некорректный список колод. Повторите подключение.')
        return decks

    @_batch
    def ensure_model(self, mode='forward'):
        model, template = MODEL_NAMES[mode], TEMPLATE_NAMES[mode]
        expected = templates(self.builder, mode)
        fields = FIELDS if mode == 'forward' else ['Term'] + [f for f in FIELDS if f != 'Term']
        if mode == 'gap':
            fields = fields + ['GapSentence', 'GapAnswer']
        css = card_css(self.appearance)
        if model not in self.call("modelNames"):
            self.call("createModel", modelName=model, inOrderFields=fields, css=css,
                      cardTemplates=[{"Name": template, **expected}])
            return
        existing = self.call("modelFieldNames", modelName=model)
        prefix = LEGACY_FIELDS if mode == 'forward' else fields[:len(FIELDS)]
        if existing[:len(prefix)] != prefix:
            raise RuntimeError(f"Тип {model} уже существует с другими полями. Переименуйте его в Anki.")
        current_templates = self.call("modelTemplates", modelName=model)
        if template not in current_templates:
            raise RuntimeError(f"В типе {model} отсутствует карточка {template}. Проверьте шаблон в Anki.")
        for field in fields:
            if field not in existing:
                self.call("modelFieldAdd", modelName=model, fieldName=field)
        if current_templates[template] != expected:
            self.call("updateModelTemplates", model={"name": model, "templates": {template: expected}})
        if self.call("modelStyling", modelName=model).get("css") != css:
            self.call("updateModelStyling", model={"name": model, "css": css})

    @_batch
    def apply_layouts(self):
        for mode in MODES:
            self.ensure_model(mode)

    @_batch
    def add(self, record: StudyRecord, deck: str) -> int:
        if record.learning_modes != ['forward'] or record.anki_modes_pending or len(record.anki_note_ids) > 1:
            return self.sync_modes(record, deck)
        if not record.complete:
            raise ValueError("Для отправки в Anki сначала завершите LLM-данные.")
        decks = self.connect()
        if deck not in decks:
            raise ValueError("Выберите существующую колоду Anki в настройках.")
        result = self._add_variant(record, deck, 'forward')
        record.anki_note_ids['forward'] = result
        return result

    def _add_variant(self, record, deck, mode):
        self.ensure_model(mode)
        model = MODEL_NAMES[mode]
        # Checking before every send also makes retries safe after an ambiguous timeout.
        existing = self.call("findNotes", query=f'"note:{model}" UID:{record.uid}')
        if existing:
            return int(existing[0])
        fields = note_fields(record)
        if mode == 'gap':
            fields.update(gap_fields(record))
        note = {"deckName": deck, "modelName": model, "fields": fields, "tags": ["golyah"],
                "options": {"allowDuplicate": mode != 'forward', "duplicateScope": "collection"}}
        if not self.call("canAddNotes", notes=[note])[0]:
            existing = self.call("findNotes", query=f'"note:{model}" UID:{record.uid}')
            if existing:
                return int(existing[0])
            raise RuntimeError("Anki не разрешает добавить эту заметку. Проверьте поля и дубликаты.")
        result = self.call("addNote", note=note)
        if not isinstance(result, int) or isinstance(result, bool) or result <= 0:
            raise RuntimeError("Anki не подтвердила создание заметки. Повторите отправку из черновиков.")
        return result

    @_batch
    def sync_modes(self, record: StudyRecord, deck: str):
        if not record.complete:
            raise ValueError('Сначала завершите LLM-данные слова.')
        if 'reverse' in record.learning_modes and not record.translation.strip():
            raise ValueError('Для обратной карточки нужен перевод.')
        if 'gap' in record.learning_modes and not gap_fields(record)['GapSentence']:
            raise ValueError('Для пропуска нужно предложение с выбранным словом.')
        if deck not in self.connect():
            raise ValueError('Выберите существующую колоду Anki в настройках.')
        record.anki_modes_pending = True
        # Resolve by UID instead of trusting note IDs imported from another collection.
        available, ids = set(self.call('modelNames')), {}
        for mode in MODES:
            if MODEL_NAMES[mode] in available:
                found = self.call('findNotes', query=f'"note:{MODEL_NAMES[mode]}" UID:{record.uid}')
                if found:
                    ids[mode] = int(found[0])
        for mode in record.learning_modes:
            ids[mode] = self._add_variant(record, deck, mode)
            record.anki_note_ids = ids.copy()
        notes = self.call('notesInfo', notes=list(ids.values()))
        by_note = {n['noteId']: n for n in notes if n.get('noteId')}
        if set(by_note) != set(ids.values()):
            raise RuntimeError('Anki не подтвердила заметки. Повторите обновление вариантов.')
        ordinals = {mode:list(self.call('modelTemplates', modelName=MODEL_NAMES[mode])).index(TEMPLATE_NAMES[mode]) for mode in ids}
        card_ids = [c for n in by_note.values() for c in n['cards']]
        cards = self.call('cardsInfo', cards=card_ids) if card_ids else []
        if len(cards) != len(card_ids) or any(not c.get('cardId') for c in cards):
            raise RuntimeError('Anki не подтвердила карточки. Повторите обновление вариантов.')
        for mode in record.learning_modes:
            if not any(c['note'] == ids[mode] and c['ord'] == ordinals[mode] for c in cards):
                raise RuntimeError('Anki не создала карточку выбранного варианта. Проверьте обязательное поле и повторите обновление.')
        paused = set(record.anki_paused_cards)
        for card in cards:
            mode = next(m for m, nid in ids.items() if nid == card['note'])
            if card['ord'] != ordinals[mode]:
                continue  # Additional user-created templates retain their own scheduling.
            cid = card['cardId']
            if mode not in record.learning_modes and card['queue'] != -1:
                paused.add(cid)
                record.anki_paused_cards = sorted(paused)  # Journal before a possibly ambiguous timeout.
                self.call('suspend', cards=[cid])
                confirmed = self.call('cardsInfo', cards=[cid])
                if len(confirmed) != 1 or confirmed[0].get('queue') != -1:
                    raise RuntimeError('Anki не подтвердила приостановку карточки. Повторите обновление вариантов.')
            elif mode in record.learning_modes and cid in paused:
                if card['queue'] == -1:
                    self.call('unsuspend', cards=[cid])
                    confirmed = self.call('cardsInfo', cards=[cid])
                    if len(confirmed) != 1 or confirmed[0].get('queue') == -1:
                        raise RuntimeError('Anki не подтвердила включение карточки. Повторите обновление вариантов.')
                paused.discard(cid)
                record.anki_paused_cards = sorted(paused)
        record.anki_note_ids = ids
        record.anki_note_id = ids.get('forward', ids[record.learning_modes[0]])
        record.anki_modes_pending = False
        return record.anki_note_id


def preview_html(record: StudyRecord, builder=None, appearance=None, mode='forward', side='front'):
    fields = note_fields(record)
    fields.update(gap_fields(record))
    layout = templates(builder, mode)
    front = render_template(layout['Front'], fields)
    body = render_template(layout['Back'], {**fields, 'FrontSide':front}) if side == 'back' else front
    if not front:
        message = 'Для этого варианта нужно предложение с выбранным словом.' if mode == 'gap' else 'Выберите слово с переводом для предпросмотра.'
        body = '<div class="golyah"><div class="hero">' + message + '</div></div>'
    return '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>' + card_css(appearance) + '</style></head><body class="card nightMode">' + body + '</body></html>'
