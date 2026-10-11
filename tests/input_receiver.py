"""Separate foreground process for native mouse isolation tests (never a real game)."""
import ctypes
from ctypes import wintypes
import json
import queue
import sys
import threading

from PySide6.QtCore import QAbstractNativeEventFilter, QTimer, Qt
from PySide6.QtWidgets import QApplication, QWidget, QLabel

native = ctypes.WinDLL('user32', use_last_error=True)
native.GetAsyncKeyState.restype = wintypes.SHORT
native.GetRawInputData.argtypes = [wintypes.HANDLE, wintypes.UINT, ctypes.c_void_p,
    ctypes.POINTER(wintypes.UINT), wintypes.UINT]

class Device(ctypes.Structure):
    _fields_ = [('page', wintypes.USHORT), ('usage', wintypes.USHORT),
        ('flags', wintypes.DWORD), ('target', wintypes.HWND)]

class Header(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('size', wintypes.DWORD),
        ('device', wintypes.HANDLE), ('param', wintypes.WPARAM)]

counts = {'down': 0, 'up': 0, 'wheel': 0, 'raw_down': 0, 'raw_up': 0,
    'raw_wheel': 0, 'polled_down': 0, 'raw_left_down': 0, 'raw_left_up': 0,
    'raw_side_down': 0, 'raw_side_up': 0}
held = False
commands = queue.Queue()

class Filter(QAbstractNativeEventFilter):
    def nativeEventFilter(self, event_type, address):
        msg = wintypes.MSG.from_address(int(address))
        if msg.message in (0x201, 0x204, 0x207, 0x20b): counts['down'] += 1
        elif msg.message in (0x202, 0x205, 0x208, 0x20c): counts['up'] += 1
        elif msg.message in (0x20a, 0x20e): counts['wheel'] += 1
        elif msg.message == 0xff:
            size = wintypes.UINT()
            native.GetRawInputData(msg.lParam, 0x10000003, None, ctypes.byref(size), ctypes.sizeof(Header))
            buffer = (ctypes.c_ubyte * size.value)()
            native.GetRawInputData(msg.lParam, 0x10000003, buffer, ctypes.byref(size), ctypes.sizeof(Header))
            header = Header.from_buffer(buffer)
            if header.type == 0:
                flags = ctypes.c_ushort.from_buffer(buffer, ctypes.sizeof(Header) + 4).value
                if flags & 0x155: counts['raw_down'] += 1
                if flags & 0x2aa: counts['raw_up'] += 1
                if flags & 0xc00: counts['raw_wheel'] += 1
                if flags & 1: counts['raw_left_down'] += 1
                if flags & 2: counts['raw_left_up'] += 1
                if flags & 0x140: counts['raw_side_down'] += 1
                if flags & 0x280: counts['raw_side_up'] += 1
        return False, 0

app = QApplication([])
window = QWidget()
window.setWindowTitle('GOlyah mouse input test receiver')
window.setGeometry(60, 80, 900, 650)
if '--fullscreen' in sys.argv:
    window.setWindowFlags(Qt.WindowType.FramelessWindowHint)
    window.setStyleSheet('background: #202428; color: white;')
    label = QLabel('We experience new things every day.', window)
    label.setStyleSheet('font-size: 44px;')
    label.setGeometry(100, 420, 1200, 90)
    window.showFullScreen()
else:
    window.show()
window.activateWindow()
event_filter = Filter()
app.installNativeEventFilter(event_filter)
device = Device(1, 2, 0x100 if '--background' in sys.argv else 0, int(window.winId()))
native.RegisterRawInputDevices.argtypes = [ctypes.POINTER(Device), wintypes.UINT, wintypes.UINT]
assert native.RegisterRawInputDevices(ctypes.byref(device), 1, ctypes.sizeof(Device))

def read_commands():
    for line in sys.stdin: commands.put(line.strip())

def tick():
    global held
    pressed = any(native.GetAsyncKeyState(vk) & 0x8000 for vk in (1, 2, 4, 5, 6))
    if pressed and not held: counts['polled_down'] += 1
    held = pressed
    while not commands.empty():
        command = commands.get_nowait()
        if command == 'report': print(json.dumps(counts), flush=True)
        elif command == 'reset':
            for key in counts: counts[key] = 0
            held = False
            print(json.dumps(counts), flush=True)
        elif command == 'quit': app.quit()

threading.Thread(target=read_commands, daemon=True).start()
timer = QTimer(); timer.timeout.connect(tick); timer.start(2)
print(json.dumps({'hwnd': int(window.winId())}), flush=True)
app.exec()
