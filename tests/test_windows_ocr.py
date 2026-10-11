from types import SimpleNamespace
import pytest
from golyah.windows_ocr import convert_windows_result,WindowsOCRUnavailable
from golyah.ocr import OCRRunner
from golyah.selection import selection


def native_word(text,x,y,width=45):
    return SimpleNamespace(text=text,bounding_rect=SimpleNamespace(x=x,y=y,width=width,height=30))


def test_native_word_boxes_keep_both_it_and_reject_nearby_ui_noise():
    labels=['>','It','seems','to','be','a','woman.','It','looks','like']
    row=SimpleNamespace(text=' '.join(labels),words=[native_word(t,i*80,100) for i,t in enumerate(labels)])
    second=SimpleNamespace(text="she's wearing a kimono...",words=[native_word(t,i*80,140)
        for i,t in enumerate(["she's",'wearing','a','kimono...'])])
    noise=[SimpleNamespace(text=t,words=[native_word(t,i*100,500)]) for i,t in enumerate(['x','99','+'])]
    words=convert_windows_result(SimpleNamespace(lines=[row,second,*noise]),scale=2)
    assert [w.text for w in words].count('It')==2
    chosen=[w for w in words if w.text=='It'][1]
    assert chosen.bounds()==(1120,200,1210,260)
    assert selection(words,[chosen.id])['sentence']=="It looks like she's wearing a kimono..."
    assert not any(w.text in ('>','x','99','+') for w in words)


def test_resized_word_boxes_map_back_with_actual_axis_scales():
    sx,sy=4097/2048,2305/1152
    row=SimpleNamespace(text='weather',words=[native_word('weather',1900,1080,80)])
    words=convert_windows_result(SimpleNamespace(lines=[row]),scale=(sx,sy))
    assert words[0].bounds() == pytest.approx((1900*sx,1080*sy,1980*sx,1110*sy))


def test_auto_falls_back_when_english_windows_ocr_is_unavailable(monkeypatch):
    import golyah.windows_ocr as native
    calls=[]
    def unavailable(self):raise WindowsOCRUnavailable('English OCR missing')
    monkeypatch.setattr(native.WindowsOCR,'initialize',unavailable)
    runner=OCRRunner()
    monkeypatch.setattr(runner.paddle,'initialize',lambda:calls.append('paddle'))
    monkeypatch.setattr(runner.paddle,'recognize',lambda image:{'words':[],'seconds':.1})
    result=runner.recognize('unused')
    assert calls==['paddle'] and result['engine']=='PaddleOCR'
    assert result['fallback']=='English OCR missing'


def test_native_dialogue_action_is_selectable_without_asterisks_in_lookup():
    from golyah.selection import highlight_layout, word_at
    labels = ['of', 'your', 'destiny', 'together...', '*chuckle*']
    row = SimpleNamespace(text=' '.join(labels), words=[native_word(t, i*100, 255)
        for i,t in enumerate(labels)])
    words = convert_windows_result(SimpleNamespace(lines=[row]))
    action = next(w for w in words if w.text == '*chuckle*')
    annotated, _ = highlight_layout(words)
    assert word_at(annotated, 420, 270)['id'] == action.id
    data = selection(words, [action.id])
    assert data['term'] == 'chuckle'
    assert data['display'] == data['sentence'] == '*chuckle*'
    assert data['positions'] == [[0,9]]


def test_explicit_windows_mode_reports_missing_language_without_loading_paddle(monkeypatch):
    import golyah.windows_ocr as native
    def unavailable(self):raise WindowsOCRUnavailable('English OCR missing')
    monkeypatch.setattr(native.WindowsOCR,'initialize',unavailable)
    runner=OCRRunner('windows')
    monkeypatch.setattr(runner.paddle,'initialize',lambda:pytest.fail('Explicit mode must not change silently'))
    with pytest.raises(WindowsOCRUnavailable,match='English OCR missing'):
        runner.recognize('unused')
