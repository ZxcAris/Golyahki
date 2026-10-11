from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import threading

from PySide6.QtCore import QObject, Signal, Slot, Qt


class _CaptionMover(QObject):
    requested = Signal()

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._pending = {}
        self._scheduled = False
        self._native = ctypes.WinDLL('user32', use_last_error=True) if os.name == 'nt' else None
        if self._native:
            self._native.IsWindowVisible.argtypes = [wintypes.HWND]
            self._native.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        self.requested.connect(self._apply, Qt.ConnectionType.QueuedConnection)

    def move(self, hwnd, x, y):
        # Keep only the current pointer position while the GUI handles input.
        # Never queue a native window move for every mouse sample: stale samples
        # would make the card trail behind the pointer after a fast drag.
        with self._lock:
            self._pending[hwnd] = (x, y)
            if self._scheduled:
                return
            self._scheduled = True
        self.requested.emit()

    @Slot()
    def _apply(self):
        with self._lock:
            pending, self._pending = self._pending, {}
            self._scheduled = False
        for hwnd, (x, y) in pending.items():
            if self._native and self._native.IsWindowVisible(hwnd):
                # Apply directly on the GUI thread, without ASYNCWINDOWPOS,
                # timers or interpolation. A synchronous move inside the mouse
                # hook would deadlock when the GUI is delivering native input.
                self._native.SetWindowPos(hwnd, None, x, y, 0, 0, 0x15)

    def clear(self):
        with self._lock:
            self._pending.clear()


class OverlayMouseGuard:
    """Focus our hovered surface and route clicks without changing async mouse state.

    Low-level hooks do not suppress Raw Input. Foreground Raw Input is isolated by
    activating our surface before a click; games opting into background Raw Input
    must disable that option themselves.
    """

    def __init__(self, activate, move_started=None):
        self.activate = activate
        self.move_started = move_started
        self.focus_on_hover = False
        self.interaction_button = 0
        self.enabled = False
        self.active = False
        self.thread = None
        self.thread_id = 0
        self._caption_mover = _CaptionMover()

    def start(self):
        if self.thread or os.name != 'nt':
            return
        ready, errors = threading.Event(), []

        def listen():
            # Use a private DLL handle: other listeners have their own ctypes signatures.
            native = ctypes.WinDLL('user32', use_last_error=True)
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
            kernel.GetModuleHandleW.restype = wintypes.HMODULE
            self.thread_id = kernel.GetCurrentThreadId()
            native.WindowFromPoint.argtypes = [wintypes.POINT]
            native.WindowFromPoint.restype = wintypes.HWND
            native.GetForegroundWindow.restype = wintypes.HWND
            native.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
            native.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            native.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            native.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            native.GetAsyncKeyState.argtypes = [ctypes.c_int]
            native.GetAsyncKeyState.restype = wintypes.SHORT
            native.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            native.IsWindowVisible.argtypes = [wintypes.HWND]
            native.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM,
                wintypes.LPARAM, wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
            native.SendMessageTimeoutW.restype = wintypes.LPARAM
            native.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
            native.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
            native.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

            class Mouse(ctypes.Structure):
                _fields_ = [('point', wintypes.POINT), ('data', wintypes.DWORD),
                    ('flags', wintypes.DWORD), ('time', wintypes.DWORD), ('extra', ctypes.c_size_t)]

            callback_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            native.SetWindowsHookExW.argtypes = [ctypes.c_int, callback_type, wintypes.HINSTANCE, wintypes.DWORD]
            native.SetWindowsHookExW.restype = wintypes.HHOOK
            native.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            native.CallNextHookEx.restype = ctypes.c_ssize_t
            # Button identity, native key-state mask, matching up message.
            buttons = {0x201: (1, 1, 0x202), 0x204: (2, 2, 0x205),
                0x207: (3, 0x10, 0x208), 0x20b: (4, 0x20, 0x20c)}
            releases = {value[2] for value in buttons.values()}
            held = {}
            last_click = {}
            caption_drags = {}

            def packed(point):
                return (point.x & 0xffff) | ((point.y & 0xffff) << 16)

            def recipient(point):
                hwnd = native.WindowFromPoint(point)
                process = wintypes.DWORD()
                native.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
                return hwnd if process.value == os.getpid() else None

            def focus(hwnd):
                if not self.focus_on_hover:
                    return
                foreground = native.GetForegroundWindow()
                process = wintypes.DWORD()
                native.GetWindowThreadProcessId(foreground, ctypes.byref(process))
                if process.value != os.getpid():
                    # Queue activation on the GUI thread. SetForegroundWindow in
                    # this hook can wait on the GUI, deadlock input, and lose the hook.
                    self.activate(hwnd)

            def state():
                mask = 0
                for _, button_mask, _, _ in held.values():
                    mask |= button_mask
                if native.GetAsyncKeyState(0x10) & 0x8000:
                    mask |= 4
                if native.GetAsyncKeyState(0x11) & 0x8000:
                    mask |= 8
                return mask

            def move_caption(identity, point):
                drag = caption_drags.get(identity)
                if not drag:
                    return False
                if not native.IsWindowVisible(drag['hwnd']):
                    return True
                dx, dy = point.x - drag['press'][0], point.y - drag['press'][1]
                if not drag['moved']:
                    if not dx and not dy:
                        return True
                    drag['moved'] = True
                    if self.move_started:
                        self.move_started(drag['hwnd'])
                # The guard suppresses physical button state, so use screen
                # pixels from the press, applying only the latest position.
                self._caption_mover.move(drag['hwnd'],
                    drag['origin'][0] + dx, drag['origin'][1] + dy)
                return True

            def forward(hwnd, message, mouse, hit=0, double=False):
                if not native.IsWindowVisible(hwnd):
                    return
                if hit == 20:  # HTCLOSE: the system button expects physical button state.
                    if message == 0x202:
                        result = ctypes.c_size_t()
                        if native.SendMessageTimeoutW(hwnd, 0x84, 0, packed(mouse.point), 2, 20, ctypes.byref(result)) and result.value == 20:
                            native.PostMessageW(hwnd, 0x112, 0xf060, 0)  # SC_CLOSE
                    return
                point = wintypes.POINT(mouse.point.x, mouse.point.y)
                if hit:
                    # Native caption/close controls also need protection from the game.
                    message -= 0x160  # WM_*BUTTON to WM_NC*BUTTON.
                    keys = hit
                else:
                    keys = state()
                    if message not in (0x20a, 0x20e):  # Wheel coordinates stay screen-relative.
                        native.ScreenToClient(hwnd, ctypes.byref(point))
                if double:
                    message += 2
                if message in (0x20a, 0x20e, 0x20b, 0x20c, 0x20d, 0xab, 0xac, 0xad):
                    keys |= mouse.data & 0xffff0000
                native.PostMessageW(hwnd, message, keys, packed(point))

            def event(code, message, address):
                if not self.enabled and not held:
                    return native.CallNextHookEx(None, code, message, address)
                if code == 0:
                    mouse = ctypes.cast(address, ctypes.POINTER(Mouse)).contents
                    if message in buttons:
                        identity, mask, release = buttons[message]
                        if identity == 4 and mouse.data >> 16 == 2:
                            identity, mask = 5, 0x40
                        hwnd = recipient(mouse.point) if self.enabled else None
                        if hwnd:
                            focus(hwnd)
                            client = wintypes.POINT(mouse.point.x, mouse.point.y)
                            rect = wintypes.RECT()
                            native.ScreenToClient(hwnd, ctypes.byref(client))
                            native.GetClientRect(hwnd, ctypes.byref(rect))
                            hit = 0
                            if not (0 <= client.x < rect.right and 0 <= client.y < rect.bottom):
                                result = ctypes.c_size_t()
                                # Bound the cross-thread hit test; never wait for a busy UI.
                                if native.SendMessageTimeoutW(hwnd, 0x84, 0, packed(mouse.point), 2, 20, ctypes.byref(result)):
                                    hit = result.value
                            delivered = message
                            if identity in (4, 5) and identity == self.interaction_button:
                                # Remap only inside our UI. Raw Input still carries the
                                # original side button; no system-wide LMB is injected.
                                delivered, mask, release = 0x201, 1, 0x202
                            held[identity] = (hwnd, mask, hit, release)
                            previous = last_click.pop(identity, None)
                            double = bool(previous and previous[0] == hwnd and
                                ((mouse.time - previous[3]) & 0xffffffff) <= native.GetDoubleClickTime() and
                                abs(mouse.point.x - previous[1]) <= native.GetSystemMetrics(36) // 2 and
                                abs(mouse.point.y - previous[2]) <= native.GetSystemMetrics(37) // 2)
                            if not double:
                                last_click[identity] = (hwnd, mouse.point.x, mouse.point.y, mouse.time)
                            window_rect = wintypes.RECT()
                            if (hit == 2 and delivered == 0x201 and not double
                                    and native.GetWindowRect(hwnd, ctypes.byref(window_rect))):
                                caption_drags[identity] = {'hwnd': hwnd,
                                    'press': (mouse.point.x, mouse.point.y),
                                    'origin': (window_rect.left, window_rect.top), 'moved': False}
                            else:
                                forward(hwnd, delivered, mouse, hit, double)
                            return 1
                    elif message in releases:
                        identity = {0x202: 1, 0x205: 2, 0x208: 3, 0x20c: 4}[message]
                        if identity == 4 and mouse.data >> 16 == 2:
                            identity = 5
                        target = held.pop(identity, None)
                        if target:
                            if not move_caption(identity, mouse.point):
                                forward(target[0], target[3], mouse, target[2])
                            caption_drags.pop(identity, None)
                            # Always consume the matching release, even after hiding the overlay
                            # or dragging outside it. Otherwise the game receives half a click.
                            return 1
                    elif message == 0x200 and held:
                        identity, (hwnd, _, hit, _) = next(iter(held.items()))
                        if move_caption(identity, mouse.point):
                            # Let Windows update the real pointer position. Blocking
                            # motion leaves it at the press and makes release jump back.
                            return native.CallNextHookEx(None, code, message, address)
                        forward(hwnd, message, mouse, 0 if not hit else hit)
                        return 1
                    elif self.enabled and self.focus_on_hover and message == 0x200:
                        hwnd = recipient(mouse.point)
                        if hwnd:
                            focus(hwnd)
                    elif self.enabled and message in (0x20a, 0x20e):
                        hwnd = recipient(mouse.point)
                        if hwnd:
                            focus(hwnd)
                            forward(hwnd, message, mouse)
                            return 1
                return native.CallNextHookEx(None, code, message, address)

            procedure = callback_type(event)
            msg = wintypes.MSG()
            native.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
            hook = native.SetWindowsHookExW(14, procedure, kernel.GetModuleHandleW(None), 0)
            if not hook:
                errors.append(RuntimeError('Не удалось включить защиту кликов поверх игры.'))
                ready.set()
                return
            self.active = True
            ready.set()
            try:
                while native.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                    pass
            finally:
                native.UnhookWindowsHookEx(hook)
                self.active = False

        self.thread = threading.Thread(target=listen, name='GOlyah-overlay-mouse', daemon=True)
        self.thread.start()
        if not ready.wait(2):
            raise RuntimeError('Не удалось включить защиту кликов поверх игры.')
        if errors:
            self.thread = None
            raise errors[0]

    def close(self):
        self.enabled = False
        if self.thread and self.thread.is_alive():
            native = ctypes.WinDLL('user32', use_last_error=True)
            native.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
            native.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
            self.thread.join(2)
        self.thread = None
        self.active = False
        self._caption_mover.clear()
