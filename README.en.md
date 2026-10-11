# Golyahki

**Turn English on your screen into words you remember.**

[Download for Windows](https://github.com/MrSamurai4/Golyahki/releases/latest) · [Русский](README.md) · [Report a bug](https://github.com/MrSamurai4/Golyahki/issues)

![Golyahki with a sample dictionary entry](docs/images/main.png)

Golyahki is a Windows desktop app for Russian-speaking learners of English. Capture text in a game, video or application, look up words in local dictionaries, request explanations from Gemini, and send vocabulary to Anki.

## Install

1. Download **Golyahki-1.0.0-windows-x64.zip** from [Releases](https://github.com/MrSamurai4/Golyahki/releases/latest).
2. Extract the entire `Golyahki` folder and run **Golyahki.exe**. Keep `_internal` and `Golyahki-OCR.exe` beside it.
3. No Python or administrator access is needed. The executable is unsigned; Windows may show an unknown-publisher warning. A SHA-256 checksum file is included with each release.

Requires **Windows 11 x64**. The Anki preview uses the [Microsoft Edge WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/). WindowsOCR uses the installed English OCR language component; PaddleOCR and its models are also bundled. macOS, Linux and Windows ARM are not supported by this release.

## Get started

- Import `examples/custom-dictionary.json` on the **Словари** page, then search for `experience`. This is a sample; import your own Yomitan v3 dictionary for everyday use. No large dictionary is included.
- Choose a screen or window in **Настройки**, press **Alt+Q**, then click a word. **Shift+click** selects a range; **Ctrl+click** selects additional words; **Esc** closes the overlay.
- Add your own [Google AI Studio](https://aistudio.google.com/api-keys) key in settings to use **Explain** and **Context translator**. Choose a model available to your Google account. Usage and billing belong to your project.
- To use Anki, install [Anki Desktop](https://apps.ankiweb.net/) and [AnkiConnect](https://ankiweb.net/shared/info/2055492159), restart Anki, connect from Golyahki, and select a deck. Keep Anki running while adding cards.
- The **+** button prepares missing Gemini explanations, saves a study record, and optionally sends it to Anki. Without a key or when a request fails, the record remains a draft. Dictionary-only mode disables Anki delivery, not LLM enrichment.

Local OCR and dictionary lookup work without Gemini or Anki. The UI and translations are primarily Russian. Text-to-speech is not included.

## Privacy

Every user supplies their own API key. It is stored in Windows Credential Manager, outside the database and source tree. Personal words, settings and translation cache live in `%LOCALAPPDATA%\GOlyah`. Normal screen capture stays in memory and runs locally; Gemini receives selected text, context and dictionary hints when requested, never the screen image. There is no project-operated server or analytics. See [the data guide](docs/PRIVACY.md).

## Develop

On Windows with Python 3.11 x64, run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
.\.venv\Scripts\python.exe -m golyah
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.check_ocr --paddle
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
```

[Build instructions](docs/SETUP.md) · [Contributing](CONTRIBUTING.md) · [MIT license](LICENSE) · [Third-party notices](THIRD_PARTY_NOTICES.md)
