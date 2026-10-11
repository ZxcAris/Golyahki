"""Prevent accidental release of personal files or embedded credentials."""
import json
from pathlib import Path

from scripts.audit_release import audit, code_findings, forbidden_name, inspect_bytes


def test_detects_credentials_without_echoing_values():
    fake = ('AI' + 'za' + 'a' * 35).encode()
    assert 'Google API key' in inspect_bytes(fake)
    assert 'Google API key' in inspect_bytes(fake.decode().encode('utf-16le'))
    assert not inspect_bytes(b'local-test-key')


def test_detects_embedded_python_constants_and_source_path():
    fake = 'gh' + 'p_' + 'a' * 36
    code = compile('value = ' + repr(fake), 'launcher.py', 'exec')
    assert 'GitHub token' in code_findings(code)
    personal = 'C:' + '/Users/' + 'example/build/app.py'
    assert 'absolute user profile path' in code_findings(compile('pass', personal, 'exec'))


def test_rejects_exports_and_credentials_by_type(tmp_path):
    for name in ('.env', 'secrets.json', 'profile.sqlite-wal', 'collection.apkg', 'personal/words.json'):
        assert forbidden_name(Path(name))
    assert forbidden_name(Path('_internal/pkg.dist-info/direct_url.json'), binary=True)
    (tmp_path / 'innocent.json').write_text(json.dumps({'kind': 'golyah-study', 'records': []}))
    _, findings = audit(tmp_path)
    assert any('personal study export' in finding for finding in findings)


def test_demo_dictionary_passes_audit(tmp_path):
    (tmp_path / 'dictionary.json').write_text(json.dumps({'kind': 'golyah-dictionary', 'entries': []}))
    assert audit(tmp_path) == (1, [])
