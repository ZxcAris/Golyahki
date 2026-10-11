import sys
from types import SimpleNamespace
import numpy as np
import pytest
from golyah import windows


def test_dxgi_crops_a_window_across_negative_monitors_and_multiple_gpus(monkeypatch):
    used = []
    class Camera:
        def __init__(self, value): self.value = value
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def grab(self, **kwargs):
            assert kwargs['new_frame_only'] is False
            return np.full((50,50,4), self.value, dtype=np.uint8)
    def create(**options):
        used.append((options['device_idx'],options['output_idx']))
        return Camera(10 if options['device_idx'] == 0 else 20)
    monkeypatch.setitem(sys.modules,'comtypes', SimpleNamespace(CoInitialize=lambda:None, CoUninitialize=lambda:None))
    monkeypatch.setitem(sys.modules,'dxcam', SimpleNamespace(create=create))
    monkeypatch.setattr(windows,'dxgi_outputs',lambda:{'left':(0,0),'right':(1,0)})
    monkeypatch.setattr(windows,'monitors',lambda:[(1,-50,0,50,50),(2,0,0,50,50)])
    monkeypatch.setattr(windows,'monitor_name',lambda handle:'left' if handle==1 else 'right')
    target=windows.CaptureTarget('window',1,-20,5,40,10)
    frame=windows.capture(target)
    assert frame.shape==(10,40,4) and target.backend=='DirectX'
    assert np.all(frame[:,:20,:3]==10) and np.all(frame[:,20:,:3]==20)
    assert np.all(frame[:,:,3]==255) and used==[(0,0),(1,0)]


def test_fullscreen_failure_never_returns_gdi_desktop_instead_of_game(monkeypatch):
    def unavailable(target): raise OSError('Access lost')
    called=[]
    monkeypatch.setattr(windows,'capture_dxgi',unavailable)
    monkeypatch.setattr(windows,'capture_gdi',lambda target:called.append(target) or 'desktop')
    normal=windows.CaptureTarget('window',1,0,0,800,600)
    assert windows.capture(normal)=='desktop' and normal.backend=='GDI (резервный)'
    with pytest.raises(RuntimeError,match='Access lost'):
        windows.capture(windows.CaptureTarget('window',1,0,0,1920,1080,fullscreen=True))
    assert called==[normal]
