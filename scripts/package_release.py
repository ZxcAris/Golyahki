"""Create and recheck the downloadable archive and its SHA-256 checksum."""
import hashlib
import tempfile
import zipfile
from pathlib import Path

from golyah import __version__
from scripts.audit_release import ROOT, audit


def main():
    build = ROOT / 'dist' / 'Golyahki'
    for required in ('Golyahki.exe', 'Golyahki-OCR.exe', '_internal', 'LICENSE', 'licenses', 'README.md'):
        if not (build / required).exists():
            raise RuntimeError(f'Missing required release component: {required}')
    count, findings = audit(build, binary=True)
    if findings:
        raise RuntimeError('\n'.join(findings))
    output = ROOT / 'release'
    output.mkdir(exist_ok=True)
    destination = output / f'Golyahki-{__version__}-windows-x64.zip'
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(build.rglob('*')):
            if path.is_file():
                archive.write(path, 'Golyahki/' + path.relative_to(build).as_posix())
    with tempfile.TemporaryDirectory(prefix='golyahki-archive-audit-') as temporary:
        with zipfile.ZipFile(destination) as archive:
            if archive.testzip() is not None:
                raise RuntimeError('Archive checksum verification failed')
            archive.extractall(temporary)
        archived_count, findings = audit(Path(temporary) / 'Golyahki', binary=True)
        if findings or archived_count != count:
            raise RuntimeError('Archive audit failed: ' + '\n'.join(findings))
    with destination.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (output / 'SHA256SUMS.txt').write_text(f'{digest}  {destination.name}\n', encoding='ascii')
    print(f'Archive verified: {destination.name}, {destination.stat().st_size} bytes, {count} files')
    print(f'SHA-256: {digest}')


if __name__ == '__main__':
    main()
