"""Local Windows OCR with genuine per-word coordinates."""
from __future__ import annotations

import time
import numpy as np


class WindowsOCRUnavailable(RuntimeError):
    pass


def convert_windows_result(result, scale=1.0):
    from .ocr import convert_result
    sx,sy=scale if isinstance(scale,tuple) else (scale,scale)
    lines=list(result.lines)
    data={'rec_texts':[line.text for line in lines], 'rec_scores':[1.0]*len(lines),
          'text_word':[], 'text_word_boxes':[]}
    for line in lines:
        labels,boxes=[],[]
        for word in line.words:
            rect=word.bounding_rect
            labels.append(word.text)
            boxes.append([rect.x*sx,rect.y*sy,(rect.x+rect.width)*sx,(rect.y+rect.height)*sy])
        data['text_word'].append(labels); data['text_word_boxes'].append(boxes)
    return convert_result(data)


class WindowsOCR:
    def __init__(self):
        self.engine=None

    def initialize(self):
        if self.engine is not None:
            return
        try:
            from winrt.windows.media.ocr import OcrEngine
            from winrt.windows.globalization import Language
            languages=[lang.language_tag for lang in OcrEngine.available_recognizer_languages]
            english=[tag for tag in languages if tag.casefold().startswith('en')]
            if not english:
                raise WindowsOCRUnavailable('В Windows не установлен английский OCR. Выберите PaddleOCR или установите распознавание текста для английского языка в Windows.')
            tag=next((tag for tag in english if tag.casefold()=='en-us'),english[0])
            self.engine=OcrEngine.try_create_from_language(Language(tag))
            if self.engine is None:
                raise WindowsOCRUnavailable('WindowsOCR недоступен. Выберите PaddleOCR в настройках.')
            self.max_dimension=OcrEngine.max_image_dimension
        except (ImportError,OSError) as exc:
            raise WindowsOCRUnavailable('WindowsOCR недоступен: '+str(exc)) from exc

    def warmup(self):
        self.initialize()
        self.recognize(np.full((80,320,3),255,dtype=np.uint8))

    def recognize(self,image):
        self.initialize()
        from winrt.windows.graphics.imaging import SoftwareBitmap,BitmapPixelFormat,BitmapAlphaMode
        from winrt.windows.storage.streams import Buffer
        import cv2
        start=time.perf_counter()
        if isinstance(image,(str,bytes)):
            from PIL import Image
            with Image.open(image) as source:
                pixels=np.array(source.convert('RGBA'))[:,:,[2,1,0,3]].copy()
        else:
            pixels=np.asarray(image)
            if pixels.shape[2]==3:
                pixels=cv2.cvtColor(pixels,cv2.COLOR_BGR2BGRA)
            else:
                pixels=np.ascontiguousarray(pixels)
        original_height,original_width=pixels.shape[:2]
        scale=max(1.0,max(pixels.shape[:2])/self.max_dimension)
        if scale>1:
            pixels=cv2.resize(pixels,(int(pixels.shape[1]/scale),int(pixels.shape[0]/scale)),interpolation=cv2.INTER_AREA)
        buffer=Buffer(pixels.nbytes);buffer.length=pixels.nbytes
        memoryview(buffer)[:]=memoryview(pixels).cast('B')
        with SoftwareBitmap.create_copy_with_alpha_from_buffer(buffer,BitmapPixelFormat.BGRA8,
                pixels.shape[1],pixels.shape[0],BitmapAlphaMode.IGNORE) as bitmap:
            result=self.engine.recognize_async(bitmap).get()
            # Integer resize dimensions can have different X/Y scale factors.
            # Map boxes back using the dimensions actually sent to the OCR API.
            words=convert_windows_result(result,(original_width/pixels.shape[1],original_height/pixels.shape[0]))
        return {'words':[word.model_dump() for word in words],
                'seconds':round(time.perf_counter()-start,3)}
