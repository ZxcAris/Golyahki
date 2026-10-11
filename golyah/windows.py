from __future__ import annotations

import ctypes
import os
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass

import numpy as np

if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
    user32.MonitorFromPoint.restype = wintypes.HMONITOR
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HMONITOR
    user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]


@dataclass
class CaptureTarget:
    mode: str
    monitor: int
    left: int
    top: int
    width: int
    height: int
    hwnd: int = 0
    title: str = ""
    fullscreen: bool = False
    backend: str = ''
    settle_ms: int = 70


def monitors():
    result = []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                      ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
    def visit(handle, hdc, rect, data):
        r = rect.contents
        result.append((int(handle), r.left, r.top, r.right - r.left, r.bottom - r.top))
        return True
    callback = callback_type(visit)
    user32.EnumDisplayMonitors(None, None, callback, 0)
    return result


def monitor_name(handle):
    class Info(ctypes.Structure):
        _fields_ = [('cbSize', wintypes.DWORD), ('rcMonitor', wintypes.RECT),
                    ('rcWork', wintypes.RECT), ('dwFlags', wintypes.DWORD),
                    ('szDevice', wintypes.WCHAR * 32)]
    info = Info()
    info.cbSize = ctypes.sizeof(info)
    user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    if user32.GetMonitorInfoW(handle, ctypes.byref(info)):
        return info.szDevice
    return ''


def screen_sources():
    """Stable display names identify sources even when enumeration order changes."""
    items = []
    primary = user32.MonitorFromPoint(wintypes.POINT(0, 0), 1)
    for index, (handle, left, top, width, height) in enumerate(monitors()):
        name = monitor_name(handle)
        items.append({'id': name, 'label': f'Экран {index + 1} · {width} × {height}' +
                      (' · основной' if handle == primary else ''), 'primary': handle == primary,
                      'left': left, 'top': top, 'width': width, 'height': height})
    return items


def window_sources():
    """List ordinary visible top-level windows, including minimized windows."""
    items = []
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    dwm = ctypes.WinDLL('dwmapi')
    dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, data):
        if not user32.IsWindowVisible(hwnd) or user32.GetWindowLongPtrW(hwnd, -20) & 0x80:
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == os.getpid():
            return True
        title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
        user32.GetWindowTextW(hwnd, title, len(title))
        if not title.value.strip():
            return True
        cloaked = wintypes.DWORD()
        if dwm.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked)) == 0 and cloaked.value:
            return True
        minimized = bool(user32.IsIconic(hwnd))
        items.append({'id': f'{pid.value}:{int(hwnd)}', 'hwnd': int(hwnd), 'pid': pid.value,
                      'title': title.value, 'minimized': minimized,
                      'label': title.value + (' · свёрнуто' if minimized else '')})
        return True
    user32.EnumWindows(callback_type(visit), 0)
    return sorted(items, key=lambda item: item['title'].casefold())


def activate_source_window(source_id: str):
    try:
        pid, hwnd = map(int, source_id.split(':'))
    except (ValueError, AttributeError):
        raise ValueError('Выберите окно в настройках захвата.') from None
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    actual_pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(actual_pid))
    if not user32.IsWindow(hwnd) or actual_pid.value != pid or pid == os.getpid():
        raise ValueError('Выбранное окно закрыто. Обновите список и выберите окно в настройках.')
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, 9)
    if foreground_window() == hwnd:
        return hwnd
    user32.BringWindowToTop(hwnd)
    if not user32.SetForegroundWindow(hwnd) and foreground_window() != hwnd:
        raise ValueError('Не удалось открыть выбранное окно поверх других окон. Активируйте его и повторите Alt+Q.')
    return hwnd


def selected_target(mode: str, source_id: str):
    if mode == 'window':
        try:
            was_minimized=bool(user32.IsIconic(int(source_id.split(':')[1])))
        except (ValueError,AttributeError,IndexError):
            was_minimized=False
        hwnd = activate_source_window(source_id)
        target=target_under_cursor('window', hwnd)
        target.settle_ms=280 if was_minimized else 70
        return target
    for index, (handle, left, top, width, height) in enumerate(monitors()):
        if monitor_name(handle) == source_id:
            return CaptureTarget('monitor', index + 1, left, top, width, height)
    raise ValueError('Выбранный экран отключён. Обновите список экранов в настройках.')


def overlay_geometry(target, physical_monitor, logical_origin, ratio):
    return (logical_origin[0] + (target.left - physical_monitor[1]) / ratio,
            logical_origin[1] + (target.top - physical_monitor[2]) / ratio,
            target.width / ratio, target.height / ratio)


def target_under_cursor(mode: str, window_hwnd: int | None = None) -> CaptureTarget:
    if os.name != "nt":
        raise RuntimeError("Захват экрана поддерживается в Windows.")
    point = wintypes.POINT()
    user32.GetCursorPos(ctypes.byref(point))
    handle = user32.MonitorFromPoint(point, 2)
    choices = monitors()
    index, monitor = next(((i, m) for i, m in enumerate(choices) if m[0] == handle), (0, choices[0]))
    _, left, top, width, height = monitor
    if mode == "window":
        hwnd = window_hwnd or user32.GetForegroundWindow()
        user32.IsWindow.argtypes = [wintypes.HWND]
        user32.IsIconic.argtypes = [wintypes.HWND]
        if not hwnd or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
            raise ValueError('Окно закрыто или свёрнуто. Активируйте нужное приложение и повторите захват.')
        window_monitor = user32.MonitorFromWindow(hwnd, 2)
        index = next((i for i, m in enumerate(choices) if m[0] == window_monitor), index)
        rect = wintypes.RECT()
        # Extended frame bounds exclude invisible resize borders.
        try:
            dwm = ctypes.WinDLL("dwmapi")
            dwm.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
            status = dwm.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(rect), ctypes.sizeof(rect))
            if status:
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
        except OSError:
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
        length = user32.GetWindowTextLengthW(hwnd)
        title = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title, length + 1)
        return CaptureTarget(mode, index + 1, rect.left, rect.top,
                             rect.right - rect.left, rect.bottom - rect.top, int(hwnd), title.value)
    return CaptureTarget(mode, index + 1, left, top, width, height)


def fullscreen_window(hwnd: int, target: CaptureTarget) -> bool:
    if not hwnd or user32.IsIconic(hwnd):
        return False
    rect = wintypes.RECT()
    if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    _, left, top, width, height = monitors()[target.monitor - 1]
    # Some games retain a slightly inset HWND while presenting an immersive frame.
    # Treat nearly full-monitor windows conservatively to avoid deactivating them.
    return (abs(rect.left - left) <= max(8, width * .025) and
            abs(rect.top - top) <= max(8, height * .025) and
            abs(rect.right - left - width) <= max(8, width * .025) and
            abs(rect.bottom - top - height) <= max(8, height * .025))


_capture_lock = threading.Lock()


def dxgi_outputs():
    """Map Windows display names to DXGI outputs, including multiple adapters."""
    from dxcam.util.io import enum_dxgi_adapters, enum_dxgi_outputs
    from dxcam.core.output import Output
    devices, device_index = {}, 0
    for adapter in enum_dxgi_adapters():
        outputs = enum_dxgi_outputs(adapter)
        if not outputs:
            continue
        for output_index, pointer in enumerate(outputs):
            devices[Output(pointer).devicename.casefold()] = (device_index, output_index)
        device_index += 1
    return devices


def capture_dxgi(target: CaptureTarget) -> np.ndarray:
    """Acquire DirectX surfaces and crop the chosen window in physical coordinates."""
    import comtypes
    initialized = False
    try:
        comtypes.CoInitialize()
        initialized = True
    except OSError as exc:
        if exc.winerror != -2147417850:  # RPC_E_CHANGED_MODE: Qt already initialized COM.
            raise
    try:
        import dxcam
        with _capture_lock:
            outputs = dxgi_outputs()
            frame = np.zeros((target.height, target.width, 4), dtype=np.uint8)
            frame[:, :, 3] = 255
            covered = False
            for handle, left, top, width, height in monitors():
                x1, y1 = max(left, target.left), max(top, target.top)
                x2, y2 = min(left + width, target.left + target.width), min(top + height, target.top + target.height)
                if x2 <= x1 or y2 <= y1:
                    continue
                indices = outputs.get(monitor_name(handle).casefold())
                if indices is None:
                    raise RuntimeError('DirectX не видит выбранный экран.')
                with dxcam.create(device_idx=indices[0], output_idx=indices[1],
                                  output_color='BGRA', processor_backend='numpy') as camera:
                    deadline = time.monotonic() + 1.0
                    pixels = None
                    while pixels is None and time.monotonic() < deadline:
                        pixels = camera.grab(new_frame_only=False)
                        if pixels is None:
                            time.sleep(0.015)
                    if pixels is None:
                        raise RuntimeError('DirectX не вернул игровой кадр. Повторите Alt+Q после переключения режима экрана.')
                    crop = pixels[y1-top:y2-top, x1-left:x2-left]
                    if crop.shape[:2] != (y2-y1, x2-x1):
                        raise RuntimeError('Разрешение экрана изменилось. Повторите захват.')
                    frame[y1-target.top:y2-target.top, x1-target.left:x2-target.left] = crop
                    covered = True
            if not covered:
                raise ValueError('Выбранное окно находится за пределами подключённых экранов.')
            frame[:, :, 3] = 255
            return frame
    finally:
        if initialized:
            comtypes.CoUninitialize()


def capture(target: CaptureTarget) -> np.ndarray:
    if target.width <= 0 or target.height <= 0:
        raise ValueError('Окно свёрнуто или недоступно для распознавания.')
    try:
        frame = capture_dxgi(target)
        target.backend = 'DirectX'
        return frame
    except Exception as exc:
        if target.fullscreen:
            # GDI can return desktop pixels in place of an exclusive game frame.
            raise RuntimeError('Не удалось получить полноэкранный кадр DirectX: ' + str(exc)) from exc
        frame = capture_gdi(target)
        target.backend = 'GDI (резервный)'
        return frame


def capture_gdi(target: CaptureTarget) -> np.ndarray:
    """Read visible desktop pixels into RAM; no file and no frozen background."""
    if target.width <= 0 or target.height <= 0:
        raise ValueError('Окно свёрнуто или недоступно для распознавания.')
    gdi = ctypes.WinDLL('gdi32', use_last_error=True)
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi.CreateCompatibleDC.restype = wintypes.HDC
    gdi.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
    gdi.CreateDIBSection.restype = wintypes.HBITMAP
    gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi.SelectObject.restype = wintypes.HGDIOBJ
    gdi.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                         wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
    gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi.DeleteDC.argtypes = [wintypes.HDC]
    class Header(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('width', wintypes.LONG), ('height', wintypes.LONG),
                    ('planes', wintypes.WORD), ('bits', wintypes.WORD), ('compression', wintypes.DWORD),
                    ('imageSize', wintypes.DWORD), ('xppm', wintypes.LONG), ('yppm', wintypes.LONG),
                    ('used', wintypes.DWORD), ('important', wintypes.DWORD)]
    header = Header(ctypes.sizeof(Header), target.width, -target.height, 1, 32, 0,
                    target.width * target.height * 4, 0, 0, 0, 0)
    screen_dc, memory_dc, bitmap, previous = None, None, None, None
    try:
        screen_dc = user32.GetDC(None)
        memory_dc = gdi.CreateCompatibleDC(screen_dc)
        pixels = ctypes.c_void_p()
        bitmap = gdi.CreateDIBSection(screen_dc, ctypes.byref(header), 0, ctypes.byref(pixels), None, 0)
        if not screen_dc or not memory_dc or not bitmap or not pixels.value:
            raise ctypes.WinError(ctypes.get_last_error())
        previous = gdi.SelectObject(memory_dc, bitmap)
        if not gdi.BitBlt(memory_dc, 0, 0, target.width, target.height,
                          screen_dc, target.left, target.top, 0x00CC0020 | 0x40000000):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = (ctypes.c_ubyte * (target.width * target.height * 4)).from_address(pixels.value)
        frame = np.ctypeslib.as_array(buffer).reshape(target.height, target.width, 4).copy()
        frame[:, :, 3] = 255
        return frame
    finally:
        if previous and memory_dc:
            gdi.SelectObject(memory_dc, previous)
        if bitmap:
            gdi.DeleteObject(bitmap)
        if memory_dc:
            gdi.DeleteDC(memory_dc)
        if screen_dc:
            user32.ReleaseDC(None, screen_dc)


def foreground_window():
    return int(user32.GetForegroundWindow() or 0)


def window_is_ours(hwnd):
    process = wintypes.DWORD()
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
    return process.value == os.getpid()


def restore_window(hwnd):
    if hwnd and not window_is_ours(hwnd):
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        user32.SetForegroundWindow(hwnd)


def focus_our_window(hwnd):
    if hwnd and window_is_ours(hwnd):
        user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        return bool(user32.SetForegroundWindow(hwnd))
    return False


def parse_hotkey(value: str):
    parts = value.upper().split("+")
    modifiers = 0x4000
    keys = []
    for part in parts:
        p = part.strip()
        if p in {"CTRL", "ALT", "SHIFT", "WIN"}:
            modifiers |= {"ALT": 1, "CTRL": 2, "SHIFT": 4, "WIN": 8}[p]
        else:
            keys.append(p)
    if len(keys) != 1:
        raise ValueError("Сочетание: Alt+Q, Ctrl+Shift+F8 и подобные.")
    key = keys[0]
    if len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key)
    elif key.startswith("F") and key[1:].isdigit() and 1 <= int(key[1:]) <= 24:
        code = 0x70 + int(key[1:]) - 1
    else:
        raise ValueError("Используйте букву, цифру или F1–F24.")
    return modifiers, code
