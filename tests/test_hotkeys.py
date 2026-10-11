import ctypes
from ctypes import wintypes
import os
import time

import pytest

from golyah.hotkeys import HotkeyListener
from golyah.windows import user32


pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Native Windows hotkey delivery')


class KeyboardInput(ctypes.Structure):
    _fields_ = [('vk',wintypes.WORD), ('scan',wintypes.WORD), ('flags',wintypes.DWORD),
                ('time',wintypes.DWORD), ('extra',ctypes.c_size_t)]


class MouseInput(ctypes.Structure):
    _fields_ = [('x',wintypes.LONG), ('y',wintypes.LONG), ('data',wintypes.DWORD),
                ('flags',wintypes.DWORD), ('time',wintypes.DWORD), ('extra',ctypes.c_size_t)]


class InputPayload(ctypes.Union):
    _fields_ = [('key',KeyboardInput), ('mouse',MouseInput)]


class Input(ctypes.Structure):
    _fields_ = [('type',wintypes.DWORD), ('payload',InputPayload)]


def press(modifiers, vk, repeat=False):
    # Call through a separate handle so tests do not change the app's ctypes prototypes.
    native = ctypes.WinDLL('user32', use_last_error=True)
    native.SendInput.argtypes = [wintypes.UINT,ctypes.POINTER(Input),ctypes.c_int]
    def key(code, up=False):
        event = Input()
        event.type = 1
        event.payload.key = KeyboardInput(code,0,2 if up else 0,0,0)
        assert native.SendInput(1,ctypes.byref(event),ctypes.sizeof(Input)) == 1
        time.sleep(.025)
    try:
        for code in modifiers: key(code)
        key(vk)
        if repeat: key(vk)
    finally:
        key(vk, True)
        for code in reversed(modifiers): key(code, True)


def delivered(received, expected):
    deadline = time.monotonic() + 2
    while len(received) < len(expected) and time.monotonic() < deadline:
        time.sleep(.02)
    time.sleep(.05)
    assert received == expected


@pytest.mark.parametrize('force_hook', [False, True])
def test_native_capture_and_selection_hotkeys_dispatch_once(monkeypatch, force_hook):
    if force_hook:
        monkeypatch.setattr(user32, 'RegisterHotKey', lambda *args: False)
    received = []
    listener = HotkeyListener(lambda: received.append('capture'), lambda: received.append('select'))
    try:
        listener.register('Alt+F23')
        assert listener.active and not listener.selection_is_primary
        press([0x12], 0x86, repeat=True)
        press([0x11,0x12], ord('Q'), repeat=True)
        delivered(received, ['capture','select'])
        assert listener.trigger_count == 2
        if force_hook: assert listener.using_hook
        # Identical configured and selection chords dispatch only one callback.
        listener.register(' ctrl + alt + q ')
        assert listener.selection_is_primary
        press([0x11,0x12], ord('Q'))
        delivered(received, ['capture','select','select'])
        listener.register('Alt+F23')
        assert not listener.selection_is_primary
        press([0x12], 0x86)
        delivered(received, ['capture','select','select','capture'])
    finally:
        listener.close()
    assert listener.thread is None and not listener.active
