# Compatibility entry point for existing build commands.
from pathlib import Path
exec(compile((Path(SPECPATH) / 'Golyahki.spec').read_text(encoding='utf-8'), 'Golyahki.spec', 'exec'))
