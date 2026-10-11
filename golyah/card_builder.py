"""Validated card layouts and shared template rendering for export and preview."""
from __future__ import annotations

import html
import re
import copy
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .models import StudyRecord

Mode = Literal['forward', 'reverse', 'gap']
MODES = ['forward', 'reverse', 'gap']
MODE_LABELS = {'forward':'Слово → перевод', 'reverse':'Перевод → слово', 'gap':'Предложение с пропуском'}
MODEL_NAMES = {'forward':'Screen Vocabulary', 'reverse':'Golyahki Reverse', 'gap':'Golyahki Gap'}
TEMPLATE_NAMES = {'forward':'Vocabulary', 'reverse':'Translation to word', 'gap':'Sentence gap'}
BLOCKS = {
    'term': ('Слово', 'Term', 'term'),
    'translation': ('Перевод', 'Translation', 'translation'),
    'lemma': ('Базовая форма', 'Lemma', 'lemma'),
    'part_of_speech': ('Часть речи', 'PartOfSpeech', 'metadata'),
    'ipa': ('Транскрипция', 'IPA', 'ipa'),
    'register': ('Пометки', 'Register', 'metadata'),
    'sentence': ('В исходном контексте', 'Sentence', 'sentence'),
    'dictionary_definition': ('Из словаря · EN', 'DictionaryDefinitionEN', ''),
    'definition': ('Explain · EN', 'DefinitionEN', ''),
    'usage': ('Употребление · EN', 'UsageEN', ''),
    'sentence_translation': ('Перевод контекста', 'SentenceTranslation', ''),
    'context_explanation': ('Разбор контекста', 'ContextExplanation', 'context-meaning'),
    'examples': ('Примеры', 'Examples', ''),
    'synonyms': ('Синонимы', 'Synonyms', ''),
    'etymology': ('Происхождение слова', 'Etymology', ''),
    'notes': ('Примечания словаря', 'Notes', ''),
    'source': ('Источники', 'Source', ''),
}


class Block(BaseModel):
    model_config = ConfigDict(extra='forbid')
    key: str
    visible: bool = True

    @field_validator('key')
    @classmethod
    def known_key(cls, value):
        if value not in BLOCKS and value not in ('prompt', 'answer'):
            raise ValueError('Неизвестный блок карточки.')
        return value


class Layout(BaseModel):
    model_config = ConfigDict(extra='forbid')
    front: list[Block]
    back: list[Block]

    @model_validator(mode='after')
    def complete_layout(self):
        for side, required in [('front', 'prompt'), ('back', 'answer')]:
            blocks = getattr(self, side)
            keys = [b.key for b in blocks]
            if set(keys) != set(BLOCKS) | {required} or len(keys) != len(set(keys)):
                raise ValueError('Каждый блок должен встречаться ровно один раз.')
            if not next(b for b in blocks if b.key == required).visible:
                raise ValueError('Основной вопрос и ответ нельзя скрыть.')
        return self


def default_layouts():
    back = ['answer', 'lemma', 'dictionary_definition', 'definition', 'usage',
            'sentence_translation', 'context_explanation', 'examples', 'synonyms', 'etymology', 'notes', 'source']
    def blocks(required, enabled):
        keys = enabled + [key for key in BLOCKS if key not in enabled]
        return [Block(key=key, visible=key in enabled) for key in keys]
    return {
        'forward': Layout(front=blocks('prompt', ['prompt','part_of_speech','ipa','register','sentence']), back=blocks('answer',back)),
        'reverse': Layout(front=blocks('prompt', ['prompt']), back=blocks('answer',['answer','part_of_speech','ipa','register','sentence'] + back[1:])),
        'gap': Layout(front=blocks('prompt', ['prompt']), back=blocks('answer',['answer','translation','sentence'] + back[1:])),
    }


class CardBuilder(BaseModel):
    model_config = ConfigDict(extra='forbid')
    layouts: dict[Mode, Layout] = Field(default_factory=default_layouts)

    @field_validator('layouts')
    @classmethod
    def all_modes(cls, value):
        if set(value) != set(MODES):
            raise ValueError('Нужны все три варианта обучения.')
        return value


def load_builder(value):
    try:
        # 0.4 audio blocks are retired; retain the order and visibility of every
        # other block, without rewriting the user's stored preferences.
        if isinstance(value, dict):
            value = copy.deepcopy(value)
            for layout in value.get('layouts', {}).values():
                for side in ('front', 'back'):
                    layout[side] = [b for b in layout[side]
                                    if b.get('key') not in ('word_audio', 'sentence_audio')]
        return CardBuilder.model_validate(value) if isinstance(value, dict) else CardBuilder()
    except (ValueError, KeyError, TypeError, AttributeError):
        return CardBuilder()


def gap_fields(record: StudyRecord):
    sentence = record.sentence
    positions = sorted({tuple(p) for p in record.selected_positions
        if len(p) == 2 and 0 <= p[0] < p[1] <= len(sentence)})
    if not positions and record.term.strip():
        match = re.search(r'(?<!\w)' + re.escape(record.term.strip()) + r'(?!\w)', sentence, re.I)
        if match:
            positions = [match.span()]
    cursor, parts, answers = 0, [], []
    for start, end in positions:
        # OCR token bounds often include a comma, quote or full stop. Keep those
        # outside the blank, while retaining intentional punctuation in the term
        # (can't, James', 'tis) and internal punctuation in selected phrases.
        chunk = sentence[start:end]
        exact = re.search(r'(?<!\w)' + re.escape(record.term.strip()) + r'(?!\w)', chunk, re.I) if record.term.strip() else None
        if exact:
            end = start + exact.end()
            start += exact.start()
        else:
            characters = list(re.finditer(r'\w', chunk))
            if not characters:
                continue
            end = start + characters[-1].end()
            start += characters[0].start()
        if start < cursor:
            continue
        parts += [html.escape(sentence[cursor:start]).replace('\n','<br>'), '<span class="gap">_____</span>']
        answers.append(html.escape(sentence[start:end]))
        cursor = end
    if not answers:
        return {'GapSentence':'', 'GapAnswer':''}
    parts.append(html.escape(sentence[cursor:]).replace('\n','<br>'))
    return {'GapSentence':''.join(parts), 'GapAnswer':' … '.join(answers)}


def templates(builder: CardBuilder | None = None, mode: Mode = 'forward'):
    builder = builder or CardBuilder()
    prompt = {'forward':('Term','term'), 'reverse':('Translation','translation'), 'gap':('GapSentence','sentence')}[mode]
    answer = {'forward':('Translation','translation'), 'reverse':('Term','term'), 'gap':('GapAnswer','term')}[mode]
    def block(spec):
        if not spec.visible:
            return ''
        if spec.key in ('prompt','answer'):
            field, style = prompt if spec.key == 'prompt' else answer
            label = 'Значение' if spec.key == 'answer' and mode == 'forward' else 'Ответ' if spec.key == 'answer' else ''
        else:
            label, field, style = BLOCKS[spec.key]
            # An unmasked source sentence would disclose the answer to a gap question.
            if spec.key == 'sentence' and mode == 'gap':
                field = 'GapSentence' if current_side == 'front' else 'Sentence'
        caption = f'<div class="section-label">{label}</div>' if label else ''
        content = f'{caption}<div class="{style}">{{{{{field}}}}}</div>'
        if spec.key in ('etymology','notes','source'):
            content = f'<details class="details"><summary>{label}</summary><div class="details-content">{{{{{field}}}}}</div></details>'
        return f'{{{{#{field}}}}}<section class="builder-block" data-block="{spec.key}">{content}</section>{{{{/{field}}}}}'
    current_side = 'front'
    front = ''.join(block(b) for b in builder.layouts[mode].front)
    direction = {'forward':'ENGLISH → РУССКИЙ', 'reverse':'РУССКИЙ → ENGLISH', 'gap':'ВОССТАНОВИТЕ СЛОВО'}[mode]
    front = ('{{#' + prompt[0] + '}}<div class="golyah"><div class="hero">'
             '<div class="brand"><span class="brand-name">Golyahki</span><span>' + direction + '</span></div>'
             + front + '</div></div>{{/' + prompt[0] + '}}')
    current_side = 'back'
    back = '{{FrontSide}}<div class="golyah"><div class="answer" id="answer">' + ''.join(block(b) for b in builder.layouts[mode].back) + '</div></div>'
    return {'Front':front, 'Back':back}


def render_template(template: str, fields: dict[str, str]):
    """Render Anki's nested field/conditional syntax without running scripts."""
    tokens = re.split(r'({{[^{}]+}})', template)
    def parse(index, closing=None):
        parts = []
        while index < len(tokens):
            token = tokens[index]; index += 1
            if not token.startswith('{{'):
                parts.append(token); continue
            key = token[2:-2]
            if key.startswith('/'):
                if key[1:] != closing:
                    raise ValueError('Неверная секция шаблона.')
                return ''.join(parts), index
            if key.startswith(('#','^')):
                child, index = parse(index, key[1:])
                if bool(fields.get(key[1:])) == (key[0] == '#'):
                    parts.append(child)
            else:
                parts.append(fields.get(key, ''))
        if closing:
            raise ValueError('Незакрытая секция шаблона.')
        return ''.join(parts), index
    return parse(0)[0]
