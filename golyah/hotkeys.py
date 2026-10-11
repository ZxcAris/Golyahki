from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading

from .windows import parse_hotkey


class HotkeyListener:
    """Deliver capture and optional selection chords from one Windows message thread."""
    def __init__(self, callback, selection_callback=None):
        self.callback = callback
        self.selection_callback = selection_callback
        self.selection_is_primary = False
        self.active = False
        self.using_hook = False
        self.thread = None
        self.thread_id = 0
        self.trigger_count = 0

    def register(self, value):
        if os.name != 'nt':
            return
        mods, key = parse_hotkey(value)
        self.close()
        bindings = {(mods & 0x0f, key): (491, mods, self.callback)}
        selection_mods, selection_key = parse_hotkey('Ctrl+Alt+Q')
        self.selection_is_primary = self.selection_callback is not None and (mods, key) == (selection_mods, selection_key)
        if self.selection_callback is not None:
            bindings[(selection_mods & 0x0f, selection_key)] = (492, selection_mods, self.selection_callback)
        ready, errors = threading.Event(), []
        def listen():
            from .windows import user32
            kernel = ctypes.WinDLL('kernel32')
            kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel.GetModuleHandleW.restype = wintypes.HMODULE
            self.thread_id = kernel.GetCurrentThreadId()
            user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            msg = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            registered, fallback = {}, {}
            for (modifiers, code), (identifier, flags, callback) in bindings.items():
                if user32.RegisterHotKey(None, identifier, flags, code):
                    registered[identifier] = callback
                else:
                    fallback[(modifiers, code)] = callback
            hook, procedure = None, None
            self.using_hook = bool(fallback)
            if fallback:
                class Keyboard(ctypes.Structure):
                    _fields_ = [('vk', wintypes.DWORD), ('scan', wintypes.DWORD),
                                ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
                callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
                user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
                user32.CallNextHookEx.restype = ctypes.c_ssize_t
                user32.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
                user32.SetWindowsHookExW.restype = wintypes.HHOOK
                user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
                user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
                user32.GetAsyncKeyState.restype = wintypes.SHORT
                modifier_codes = {0x11:2, 0xa2:2, 0xa3:2, 0x10:4, 0xa0:4, 0xa1:4,
                                  0x12:1, 0xa4:1, 0xa5:1, 0x5b:8, 0x5c:8}
                # Initialize outside the callback; then track only modifier state.
                held = {vk for vk in modifier_codes if vk >= 0x5b and user32.GetAsyncKeyState(vk) & 0x8000}
                pressed = set()
                def keyboard_event(code, message, address):
                    if code == 0:
                        event = ctypes.cast(address, ctypes.POINTER(Keyboard)).contents
                        up = message in (0x101, 0x105)
                        if event.vk in modifier_codes:
                            held.discard(event.vk) if up else held.add(event.vk)
                        else:
                            if up and event.vk in pressed:
                                pressed.discard(event.vk)
                                return 1
                            current = 0
                            for vk in held:
                                current |= modifier_codes[vk]
                            if event.flags & 0x20:
                                current |= 1
                            callback = fallback.get((current, event.vk))
                            if not up and callback is not None:
                                if event.vk not in pressed:
                                    pressed.add(event.vk)
                                    self.trigger_count += 1
                                    callback()
                                # Consume this chord so another app cannot also open an overlay.
                                return 1
                    return user32.CallNextHookEx(None, code, message, address)
                procedure = callback_type(keyboard_event)
                hook = user32.SetWindowsHookExW(13, procedure, kernel.GetModuleHandleW(None), 0)
                if not hook:
                    for identifier in registered:
                        user32.UnregisterHotKey(None, identifier)
                    errors.append(RuntimeError('Не удалось включить ' + value + '. Выберите другую горячую клавишу в настройках.'))
                    ready.set()
                    return
            self.active = True
            ready.set()
            try:
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    if msg.message == 0x0312 and msg.wParam in registered:
                        self.trigger_count += 1
                        registered[msg.wParam]()
            finally:
                if hook:
                    user32.UnhookWindowsHookEx(hook)
                for identifier in registered:
                    user32.UnregisterHotKey(None, identifier)
                self.active = False
        self.thread = threading.Thread(target=listen, name='GOlyah-hotkey', daemon=True)
        self.thread.start()
        if not ready.wait(2):
            raise RuntimeError('Не удалось зарегистрировать горячую клавишу.')
        if errors:
            raise errors[0]

    def close(self):
        if self.thread and self.thread.is_alive():
            from .windows import user32
            user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(2)
        self.active = False
        self.thread = None


class OverlayKeyboardListener:
    """Handle Esc while the overlay is visible, regardless of keyboard focus."""
    def __init__(self, callback):
        self.callback = callback
        self.enabled = False
        self.thread = None
        self.thread_id = 0
        self._escape_held = False

    def handle_key(self, key, up):
        if key != 0x1b:
            return False
        if self._escape_held:
            if up:
                self._escape_held = False
            # Finish the consumed press even after closing restores another app.
            return True
        if not self.enabled or up:
            return False
        self._escape_held = True
        self.callback(key)
        return True

    def start(self):
        if self.thread or os.name != 'nt':
            return
        ready = threading.Event()
        def listen():
            from .windows import user32
            kernel = ctypes.WinDLL('kernel32')
            kernel.GetModuleHandleW.restype = wintypes.HMODULE
            self.thread_id = kernel.GetCurrentThreadId()
            class Keyboard(ctypes.Structure):
                _fields_ = [('vk', wintypes.DWORD), ('scan', wintypes.DWORD),
                            ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]
            procedure_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, procedure_type, wintypes.HINSTANCE, wintypes.DWORD]
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            def event(code, message, address):
                if code == 0:
                    key = ctypes.cast(address, ctypes.POINTER(Keyboard)).contents.vk
                    up = message in (0x101, 0x105)
                    if self.handle_key(key, up):
                        return 1
                return user32.CallNextHookEx(None, code, message, address)
            procedure = procedure_type(event)
            hook = user32.SetWindowsHookExW(13, procedure, kernel.GetModuleHandleW(None), 0)
            ready.set()
            if not hook:
                return
            try:
                msg = wintypes.MSG()
                while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    pass
            finally:
                user32.UnhookWindowsHookEx(hook)
        self.thread = threading.Thread(target=listen, name='GOlyah-overlay-keys', daemon=True)
        self.thread.start()
        ready.wait(2)

    def close(self):
        self.enabled = False
        if self.thread and self.thread.is_alive():
            from .windows import user32
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)
            self.thread.join(2)
        self.thread = None

