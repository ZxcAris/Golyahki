import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import pytest
from PySide6.QtCore import QUrl, QPointF
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from golyah.bridge import Bridge
from golyah.models import Entry, Sense, Example
from golyah.storage import Storage
from test_hotkeys import Input, MouseInput
from test_qml import visual_child

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Native Windows mouse isolation')
native = ctypes.WinDLL('user32', use_last_error=True)
native.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int]
native.SetForegroundWindow.argtypes = [wintypes.HWND]
native.GetForegroundWindow.restype = wintypes.HWND
native.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
native.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
native.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
native.GetAsyncKeyState.restype = wintypes.SHORT
native.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
native.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
native.SendMessageW.restype = wintypes.LPARAM
native.WindowFromPoint.argtypes = [wintypes.POINT]
native.WindowFromPoint.restype = wintypes.HWND
native.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT]

def activate(hwnd):
    # Establish foreground through a click verified to hit only our test receiver.
    # This also works when Windows' foreground lock prevents programmatic activation.
    native.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x13)
    point = wintypes.POINT(20, 20)
    native.ClientToScreen(hwnd, ctypes.byref(point))
    native.SetCursorPos(point.x, point.y)
    QTest.qWait(40)
    assert native.WindowFromPoint(point) == hwnd
    try:
        mouse(2); mouse(4)
        deadline = time.monotonic() + 2
        while native.GetForegroundWindow() != hwnd and time.monotonic() < deadline:
            QTest.qWait(20)
        assert native.GetForegroundWindow() == hwnd
    finally:
        native.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x13)

def mouse(flags, data=0):
    event = Input()
    event.payload.mouse = MouseInput(0, 0, data, flags, 0, 0)
    sent = []
    sender = threading.Thread(target=lambda: sent.append(native.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input))))
    sender.start()
    deadline = time.monotonic() + 2
    while sender.is_alive() and time.monotonic() < deadline:
        QTest.qWait(5)
        # QTest's native wait can retain the GIL. Give the SendInput sender and
        # Python WH_MOUSE_LL callback a turn instead of starving the hook.
        time.sleep(.001)
    sender.join(.1)
    assert sent == [1]
    QTest.qWait(65)

def cursor(window, x, y):
    point = wintypes.POINT(round(x * window.devicePixelRatio()), round(y * window.devicePixelRatio()))
    native.ClientToScreen(int(window.winId()), ctypes.byref(point))
    screen_cursor(point.x, point.y)


def screen_motion(x, y):
    event = Input()
    event.payload.mouse = MouseInput(
        round((x - native.GetSystemMetrics(76)) * 65535 / (native.GetSystemMetrics(78) - 1)),
        round((y - native.GetSystemMetrics(77)) * 65535 / (native.GetSystemMetrics(79) - 1)),
        0, 0xc001, 0, 0)
    return event


def screen_cursor(x, y):
    # Actual native mouse movement, unlike SetCursorPos, passes through WH_MOUSE_LL.
    event = screen_motion(x, y)
    assert native.SendInput(1, ctypes.byref(event), ctypes.sizeof(Input)) == 1
    QTest.qWait(40)

@pytest.fixture
def receiver(request):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    previous = native.GetForegroundWindow()
    args = [sys.executable, str(Path(__file__).with_name('input_receiver.py'))]
    if getattr(request, 'param', False): args.append('--background')
    process = subprocess.Popen(args,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    reports = queue.Queue()
    threading.Thread(target=lambda: [reports.put(json.loads(line)) for line in process.stdout], daemon=True).start()
    def command(value):
        process.stdin.write(value + '\n'); process.stdin.flush()
        deadline = time.monotonic() + 4
        while reports.empty() and time.monotonic() < deadline: QTest.qWait(20)
        return reports.get_nowait()
    try:
        deadline = time.monotonic() + 8
        while reports.empty() and time.monotonic() < deadline: QTest.qWait(20)
        hwnd = reports.get_nowait()['hwnd']
        activate(hwnd)
        QTest.qWait(150)
        yield hwnd, command
    finally:
        if process.poll() is None:
            process.stdin.write('quit\n'); process.stdin.flush()
        process.wait(timeout=4)
        errors = process.stderr.read()
        assert process.returncode == 0, errors
        native.SetForegroundWindow(previous)

@pytest.mark.parametrize('focus_on_hover', [False, True])
@pytest.mark.parametrize('receiver', [False, True], indirect=True, ids=['foreground-raw', 'background-raw'])
def test_native_card_clicks_and_raw_input(tmp_path, receiver, focus_on_hover, request):
    hwnd, report = receiver
    bridge = Bridge(Storage(tmp_path / 'mouse.sqlite'))
    guard = bridge.overlayMouse
    bridge.setOverlayMouseButton('none')
    bridge.setFocusOnHover(focus_on_hover)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]
    popup = main.findChild(QQuickWindow, 'wordPopup')
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    main.hide()
    entry = Entry(word='experience', pos='v', dictionary='test', senses=[
        Sense(translation='испытывать', examples=[Example(en='We experience it.', ru='Мы испытываем это.')])])
    bridge.record.term = 'experience'; bridge.record.sentence = 'We experience it.'
    bridge.record.entries = [entry]; bridge.record.select_defaults()
    bridge._overlay.update(passive=True, visible=True, left=70, top=90, width=600, height=550)
    bridge.overlayChanged.emit(); bridge.cardChanged.emit()
    popup.setPosition(160, 140); popup.show()
    QTest.qWait(180)
    activate(hwnd)
    guard.start(); guard.enabled = True
    card = visual_child(popup.contentItem(), 'popupWordCard')
    def click_item(name):
        button = visual_child(popup.contentItem(), name)
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
        cursor(popup, point.x(), point.y())
        pointer = wintypes.POINT()
        native.GetCursorPos(ctypes.byref(pointer))
        under_pointer = native.WindowFromPoint(pointer)
        assert under_pointer == int(popup.winId()), (name, under_pointer, int(popup.winId()))
        mouse(2)
        assert not native.GetAsyncKeyState(1) & 0x8000, (
            name, guard.active, guard.enabled, native.GetForegroundWindow(), int(popup.winId()))
        mouse(4)
    try:
        # Establish all three observer paths really detect an ordinary native click.
        native.SetCursorPos(850, 600); QTest.qWait(40)
        report('reset'); guard.enabled = False
        mouse(2); mouse(4)
        baseline = report('report')
        assert baseline['polled_down'] == 1 and baseline['down'] == 1 and baseline['up'] == 1, baseline
        assert baseline['raw_down'] == 1 and baseline['raw_up'] == 1, baseline
        guard.enabled = True; report('reset')
        click_item('showTranslation')
        deadline = time.monotonic() + 2
        while not card.property('translationVisible') and time.monotonic() < deadline:
            QTest.qWait(20)
        assert card.property('translationVisible')
        if focus_on_hover:
            assert native.GetForegroundWindow() in (int(popup.winId()), int(overlay.winId()))
        else:
            assert native.GetForegroundWindow() == hwnd
        click_item('senseExamplesToggle_0')
        assert visual_child(popup.contentItem(), 'senseExamples_0').isVisible()
        received = report('report')
        assert received['down'] == received['up'] == received['polled_down'] == 0, received
        # Raw Input bypasses low-level hooks. Test and document the honest boundary:
        # focus-on-hover isolates foreground Raw Input; passive mode does not.
        background = request.node.callspec.params['receiver']
        assert received['raw_down'] == received['raw_up'] == (0 if focus_on_hover and not background else 2), received

        # Drag the ordinary Windows caption, without a client-area drag control.
        popup.setPosition(600, 120)
        QTest.qWait(50)
        assert visual_child(popup.contentItem(), 'popupDragHandle') is None
        rect = wintypes.RECT()
        native.GetWindowRect(int(popup.winId()), ctypes.byref(rect))
        client_origin = wintypes.POINT(0, 0)
        native.ClientToScreen(int(popup.winId()), ctypes.byref(client_origin))
        caption = ((rect.left + rect.right)//2, (rect.top + client_origin.y)//2)
        packed = (caption[0] & 0xffff) | ((caption[1] & 0xffff) << 16)
        assert native.SendMessageW(int(popup.winId()), 0x84, 0, packed) == 2
        screen_cursor(*caption)
        report('reset')
        before = popup.position()
        mouse(2)
        ratio = popup.devicePixelRatio()
        for dx, dy in [(-1,0), (-20,10), (-60,30), (-100,50)]:
            expected = (caption[0] + round(dx*ratio), caption[1] + round(dy*ratio))
            screen_cursor(*expected)
            pointer = wintypes.POINT()
            native.GetCursorPos(ctypes.byref(pointer))
            assert abs(pointer.x - expected[0]) <= 2 and abs(pointer.y - expected[1]) <= 2
            assert abs(popup.x() - before.x() - dx) <= 3
            assert abs(popup.y() - before.y() - dy) <= 3
            if dx == -1:
                # Even the first screen pixel moves the window, without a dead zone.
                moved = wintypes.RECT()
                native.GetWindowRect(int(popup.winId()), ctypes.byref(moved))
                assert moved.left == rect.left + pointer.x - caption[0]
                assert moved.top == rect.top + pointer.y - caption[1]
                assert popup.property('manuallyPlaced')
        # A busy GUI must resume at the latest mouse position, without replaying
        # old positions or continuing to animate after the pointer stops.
        steps = [(caption[0] + round(dx*ratio), caption[1] + round((50 + i%4)*ratio))
                 for i, dx in enumerate(range(-101, -221, -1))]
        inputs = (Input * len(steps))(*(screen_motion(*point) for point in steps))
        sent = []
        sender = threading.Thread(target=lambda: sent.append(
            native.SendInput(len(inputs), inputs, ctypes.sizeof(Input))))
        sender.start()
        deadline = time.monotonic() + 3
        while sender.is_alive() and time.monotonic() < deadline:
            time.sleep(.005)  # Allow the hook to run while the GUI is deliberately busy.
        sender.join(.1)
        assert sent == [len(steps)]
        QApplication.processEvents()
        moved = wintypes.RECT()
        native.GetWindowRect(int(popup.winId()), ctypes.byref(moved))
        pointer = wintypes.POINT()
        native.GetCursorPos(ctypes.byref(pointer))
        assert moved.left == rect.left + pointer.x - caption[0]
        assert moved.top == rect.top + pointer.y - caption[1]
        final_position = popup.position()
        mouse(4)
        assert popup.property('manuallyPlaced')
        assert popup.position() == final_position
        received = report('report')
        assert received['down'] == received['up'] == received['polled_down'] == 0, received
        position = popup.position()
        bridge.cardChanged.emit()
        QTest.qWait(50)
        assert popup.position() == position

        # Release ownership survives leaving our window and disabling the guard.
        report('reset')
        cursor(popup, 25, 25)
        mouse(2)
        native.SetCursorPos(850, 700); QTest.qWait(40)
        guard.enabled = False
        mouse(4)
        received = report('report')
        assert received['down'] == received['up'] == received['polled_down'] == 0, received
        guard.enabled = True

        # Wheel and the other buttons do not update the game's polled mouse state.
        popup.setPosition(600, 120)
        entry.senses[0].examples = [Example(en=f'Example sentence {i}.', ru=f'Пример {i}.') for i in range(20)]
        bridge.cardChanged.emit(); QTest.qWait(100)
        scroller = card.property('contentItem')
        assert card.property('naturalHeight') > card.height()
        scroller.setProperty('contentY', 0)
        cursor(popup, 350, 220)
        mouse(0x800, (0x100000000 - 120))
        QTest.qWait(220)
        assert scroller.property('contentY') > 0
        report('reset')
        for down, up, vk, data in [(8, 16, 2, 0), (32, 64, 4, 0),
                (0x80, 0x100, 5, 1), (0x80, 0x100, 6, 2)]:
            mouse(down, data)
            assert not native.GetAsyncKeyState(vk) & 0x8000
            mouse(up, data)
        assert report('report')['polled_down'] == 0

        # A closing overlay click is consumed as a complete pair; normal input
        # resumes afterward, including releases of presses that began outside it.
        popup.hide()
        bridge._previous_window = hwnd
        cursor(overlay, 40, 400)
        report('reset'); mouse(2); mouse(4)
        assert not bridge.overlay['visible'] and not guard.enabled
        assert report('report')['polled_down'] == 0
        report('reset')
        mouse(2); mouse(4)
        received = report('report')
        assert received['polled_down'] == received['down'] == received['up'] == 1, received

        # This preference is persisted independently of the other settings.
        reloaded = Bridge(Storage(tmp_path / 'mouse.sqlite'))
        assert reloaded.settings['focusOnHover'] == focus_on_hover
        reloaded.close()

        # Native close on the main window remains usable while an overlay is open.
        bridge._overlay['visible'] = True; bridge.overlayChanged.emit()
        main.setPosition(50, 60); main.show(); main.raise_(); QTest.qWait(100)
        native.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        rect = wintypes.RECT(); native.GetWindowRect(int(main.winId()), ctypes.byref(rect))
        native.SetCursorPos(rect.right - 20, rect.top + 15); QTest.qWait(50)
        native.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        assert native.SendMessageW(int(main.winId()), 0x84, 0,
            ((rect.right - 20) & 0xffff) | (((rect.top + 15) & 0xffff) << 16)) == 20
        mouse(2); mouse(4)
        deadline = time.monotonic() + 2
        while main.isVisible() and time.monotonic() < deadline:
            QTest.qWait(20)
        assert not main.isVisible()
    finally:
        mouse(4)
        guard.close(); bridge.close()
        for window in [overlay, popup, main]: window.close()
        engine.deleteLater(); QTest.qWait(30)
    assert guard.thread is None and not guard.active


@pytest.mark.parametrize('button, data, other', [('mouse4', 1, 'mouse5'), ('mouse5', 2, 'mouse4')])
def test_native_side_button_selects_words_and_operates_card(tmp_path, receiver, button, data, other):
    hwnd, report = receiver
    bridge = Bridge(Storage(tmp_path/'side.sqlite'))
    bridge.dictionary.ensure_builtin()
    bridge.setOverlayMouseButton(button)
    guard = bridge.overlayMouse
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    popup = main.findChild(QQuickWindow, 'wordPopup')
    main.hide()
    bridge._overlay.update(passive=True, visible=True, stage='ready', left=60, top=80,
        width=900, height=650, pixelWidth=900, pixelHeight=650)
    bridge.set_ocr_words([{'id': i, 'text': text, 'polygon': [[x,90],[x+80,90],[x+80,122],[x,122]],
        'confidence': 1, 'line': 0, 'block': 0} for i,(text,x) in enumerate([('Nah,',90),('thanks.',200)])])
    bridge.overlayChanged.emit(); QTest.qWait(120)
    activate(hwnd); guard.start()
    def click(name, down=0x80, up=0x100, value=data):
        item = visual_child(popup.contentItem(), name)
        point = item.mapToScene(QPointF(item.width()/2, item.height()/2))
        cursor(popup, point.x(), point.y())
        mouse(down, value)
        assert not native.GetAsyncKeyState(1) & 0x8000
        mouse(up, value)
    try:
        report('reset')
        cursor(overlay, 130, 106); mouse(0x80, data); mouse(0x100, data)
        assert popup.isVisible() and bridge.record.term == 'Nah'
        assert bridge.record.translation == 'неа; нет'
        assert bridge.overlay['selected'] == [0]
        card = visual_child(popup.contentItem(), 'popupWordCard')
        click('showTranslation')
        assert card.property('translationVisible')
        click('senseExamplesToggle_0')
        assert visual_child(popup.contentItem(), 'senseExamples_0').isVisible()
        received = report('report')
        assert received['raw_left_down'] == received['raw_left_up'] == received['polled_down'] == 0, received
        assert received['raw_side_down'] == received['raw_side_up'] == 3, received
        assert native.GetForegroundWindow() == hwnd

        # The unconfigured side button does not act as LMB, and LMB still works.
        click('showTranslation', value=2 if data == 1 else 1)
        assert card.property('translationVisible')
        click('showTranslation', down=2, up=4, value=0)
        assert not card.property('translationVisible')

        # Keep the down/up mapping stable if the setting changes while held.
        item = visual_child(popup.contentItem(), 'showTranslation')
        point = item.mapToScene(QPointF(item.width()/2,item.height()/2))
        cursor(popup, point.x(), point.y()); mouse(0x80, data)
        bridge.setOverlayMouseButton(other); mouse(0x100, data)
        assert card.property('translationVisible')
        bridge.setOverlayMouseButton(button)
        bridge.setOverlayMouseButton('invalid')
        assert bridge.settings['overlayMouseButton'] == button
        reloaded = Bridge(Storage(tmp_path/'side.sqlite'))
        assert reloaded.overlayMouse.interaction_button == (4 if data == 1 else 5)
        reloaded.close()

        # A native Ctrl+side-button extends the same selection as Ctrl+LMB.
        from test_hotkeys import KeyboardInput
        event = Input(); event.type = 1; event.payload.key = KeyboardInput(0x11,0,0,0,0)
        assert native.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input)) == 1
        QTest.qWait(30)
        cursor(overlay,240,106); mouse(0x80,data); mouse(0x100,data)
        event.payload.key.flags = 2
        assert native.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input)) == 1
        QTest.qWait(30)
        assert bridge.overlay['selected'] == [0,1]
        assert bridge.record.term == 'Nah, thanks'
    finally:
        from test_hotkeys import KeyboardInput
        event = Input(); event.type = 1; event.payload.key = KeyboardInput(0x11,0,2,0,0)
        native.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input))
        mouse(0x100,data); mouse(4)
        guard.close(); bridge.close()
        for window in [overlay,popup,main]: window.close()
        engine.deleteLater(); QTest.qWait(30)
