"""Fail publication on known credential formats, personal files or user paths.

Only file names and rule names are reported, never matched secret values.
This complements code review and a full secret scanner; it is not a guarantee.
"""
from __future__ import annotations

import argparse
import json
import marshal
import re
import subprocess
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {'.git', '.venv', 'venv', '.runtime', '.local', 'build', 'dist', 'release',
           '__pycache__', '.pytest_cache', '.mypy_cache', '.ruff_cache', 'test-results',
           '.idea', '.vscode', 'generated'}
FORBIDDEN_DIRS = {'.env', '.local', 'personal', 'exports', 'screenshots', 'test-results',
                  '.venv', '.runtime', '.git', '__pycache__'}
RULES = {
    'Google API key': rb'AIza[0-9A-Za-z_-]{35}',
    'GitHub token': rb'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})',
    'LLM API token': rb'(?<![A-Za-z0-9_])sk-(?:proj-|ant-)?[A-Za-z0-9_-]{24,}',
    'AWS access key': rb'(?:AKIA|ASIA)[A-Z0-9]{16}',
    'private key': rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=\r\n]{64,}',
    'absolute user profile path': rb'[A-Za-z]:[\\/]+Users[\\/]+(?!Public[\\/]|Default[\\/])[^\\/\s"\x00]+[\\/]',
    'authenticated URL': rb'https?://[A-Za-z0-9_.~%+!-]{1,128}:[A-Za-z0-9_.~%+!=-]{1,128}@[A-Za-z0-9]',
}
PATTERNS = {name: re.compile(pattern, re.I if name in ('absolute user profile path',) else 0)
            for name, pattern in RULES.items()}


def inspect_bytes(data: bytes) -> set[str]:
    # Decode only actual UTF-16 strings. Removing every NUL would concatenate
    # unrelated DLL string-table entries and manufacture false credential matches.
    strings = [data]
    if b'\x00' in data:
        strings.extend(match.group()[::2] for match in re.finditer(rb'(?:[\x09\x0a\x0d\x20-\x7e]\x00){8,}', data))
    findings = set()
    for name, pattern in PATTERNS.items():
        for value in strings:
            for match in pattern.finditer(value):
                if name == 'authenticated URL':
                    credentials = match.group().split(b'://', 1)[1].split(b'@', 1)[0]
                    if credentials in {b'user:pass', b'user:password', b'username:password'}:
                        continue  # Documented proxy placeholders, not usable accounts.
                findings.add(name)
                break
            if name in findings:
                break
    return findings


def forbidden_name(path: Path, *, binary: bool = False) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if any(part.lower() in FORBIDDEN_DIRS for part in path.parts):
        return True
    if name.startswith('.env') and name != '.env.example':
        return True
    if suffix in {'.sqlite', '.sqlite3', '.db', '.log', '.bak', '.pfx', '.p12', '.apkg', '.colpkg', '.lnk'}:
        return True
    if re.search(r'\.(?:sqlite3?|db)-', name):
        return True
    if name.startswith(('credentials', 'secrets')) and suffix in {'.json', '.yml', '.yaml', '.toml', '.ini'}:
        return True
    return binary and name == 'direct_url.json'


def code_findings(value) -> set[str]:
    if isinstance(value, types.CodeType):
        result = inspect_bytes(value.co_filename.encode('utf-8'))
        for constant in value.co_consts:
            result.update(code_findings(constant))
        return result
    if isinstance(value, str):
        return inspect_bytes(value.encode('utf-8'))
    if isinstance(value, bytes):
        return inspect_bytes(value)
    if isinstance(value, (tuple, frozenset)):
        return set().union(*(code_findings(item) for item in value)) if value else set()
    return set()


def executable_findings(path: Path) -> list[str]:
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(path))
    findings = []
    for name, entry in archive.toc.items():
        if entry[-1] == 'z':
            pyz = archive.open_embedded_archive(name)
            for module in pyz.toc:
                # First-party code and embedded source paths are inspected after decompression.
                if module == 'golyah' or module.startswith('golyah.'):
                    for reason in code_findings(pyz.extract(module)):
                        findings.append(f'{path.name}:{module}: {reason}')
        elif entry[-1] == 's':
            for reason in code_findings(marshal.loads(archive.extract(name))):
                findings.append(f'{path.name}:{name}: {reason}')
    return findings


def audit(root: Path, *, binary: bool = False, tracked: bool = False) -> tuple[int, list[str]]:
    root = root.resolve()
    if tracked:
        names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode('utf-8').split('\0')
        files = [root / name for name in names if name]
        if not files:
            raise RuntimeError('No tracked files. Stage the public files before using --tracked.')
    else:
        files = [p for p in root.rglob('*') if p.is_file() and
                 (binary or not any(x in IGNORED or x.endswith('.egg-info') for x in p.relative_to(root).parts))]
        files = [p for p in files if binary or p.suffix.lower() not in {'.log', '.pyc'}]
    findings = []
    for path in files:
        relative = path.relative_to(root)
        if forbidden_name(relative, binary=binary):
            findings.append(f'{relative.as_posix()}: private/local file type')
        data = path.read_bytes()
        # Third-party binaries can contain their vendors' build paths. Scan all for
        # credentials, and enforce profile-path removal on our own files.
        reasons = inspect_bytes(data)
        if binary and relative.parts[0] in {'_internal', 'licenses'} and 'golyah' not in relative.parts:
            reasons.discard('absolute user profile path')
        findings.extend(f'{relative.as_posix()}: {reason}' for reason in sorted(reasons))
        if path.suffix.lower() == '.json':
            try:
                value = json.loads(data)
            except (ValueError, UnicodeError):
                value = None
            if isinstance(value, dict) and value.get('kind') == 'golyah-study' and isinstance(value.get('records'), list):
                findings.append(f'{relative.as_posix()}: personal study export')
        if binary and path.name in {'Golyahki.exe', 'Golyahki-OCR.exe'}:
            findings.extend(executable_findings(path))
    return len(files), findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path, nargs='?', default=ROOT)
    parser.add_argument('--binary', action='store_true')
    parser.add_argument('--tracked', action='store_true')
    args = parser.parse_args()
    count, findings = audit(args.root, binary=args.binary, tracked=args.tracked)
    for finding in findings:
        print(finding)
    print(f'Privacy audit: {count} files, {len(findings)} findings.')
    raise SystemExit(bool(findings))


if __name__ == '__main__':
    main()
