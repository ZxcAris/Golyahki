from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, PositiveInt, field_validator
from .audio_models import AudioClip

StudyMode = Literal['forward', 'reverse', 'gap']


def normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).strip().split()).casefold()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Example(BaseModel):
    en: str
    ru: str = ""


class Sense(BaseModel):
    translation: str
    definition_en: str = ""
    examples: list[Example] = Field(default_factory=list)


class Entry(BaseModel):
    word: str
    lemma: str = ""
    pos: str = ""
    tags: list[str] = Field(default_factory=list)
    definition_en: str = ""
    senses: list[Sense] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    etymology: str = ""
    extra: str = ""
    sources: list[str] = Field(default_factory=list)
    ipa: str = ""
    dictionary: str = ""
    forms: list[str] = Field(default_factory=list)
    raw: Any = None


class Explanation(BaseModel):
    definition_en: str = Field(min_length=1)
    usage_en: str = Field(min_length=1)
    translation_ru: str = Field(min_length=1)
    synonyms: list[str] = Field(default_factory=list)
    examples: list[Example] = Field(default_factory=list)
    senses: list[Sense] = Field(default_factory=list)

    @property
    def full_translation(self) -> str:
        return '\n'.join(f'{index}. {sense.translation}' for index, sense in enumerate(self.senses, 1)) if self.senses else self.translation_ru

    @property
    def full_definition_en(self) -> str:
        definitions = '\n'.join(f'{index}. {sense.definition_en}' for index, sense in enumerate(self.senses, 1)
                                if sense.definition_en.strip())
        return self.definition_en + ('\n\n' + definitions if definitions else '')

    def all_examples(self) -> list[Example]:
        examples, seen = [], set()
        for example in self.examples + [example for sense in self.senses for example in sense.examples]:
            if (example.en, example.ru) not in seen:
                examples.append(example)
                seen.add((example.en, example.ru))
        return examples


class ContextTranslation(BaseModel):
    translation_ru: str = Field(min_length=1)
    explanation_ru: str = Field(min_length=1)


class Enrichment(BaseModel):
    explain: Explanation
    context: ContextTranslation | None = None


class StudyRecord(BaseModel):
    term: str
    lemma: str = ""
    sentence: str = ""
    selected_positions: list[list[int]] = Field(default_factory=list)
    selection_preview: str = ""
    entries: list[Entry] = Field(default_factory=list)
    sense_index: int = Field(default=0, ge=0)
    entry_index: int = Field(default=0, ge=0)
    translation: str = ""
    definition_en: str = ""
    usage_en: str = ""
    sentence_translation: str = ""
    context_explanation: str = ""
    examples: list[Example] = Field(default_factory=list)
    synonyms: list[str] = Field(default_factory=list)
    sources: list[str] = Field(default_factory=list)
    explain: Explanation | None = None
    context: ContextTranslation | None = None
    llm_model: str = ""
    status: Literal['draft', 'preview', 'saved', 'pending_anki'] = "draft"
    destination: Literal['dictionary', 'anki'] = "dictionary"
    error: str = ""
    anki_note_id: int | None = None
    learning_modes: list[StudyMode] = Field(default_factory=lambda: ['forward'])
    anki_note_ids: dict[StudyMode, PositiveInt] = Field(default_factory=dict)
    anki_paused_cards: list[PositiveInt] = Field(default_factory=list)
    anki_modes_pending: bool = False
    word_audio: AudioClip | None = None
    sentence_audio: AudioClip | None = None
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)

    @field_validator('learning_modes')
    @classmethod
    def study_modes(cls, value):
        if not value or len(value) != len(set(value)):
            raise ValueError('Выберите хотя бы один вариант обучения без повторов.')
        return [m for m in ('forward', 'reverse', 'gap') if m in value]

    @property
    def uid(self) -> str:
        payload = json.dumps([normalized(self.term), normalized(self.sentence)], ensure_ascii=False)
        return hashlib.sha256(payload.encode()).hexdigest()

    @property
    def complete(self) -> bool:
        return self.explain is not None and (not self.sentence.strip() or self.context is not None)

    def identity(self) -> tuple:
        return (self.term, self.sentence, self.entry_index, self.sense_index)

    def selected_entry(self) -> Entry | None:
        return self.entries[self.entry_index] if self.entries and self.entry_index < len(self.entries) else None

    def dictionary_text(self, field: Literal['translation', 'definition_en']) -> str:
        """Keep every article and sense, with stable labels across selections."""
        articles = []
        for entry in self.entries:
            lines = []
            if field == 'definition_en' and entry.definition_en.strip():
                lines.append(entry.definition_en.strip())
            for index, sense in enumerate(entry.senses, 1):
                value = getattr(sense, field).strip()
                if not value:
                    continue
                label = f'{index}. ' if len(entry.senses) > 1 else ''
                if field == 'definition_en' and sense.translation.strip():
                    label += sense.translation.strip() + ' — '
                lines.append(label + value)
            if not lines:
                continue
            if len(self.entries) > 1:
                label = ' · '.join(v for v in (entry.word, entry.pos, entry.dictionary) if v.strip())
                lines.insert(0, label)
            articles.append('\n'.join(lines))
        return '\n\n'.join(articles)

    def include_dictionary_content(self):
        """Also upgrade saved records made when only one sense was copied."""
        translation = self.dictionary_text('translation')
        if translation:
            defaults = {sense.translation.strip() for entry in self.entries for sense in entry.senses}
            if self.explain:
                defaults.add(self.explain.translation_ru.strip())
            current = self.translation.strip()
            if not current or current in defaults or current == translation:
                self.translation = translation
            elif not current.endswith('\n\n' + translation):
                self.translation = current + '\n\n' + translation
        seen = {(example.en, example.ru) for example in self.examples}
        for entry in self.entries:
            self.sources = list(dict.fromkeys(self.sources + entry.sources + ([entry.dictionary] if entry.dictionary else [])))
            self.synonyms = list(dict.fromkeys(self.synonyms + entry.synonyms))
            for sense in entry.senses:
                for example in sense.examples:
                    if (example.en, example.ru) not in seen:
                        self.examples.append(example.model_copy(deep=True))
                        seen.add((example.en, example.ru))

    def select_defaults(self):
        entry = self.selected_entry()
        self.lemma = entry.lemma or entry.word if entry else self.term
        self.include_dictionary_content()


class OCRWord(BaseModel):
    id: int
    text: str
    polygon: list[list[float]]
    confidence: float
    line: int
    block: int = 0

    def bounds(self) -> tuple[float, float, float, float]:
        xs, ys = zip(*self.polygon)
        return min(xs), min(ys), max(xs), max(ys)
