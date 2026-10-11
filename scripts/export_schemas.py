"""Regenerate the public dictionary and study JSON schemas."""
import json
from pathlib import Path
from golyah.models import Entry, StudyRecord

directory = Path(__file__).resolve().parents[1] / 'golyah' / 'schemas'
directory.mkdir(exist_ok=True)
for kind, model, array, extra in [
    ('golyah-dictionary', Entry, 'entries', {'name': {'type': 'string', 'minLength': 1},
        'revision': {'type': 'string'}, 'attribution': {'type': 'string'}}),
    ('golyah-study', StudyRecord, 'records', {}),
]:
    item = model.model_json_schema()
    definitions = item.pop('$defs', {})
    schema = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
        'title': kind, 'type': 'object', '$defs': definitions,
        'properties': {'schemaVersion': {'const': 1}, 'kind': {'const': kind},
                       array: {'type': 'array', 'items': item}, **extra},
        'required': ['schemaVersion', 'kind', array] + (['name'] if extra else [])}
    (directory / (kind + '.schema.json')).write_text(
        json.dumps(schema, ensure_ascii=False, indent=2), encoding='utf-8')
