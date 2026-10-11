import numpy as np
import pytest
from golyah.models import OCRWord
from golyah.ocr import OCRRunner
from golyah.ocr_repair import recover_gaps, recover_edges, word_gaps
from golyah.selection import selection, highlight_layout, word_at


def word(identifier, label, left, right, top=150, bottom=201):
    return OCRWord(id=identifier, text=label, confidence=1, line=0,
        polygon=[[left,top],[right,top],[right,bottom],[left,bottom]])


def test_repair_uses_real_boxes_and_restores_sentence_selection():
    words = [word(0,'uh.',217,305), word(1,'it',512,552), word(2,'was',581,699),
        word(3,'nothing.',727,961)]
    frame = np.random.default_rng(8).integers(0,256,(300,1000,4),dtype=np.uint8)
    calls = []
    def recognize(crop):
        calls.append(crop.shape)
        return {'words':[word(0,'Nah,',28,173,17,74).model_dump()]}
    assert recover_gaps(words, frame, recognize) == 1
    assert len(calls) == 1 and calls[0][2] == 3
    recovered = words[-1]
    assert recovered.text == 'Nah,' and recovered.bounds() == (334,149,479,206)
    assert [w.id for w in words] == list(range(5))
    annotated, lines = highlight_layout(words)
    assert word_at(annotated,400,175)['text'] == 'Nah,'
    chosen = selection(words,[recovered.id])
    assert chosen['term'] == 'Nah'
    assert chosen['sentence'] == 'Nah, it was nothing.'
    assert any(line['left'] <= 334 and line['left']+line['width'] >= 479 for line in lines)


@pytest.mark.parametrize('color', [(0,0,0,0), (70,85,110,255)])
def test_blank_spacing_and_separate_columns_do_not_start_repair(color):
    words = [word(0,'left',10,50),word(1,'right',210,250)]
    frame = np.empty((300,1000,4),dtype=np.uint8); frame[:] = color
    assert recover_gaps(words,frame,
        lambda frame: pytest.fail('Empty gap must not load Paddle')) == 0
    assert not word_gaps([word(0,'left',10,50),word(1,'column',700,800)])


def test_repair_drops_boxes_outside_the_gap_and_overlaps():
    words = [word(0,'before',217,305),word(1,'after',512,552)]
    frame = np.random.default_rng(8).integers(0,256,(300,1000,4),dtype=np.uint8)
    def recognize(crop):
        return {'words':[word(0,'Nah,',28,173,17,74).model_dump(),
            word(1,'duplicate',28,173,17,74).model_dump(),
            word(2,'edge',190,230,17,74).model_dump()]}
    assert recover_gaps(words,frame,recognize) == 1
    assert [w.text for w in words] == ['before','after','Nah,']


def test_auto_repair_failure_preserves_primary_words(monkeypatch):
    primary = [word(0,'before',217,305),word(1,'after',512,552)]
    class Windows:
        def initialize(self): pass
        def recognize(self,image): return {'words':[w.model_dump() for w in primary],'seconds':.01}
    runner = OCRRunner(); runner.windows = Windows()
    monkeypatch.setattr(runner.paddle,'recognize',lambda frame: (_ for _ in ()).throw(RuntimeError('repair unavailable')))
    frame = np.random.default_rng(8).integers(0,256,(300,1000,4),dtype=np.uint8)
    result = runner.recognize(frame)
    assert result['words'] == [w.model_dump() for w in primary]
    assert result['engine'] == 'WindowsOCR' and result['repair_error'] == 'repair unavailable'


def test_edge_repair_uses_real_coordinates_and_rejects_internal_changes():
    from PIL import Image,ImageDraw,ImageFont
    image=Image.new('RGB',(500,100),(55,65,75)); draw=ImageDraw.Draw(image)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',32)
    draw.text((30,20),'We',font=font,fill='white')
    draw.text((95,20),'said',font=font,fill='white')
    draw.text((170,20),"I'll",font=font,fill='white')
    words=[word(0,'We',30,76,20,50),word(1,'said',95,154,20,50)]
    frame=np.array(image)[:,:,::-1].copy()
    calls=[]
    # The retry crop begins at (0,14); its OCR boxes are local coordinates.
    def recognize(crop):
        calls.append(crop)
        return {'words':[word(0,"I'll",170,211,12,36).model_dump(),
            word(1,'wrong',95,154,12,36).model_dump()]}
    assert recover_edges(words,frame,recognize)==1
    assert len(calls)==1
    assert words[-1].bounds()==(170,26,211,50)
    assert selection(words,[words[-1].id])['sentence']=="We said I'll"
    # Once the new word is included, there is no letter-sized ink past row ends.
    assert recover_edges(words,frame,lambda crop:pytest.fail('Complete row must not be retried'))==0


def test_repair_cache_uses_exact_pixels_and_is_bounded(monkeypatch):
    runner=OCRRunner(); calls=[]
    monkeypatch.setattr(runner.paddle,'recognize',lambda frame: calls.append(frame.copy()) or {'words':[]})
    frame=np.zeros((20,30,3),np.uint8)
    assert runner._recognize_repair(frame,'paddle')=={'words':[]}
    runner._recognize_repair(frame.copy(),'paddle')
    assert len(calls)==1 and runner._repair_cache_hits==1
    for i in range(1,20):
        changed=frame.copy(); changed[0,0,0]=i
        runner._recognize_repair(changed,'paddle')
    assert len(calls)==20 and len(runner._repair_cache)==16
    runner._recognize_repair(frame,'paddle')
    assert len(calls)==21, 'An evicted result is recognized again'


@pytest.mark.parametrize('channels',[3,4])
def test_paddle_receives_contiguous_bgr_without_changing_color_order(channels):
    from golyah.ocr import PaddleRunner
    frame=np.arange(20*30*channels,dtype=np.uint8).reshape(20,30,channels)
    expected=frame[:,:,:3].copy()
    class Predictor:
        def predict(self,image):
            assert image.shape==(20,30,3) and image.flags.c_contiguous
            assert np.array_equal(image,expected)
            return []
    runner=PaddleRunner(); runner.engine=Predictor()
    assert runner.recognize(frame)['words']==[]
