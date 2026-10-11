# Запуск из исходников и выпуск

## Окружение

Поддерживаемая платформа — Windows 11 x64; рекомендуемая версия Python — 3.11 x64. `pyproject.toml` допускает Python 3.11–3.12. `requirements.lock.txt` фиксирует окружение проверенной сборки; локальных путей и учётных данных в нём нет.

```powershell
git clone https://github.com/MrSamurai4/Golyahki.git
cd Golyahki
powershell -ExecutionPolicy Bypass -File scripts/setup.ps1
.\.venv\Scripts\python.exe -m golyah
```

Если Python не найден автоматически, передайте `-Python` с путём к Python 3.11. Скрипт создаёт `.venv`, устанавливает зависимости и проект. Интернет требуется для установки и первоначальной загрузки OCR-моделей. Для минимальной разработки без Paddle и сборщика можно создать venv вручную и выполнить `python -m pip install -e . pytest`.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m scripts.audit_release
.\.venv\Scripts\python.exe -m scripts.check_ocr --paddle
```

Pytest использует временные базы и подмены API; реальный Gemini и личная коллекция Anki ему не нужны. Часть тестов Windows проверяет окна, горячие клавиши и ввод. Для настоящих проверок OCR нужен установленный английский компонент WindowsOCR или Paddle. Изображение для `check_ocr` создаётся из тестового текста; рабочий стол не захватывается.

## Переносимая сборка

```powershell
powershell -ExecutionPolicy Bypass -File scripts/build.ps1
.\.venv\Scripts\python.exe -m scripts.check_build
.\.venv\Scripts\python.exe -m scripts.package_release
```

Результат — `dist/Golyahki` и архив в `release`. PyInstaller собирает два EXE и общую `_internal`. Модели берутся из `%USERPROFILE%\.paddlex\official_models` после `check_ocr --paddle`; включаются только файлы моделей из разрешённого списка. Метаданные локальной editable-установки и `direct_url.json` исключаются. Лицензии зависимостей копируются в `licenses/dependencies`.

Используется системный Edge WebView2, без встроенного Chromium. Сборка не имеет цифровой подписи. Проверка `check_build` запускает EXE с временной базой и без Python в PATH, проверяет интерфейс и оба OCR-движка. Она сохраняет контрольные снимки только в игнорируемую папку `test-results`.

`package_release` проверяет папку и содержимое архива, создаёт SHA-256. Публикуйте только проверенный ZIP и `SHA256SUMS.txt`, а не содержимое личной рабочей папки. Не добавляйте базы, экспортированные слова, `.env`, логи, пользовательские скриншоты или старые сборки. Перед коммитом полезно дополнительно выполнить `python -m scripts.audit_release --tracked`.

## Изоляция данных

Параметр `--data-dir` выбирает отдельную базу. Он не изолирует Windows Credential Manager. Для демонстрации используйте `examples/custom-dictionary.json`, не вызывайте Gemini и не сохраняйте страницу настроек с названиями реальных окон. Штатная настройка ключа выполняется через интерфейс; переменные окружения с API-ключом не требуются.

## Структура

- `golyah/` — приложение, интеграции, QML, схемы данных;
- `tests/` — автоматические проверки;
- `scripts/` — настройка, сборка, проверка и упаковка;
- `assets/` — логотип и иконки;
- `examples/` — вымышленные демонстрационные данные;
- `docs/` — пользовательские и технические инструкции.
