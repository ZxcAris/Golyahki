"""Collect license texts from the build environment without copying install paths."""
import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path


def collect(destination):
    output = Path(destination) / 'licenses' / 'dependencies'
    output.mkdir(parents=True, exist_ok=True)
    packages = []
    for dist in importlib.metadata.distributions():
        name = dist.metadata.get('Name', '')
        if not name or name.lower() == 'golyah':
            continue
        folder = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
        included = []
        for file in dist.files or []:
            if any(part in {'..', '__pycache__'} for part in file.parts):
                continue
            if not any(part.lower() == 'licenses' for part in file.parts) and not file.name.lower().startswith(('license', 'copying', 'notice', 'copyright')):
                continue
            source = Path(dist.locate_file(file))
            if not source.is_file() or source.suffix.lower() in {'.py', '.pyc', '.pyd', '.dll'}:
                continue
            target = output / folder / file
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            included.append(target.relative_to(output).as_posix())
        packages.append({'name': name, 'version': dist.version,
            'license': dist.metadata.get('License-Expression') or dist.metadata.get('License', '').split('\n')[0],
            'license_files': included})
    (output / 'packages.json').write_text(json.dumps(sorted(packages, key=lambda p: p['name'].lower()),
        ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Collected notices for {len(packages)} build-environment distributions.')


if __name__ == '__main__':
    collect(sys.argv[1])
