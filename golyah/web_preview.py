"""Initialize Qt's small native WebView2 backend instead of bundled Chromium."""
from __future__ import annotations

import os
from pathlib import Path


def initialize_preview(cache: Path | None = None):
    # Must run before QApplication. Both preview and tests use the same backend.
    os.environ['QT_WEBVIEW_PLUGIN'] = 'webview2'
    os.environ['WEBVIEW2_DEFAULT_BACKGROUND_COLOR'] = 'FF161922'
    if cache is not None:
        os.environ['WEBVIEW2_USER_DATA_FOLDER'] = str(cache.resolve())
    from PySide6.QtWebView import QtWebView
    QtWebView.initialize()
