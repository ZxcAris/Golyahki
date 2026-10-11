import pytest
from golyah.windows import CaptureTarget, overlay_geometry, parse_hotkey


@pytest.mark.parametrize('ratio', [1, 1.25, 1.5, 2])
def test_window_coordinates_on_negative_monitor(ratio):
    target = CaptureTarget('window', 2, -1800, -150, 900, 600)
    geometry = overlay_geometry(target, (2, -1920, -200, 1920, 1080), (-1920, -200), ratio)
    assert geometry == (-1920 + 120 / ratio, -200 + 50 / ratio, 900 / ratio, 600 / ratio)
    word_pixel = (270, 120)
    screen_position = (geometry[0] + word_pixel[0] / ratio, geometry[1] + word_pixel[1] / ratio)
    assert screen_position[0] == -1920 + 390 / ratio


def test_hotkey_validation():
    assert parse_hotkey('Alt+Q') == (0x4001, ord('Q'))
    assert parse_hotkey('Ctrl+Alt+Q') == (0x4003, ord('Q'))
    assert parse_hotkey('Ctrl+Shift+F8') == (0x4006, 0x77)
    with pytest.raises(ValueError):
        parse_hotkey('Ctrl+Foo')
