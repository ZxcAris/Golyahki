from __future__ import annotations

import json
import base64
import io
import os
import re
import sys
import time
import unicodedata
from collections import OrderedDict
from hashlib import blake2b
from pathlib import Path

import numpy as np

from .models import OCRWord
from .layout import assign_text_rows, bounds


MIN_CONFIDENCE = 0.65
DET_MODEL = "PP-OCRv5_mobile_det"
REC_MODEL = "en_PP-OCRv5_mobile_rec"


def text_token(label: str, has_sentence: bool) -> bool:
    """Keep English text, including contractions; reject symbol-only OCR hits."""
    # Games wrap actions/emphasis in asterisks. Validate the enclosed text,
    # while retaining the original label and its full box for selection.
    label = label.replace('*', '')
    letters = [c for c in label if c.isalpha() and 'LATIN' in unicodedata.name(c, '')]
    if not letters:
        return has_sentence and bool(re.fullmatch(r"\d+(?:[.,:/-]\d+)*[.,!?]?", label))
    if len(letters) == 1 and letters[0].lower() not in ('a', 'i') and not has_sentence:
        return False
    allowed = sum(c.isalnum() or c in "'’‘\"“”.,!?;:()-–—/[]" for c in label)
    return allowed == len(label) and len(letters) / max(len(label), 1) >= 0.35


def convert_result(result: dict) -> list[OCRWord]:
    data = result.get("res", result)
    words = []
    line_texts = data.get("rec_texts", [])
    line_polys = data.get("rec_polys", data.get("dt_polys", []))
    scores = data.get("rec_scores", [])
    word_boxes = data.get("text_word_boxes", data.get("rec_word_boxes", []))
    word_texts = data.get("text_word", data.get("text_word_texts", data.get("rec_word_texts", [])))
    for line, line_text in enumerate(line_texts):
        confidence = float(scores[line]) if line < len(scores) else 0.0
        if confidence < MIN_CONFIDENCE:
            continue
        has_sentence = bool(re.search(r"[A-Za-z]{2,}", line_text))
        start_word = len(words)
        if len(word_boxes) > line and len(word_boxes[line]):
            boxes, texts = word_boxes[line], word_texts[line]
            tokens, offset = [], 0
            for label, polygon in zip(texts, boxes):
                if not label.strip():
                    continue
                # The English model returns punctuation separately. Reassemble adjacent
                # pieces using the original text, preserving don't, well-known and stops.
                position = line_text.find(label, offset)
                polygon = np.asarray(polygon).tolist()
                if len(polygon) == 4 and isinstance(polygon[0], (float, int)):
                    x1, y1, x2, y2 = polygon
                    polygon = [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]
                if tokens and position == offset and position >= 0:
                    previous = tokens[-1]
                    previous[0] += label
                    previous[1].extend(polygon)
                else:
                    tokens.append([label.strip(), polygon])
                offset = position + len(label) if position >= 0 else offset
            for label, polygon in tokens:
                if not text_token(label, has_sentence):
                    continue
                xs, ys = zip(*polygon)
                x1, x2, y1, y2 = min(xs), max(xs), min(ys), max(ys)
                if x2 <= x1 or y2 - y1 < 6:
                    continue
                words.append(OCRWord(id=len(words), text=label,
                    polygon=[[x1,y1],[x2,y1],[x2,y2],[x1,y2]], confidence=confidence, line=line))
        else:
            # Never manufacture approximate per-word rectangles from a line box.
            if len(line_text.split()) > 1:
                raise ValueError("OCR не вернул координаты отдельных слов. Проверьте return_word_box и версию PaddleOCR.")
            if text_token(line_text.strip(), has_sentence) and line < len(line_polys):
                words.append(OCRWord(id=len(words), text=line_text,
                    polygon=np.asarray(line_polys[line]).tolist(), confidence=confidence, line=line))
        line_words=words[start_word:]
        if line_words and line < len(line_polys):
            # CTC character spans omit edge bearings (e.g. the W in Weather).
            # Use the real detected line edges for its first/last word.
            lx1,ly1,lx2,ly2=bounds(line_polys[line])
            for index,word in enumerate(line_words):
                x1,y1,x2,y2=word.bounds()
                if index==0: x1=min(x1,lx1)
                if index==len(line_words)-1: x2=max(x2,lx2)
                word.polygon=[[x1,min(y1,ly1)],[x2,min(y1,ly1)],
                              [x2,max(y2,ly2)],[x1,max(y2,ly2)]]
    assign_blocks(words)
    return words


def assign_blocks(words: list[OCRWord]):
    assign_text_rows(words)


class PaddleRunner:
    def __init__(self):
        self.engine = None

    def initialize(self):
        if self.engine is None:
            os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
            from paddleocr import PaddleOCR
            model_options = {}
            if getattr(sys, "frozen", False):
                models = Path(sys._MEIPASS) / "models"
                model_options = {
                    "text_detection_model_dir": str(models / DET_MODEL),
                    "text_recognition_model_dir": str(models / REC_MODEL),
                }
            self.engine = PaddleOCR(
                text_detection_model_name=DET_MODEL,
                text_recognition_model_name=REC_MODEL,
                use_doc_orientation_classify=False, use_doc_unwarping=False,
                use_textline_orientation=False, device="cpu", cpu_threads=4,
                return_word_box=True, enable_mkldnn=True,
                text_recognition_batch_size=1,
                text_rec_score_thresh=MIN_CONFIDENCE,
                text_det_limit_type="max", text_det_limit_side_len=1600, **model_options)

    def warmup(self):
        self.initialize()
        # Exercise both predictors so first real capture does not compile them.
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new('RGB', (640, 160), 'white')
        ImageDraw.Draw(image).text((20, 35), 'A quick look.', fill='black',
            font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 32))
        self.engine.predict(np.array(image)[:, :, ::-1].copy())

    def recognize(self, path: str | np.ndarray):
        self.initialize()
        if isinstance(path,np.ndarray) and path.shape[2]==4:
            path=np.ascontiguousarray(path[:,:,:3])
        start = time.perf_counter()
        output = []
        for result in self.engine.predict(path):
            # OCRResult is already a dict; do not serialize its arrays and image metadata.
            output.extend(convert_result(result))
        return {"words": [w.model_dump() for w in output],
                "seconds": round(time.perf_counter() - start, 3)}


class OCRRunner:
    """Prefer the fast OS engine; keep Paddle available without loading it eagerly."""
    def __init__(self,mode='auto'):
        self.mode=mode
        self.paddle=PaddleRunner()
        self.windows=None
        self.active=None
        self.backend=''
        self.fallback=''
        self._repair_cache=OrderedDict()
        self._repair_cache_hits=0

    def _recognize_repair(self, frame, engine):
        frame=np.ascontiguousarray(frame)
        key=(engine,frame.shape,blake2b(memoryview(frame),digest_size=16).digest())
        if key in self._repair_cache:
            self._repair_cache_hits+=1
            self._repair_cache.move_to_end(key)
            return self._repair_cache[key]
        runner=self.paddle if engine=='paddle' else self.windows
        result=runner.recognize(frame)
        self._repair_cache[key]=result
        if len(self._repair_cache)>16: self._repair_cache.popitem(last=False)
        return result

    def initialize(self,mode=None):
        if mode is not None:
            if mode not in ('auto','windows','paddle'):
                raise ValueError('Неизвестный движок OCR.')
            self.mode=mode
        self.fallback=''
        if self.mode!='paddle':
            from .windows_ocr import WindowsOCR,WindowsOCRUnavailable
            if self.windows is None: self.windows=WindowsOCR()
            try:
                self.windows.initialize()
                self.active=self.windows;self.backend='WindowsOCR'
                return
            except WindowsOCRUnavailable as exc:
                if self.mode=='windows': raise
                self.fallback=str(exc)
        self.paddle.initialize()
        self.active=self.paddle;self.backend='PaddleOCR'

    def warmup(self,mode=None):
        self.initialize(mode)
        self.active.warmup()

    def recognize(self,image,mode=None):
        self.initialize(mode)
        start = time.perf_counter()
        result=self.active.recognize(image)
        if self.mode == 'auto' and self.backend == 'WindowsOCR':
            from .ocr_repair import recover_gaps, recover_edges
            words = [OCRWord.model_validate(value) for value in result['words']]
            if words:
                if isinstance(image, (str, bytes, Path)):
                    from PIL import Image
                    with Image.open(image) as source:
                        frame = np.array(source.convert('RGB'))[:, :, ::-1].copy()
                else:
                    frame = np.asarray(image)
                try:
                    self._repair_cache_hits=0
                    gaps=recover_gaps(words,frame,lambda crop:self._recognize_repair(crop,'paddle'))
                except Exception as exc:
                    # A failed optional repair must not discard valid primary OCR.
                    result['repair_error'] = str(exc)
                    gaps=0
                try:
                    edges=recover_edges(words,frame,lambda crop:self._recognize_repair(crop,'windows'))
                except Exception as exc:
                    result['repair_error'] = str(exc)
                    edges=0
                if gaps or edges:
                    result.update(words=[word.model_dump() for word in words],
                        recovered_words=gaps+edges,
                        repair_engine='PaddleOCR + WindowsOCR' if gaps and edges else ('PaddleOCR' if gaps else 'WindowsOCR'),
                        repair_cache_hits=self._repair_cache_hits)
        result['seconds'] = round(time.perf_counter()-start, 3)
        return {**result,'engine':self.backend,'fallback':self.fallback}


def worker():
    # QProcess consumes only marked protocol lines; library diagnostic logs stay separate.
    sys.stdout.reconfigure(encoding="utf-8")
    runner = OCRRunner()
    for line in sys.stdin:
        request = {}
        try:
            request = json.loads(line)
            if request.get('command') == 'warmup':
                runner.warmup(request.get('engine','auto'))
                result = {'ready': True,'engine':runner.backend}
            elif 'memory' in request:
                from multiprocessing.shared_memory import SharedMemory
                mapping=SharedMemory(name=request['memory'])
                try:
                    frame=np.ndarray(tuple(request['shape']),dtype=np.uint8,buffer=mapping.buf).copy()
                finally:
                    mapping.close()
                result=runner.recognize(frame,request.get('engine','auto'))
            elif 'image' in request:
                from PIL import Image
                with Image.open(io.BytesIO(base64.b64decode(request['image'], validate=True))) as image:
                    frame = np.array(image.convert('RGB'))[:, :, ::-1].copy()
                result = runner.recognize(frame,request.get('engine','auto'))
            else:
                result = runner.recognize(request["path"],request.get('engine','auto'))
            response = {"id": request["id"], "result": result}
        except Exception as exc:
            response = {"id": request.get("id", -1), "error": str(exc)}
        print("GOLYAH_JSON:" + json.dumps(response, ensure_ascii=False), flush=True)
        # Do not retain the preceding image while waiting for the next request.
        request.clear()
        frame, line = None, ''
