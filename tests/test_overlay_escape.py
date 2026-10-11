from golyah.hotkeys import OverlayKeyboardListener


def test_escape_finishes_consumed_press_after_overlay_closes():
    received = []
    listener = OverlayKeyboardListener(received.append)
    assert not listener.handle_key(0x1b, False)
    listener.enabled = True
    assert not listener.handle_key(0x0d, False)
    assert not listener.handle_key(0x1b, True)
    assert listener.handle_key(0x1b, False)
    listener.enabled = False
    assert listener.handle_key(0x1b, False), 'Autorepeat must not reach the restored app'
    assert listener.handle_key(0x1b, True), 'The matching release belongs to the consumed press'
    assert received == [0x1b]
    assert not listener.handle_key(0x1b, False), 'Esc works normally outside the overlay'
    listener.enabled = True
    assert listener.handle_key(0x1b, False)
    assert listener.handle_key(0x1b, True)
    assert received == [0x1b, 0x1b]
