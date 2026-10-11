from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ocr-worker", action="store_true")
    parser.add_argument("--import-dictionary")
    parser.add_argument("--data-dir")
    parser.add_argument("--smoke", help="Save a screenshot of the app and exit")
    parser.add_argument("--smoke-word", default="quick")
    parser.add_argument("--smoke-page", type=int, default=0)
    parser.add_argument("--smoke-translation", action="store_true")
    parser.add_argument("--smoke-ocr", help="Test the full OCR process and popup using a local image")
    parser.add_argument("--ocr-image", help="Recognize an image and output word coordinates")
    args = parser.parse_args()
    if args.ocr_worker:
        from .ocr import worker
        worker()
        return
    if args.ocr_image:
        import json
        from .ocr import OCRRunner
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(OCRRunner().recognize(args.ocr_image), ensure_ascii=False))
        return
    from platformdirs import user_data_dir
    from .storage import Storage
    data_dir = Path(args.data_dir or user_data_dir("GOlyah", appauthor=False))
    storage = Storage(data_dir / "golyah.sqlite")
    if args.import_dictionary:
        import json
        from .dictionaries import DictionaryService
        sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(DictionaryService(storage).import_file(args.import_dictionary), ensure_ascii=False))
        return
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QUrl, QLockFile, QEvent
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuick import QQuickWindow
    from PySide6.QtGui import QFont, QPalette, QColor
    from .web_preview import initialize_preview
    initialize_preview(data_dir / "webview")
    from .bridge import Bridge
    app = QApplication(sys.argv)
    app.setApplicationName("Golyahki")
    app.setOrganizationName("Golyahki")
    app.setQuitOnLastWindowClosed(False)
    server, lock = None, None
    if not args.smoke:
        import hashlib
        name = 'GOlyah-' + hashlib.sha256(str(data_dir.resolve()).casefold().encode()).hexdigest()[:24]
        socket = QLocalSocket()
        socket.connectToServer(name)
        if socket.waitForConnected(200):
            socket.write(b'show')
            socket.waitForBytesWritten(500)
            socket.disconnectFromServer()
            return 0
        lock = QLockFile(str(data_dir / 'running.lock'))
        if not lock.tryLock(500):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(None, 'Golyahki', 'Приложение уже запущено. Откройте его через значок в трее.')
            return 0
        server = QLocalServer(app)
        server.listen(name)
    bridge = Bridge(storage)
    def apply_native_appearance():
        preferences = bridge.appearance
        font = QFont(preferences['uiFont'])
        font.setPixelSize(preferences['uiFontSize'])
        app.setFont(font)
        palette = QPalette()
        accent = QColor(preferences['accent'])
        ink = '#11141b' if accent.lightnessF() > .55 else '#ffffff'
        for role, color in [(QPalette.ColorRole.Window, '#1c212c'), (QPalette.ColorRole.WindowText, '#edf0f7'),
            (QPalette.ColorRole.Base, '#11141b'), (QPalette.ColorRole.Text, '#edf0f7'),
            (QPalette.ColorRole.Button, '#262d3b'), (QPalette.ColorRole.ButtonText, '#edf0f7'),
            (QPalette.ColorRole.Highlight, preferences['accent']), (QPalette.ColorRole.HighlightedText, ink),
            (QPalette.ColorRole.PlaceholderText, '#748096')]:
            palette.setColor(role, QColor(color))
        app.setPalette(palette)
    apply_native_appearance()
    bridge.appearanceChanged.connect(apply_native_appearance)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        bridge.close()
        return 1
    window = engine.rootObjects()[0]
    if server:
        def show_existing():
            connection = server.nextPendingConnection()
            window.show(); window.raise_(); window.requestActivate()
            if connection:
                connection.disconnectFromServer()
                connection.deleteLater()
        server.newConnection.connect(show_existing)
    app.aboutToQuit.connect(bridge.close)
    # A visible tray entry allows returning to the app while an overlay is active.
    from PySide6.QtWidgets import QSystemTrayIcon, QMenu
    from PySide6.QtGui import QAction
    from .branding import app_icon
    app.setWindowIcon(app_icon())
    tray = QSystemTrayIcon(app.windowIcon(), app)
    tray.setToolTip("Golyahki · " + bridge.settings["hotkey"])
    bridge.settingsChanged.connect(lambda: tray.setToolTip("Golyahki · " + bridge.settings['hotkey']))
    menu = QMenu()
    show_action = QAction("Открыть Golyahki", menu)
    show_action.triggered.connect(lambda: (window.show(), window.raise_(), window.requestActivate()))
    menu.addAction(show_action)
    capture_action = QAction("Захватить экран", menu)
    capture_action.triggered.connect(bridge.requestCapture)
    menu.addAction(capture_action)
    menu.addSeparator()
    quit_action = QAction("Выйти", menu); quit_action.triggered.connect(app.quit); menu.addAction(quit_action)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: show_action.trigger() if reason == QSystemTrayIcon.ActivationReason.DoubleClick else None)
    tray.show()
    if args.smoke:
        screenshot_window = window
        def screenshot():
            destination = Path(args.smoke)
            destination.parent.mkdir(parents=True, exist_ok=True)
            screenshot_window.grabWindow().save(str(destination))
            app.quit()
        if args.smoke_ocr:
            from PIL import Image
            import numpy as np
            from PySide6.QtCore import QObject
            pixels = np.array(Image.open(args.smoke_ocr).convert('RGBA'))
            bridge._image = pixels[:, :, [2, 1, 0, 3]].copy()
            screen = app.primaryScreen()
            ratio = screen.devicePixelRatio()
            bridge._overlay.update(visible=True, width=pixels.shape[1]/ratio, height=pixels.shape[0]/ratio,
                pixelWidth=pixels.shape[1], pixelHeight=pixels.shape[0])
            bridge._overlay['stage'] = 'recognizing'
            window.hide()
            bridge.overlayChanged.emit()
            def ocr_finished():
                nonlocal screenshot_window
                if not bridge.busy and bridge.overlay['words']:
                    bridge.stateChanged.disconnect(ocr_finished)
                    chosen = next((w for w in bridge.overlay['words'] if w['text'].lower() == args.smoke_word), bridge.overlay['words'][0])
                    bridge.chooseWord(chosen['id'], False)
                    screenshot_window = window.findChild(QQuickWindow, 'wordPopup')
                    QTimer.singleShot(500, screenshot)
            bridge.stateChanged.connect(ocr_finished)
            QTimer.singleShot(100, bridge._run_ocr)
            QTimer.singleShot(45000, app.quit)
        else:
            bridge.lookup(args.smoke_word, "She gave them a quick look.")
            window.setProperty("page", args.smoke_page)
            if args.smoke_translation:
                from PySide6.QtCore import QObject
                card = window.findChild(QObject, "mainWordCard")
                card.setProperty("translationVisible", True)
                card.setProperty("examplesOpen", True)
            QTimer.singleShot(1700, screenshot)
    code = app.exec()
    tray.hide()
    engine.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    if server:
        server.close()
        lock.unlock()
    return code
