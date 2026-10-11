# Third-party software and data

The MIT license in `LICENSE` applies to Golyahki's own source code and artwork.
Bundled dependencies retain their original licenses and copyright notices.

| Component | Project / source | License information |
| --- | --- | --- |
| Python | https://www.python.org/ | PSF and included notices; `licenses/Python.txt` |
| PySide6 / Shiboken6 / Qt | https://code.qt.io/pyside/pyside-setup.git/ and https://code.qt.io/qt/ | LGPLv3/GPLv3 or commercial terms, according to each component; this open-source distribution uses applicable open-source terms |
| PaddlePaddle, PaddleOCR, PaddleX and PP-OCRv5 mobile models | https://github.com/PaddlePaddle | Apache-2.0 and notices of included dependencies |
| Google Gen AI Python SDK | https://github.com/googleapis/python-genai | Apache-2.0 |
| PyInstaller | https://pyinstaller.org/ | GPL with the project's bootloader distribution exception |
| Other Python dependencies | `requirements.lock.txt` | License texts from the installed distributions in `licenses/dependencies` in the binary release |

License texts for LGPLv3, GPLv3 and Apache-2.0 are in `licenses`. The binary release additionally contains the notices shipped in the build environment and a package/version inventory. The inventory may include build tools that are not used at runtime.

## Qt and PySide

The portable application dynamically loads Qt/PySide libraries from `_internal/PySide6` and Shiboken from `_internal/shiboken6`. These libraries are not statically linked into Golyahki. Users may replace them with compatible modified builds; preserve the same ABI, architecture and directory layout. This project does not prohibit reverse engineering for debugging modifications to LGPL-covered libraries.

The released environment uses PySide6 / Qt 6.11.2; exact component versions are recorded in `requirements.lock.txt` and the release inventory. Corresponding source is available from the upstream [Qt archive](https://download.qt.io/archive/qt/) and [Qt for Python archive](https://download.qt.io/official_releases/QtForPython/). The application source and build instructions are included in this repository. Qt includes its own third-party components and notices; packaged license files are preserved. Edge WebView2 is a separately installed Microsoft runtime, not redistributed as part of this ZIP.

## Dictionaries

The example JSON contains demonstration entries written for this project. The built-in `nah` entry credits its reference in `golyah/data/spoken-en-ru.json`; glosses and examples were written for the project. No complete WTY/Yomitan dictionary or personal vocabulary database is bundled. Imported dictionaries keep their own attribution and licenses, which users should review before redistributing those files or derived material.

Anki and AnkiConnect are installed separately and are not included in the download.
