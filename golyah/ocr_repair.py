"""Recover missed text between real OCR words without guessing labels or boxes."""
from statistics import median
from .layout import horizontal_rows, assign_text_rows
from .models import OCRWord


def _overlaps(word, others):
    x1,y1,x2,y2=word.bounds()
    return any(min(x2,old.bounds()[2])>max(x1,old.bounds()[0]) and
        min(y2,old.bounds()[3])>max(y1,old.bounds()[1]) for old in others)


def _finish(words, recovered):
    if recovered:
        words.extend(recovered)
        assign_text_rows(words)
        for index,word in enumerate(words): word.id=index
    return len(recovered)


def word_gaps(words):
    candidates = []
    for row in horizontal_rows(words, lambda word: word.bounds(), split_gaps=False):
        for previous, following in zip(row, row[1:]):
            left, right = previous.bounds(), following.bounds()
            height = median([left[3]-left[1], right[3]-right[1]])
            gap = right[0]-left[2]
            if height >= 10 and max(24, height*1.8) < gap <= height*8:
                candidates.append((int(left[2])+1, int(min(left[1], right[1])-height*.35),
                    int(right[0]), int(max(left[3], right[3])+height*.35)))
    # Bound work on menus/HUDs with many unrelated columns.
    return candidates[:4]


def recover_gaps(words, frame, recognize):
    recovered = []
    for left, top, right, bottom in word_gaps(words):
        left, top = max(0, left), max(0, top)
        right, bottom = min(frame.shape[1], right), min(frame.shape[0], bottom)
        if right <= left or bottom <= top:
            continue
        crop = frame[top:bottom, left:right, :3].copy()
        if crop.std(axis=(0,1)).max() < 8:  # Uniform spacing does not need a second engine.
            continue
        result = recognize(crop)
        for value in result['words']:
            word = OCRWord.model_validate(value)
            word.polygon = [[x+left, y+top] for x, y in word.polygon]
            x1, y1, x2, y2 = word.bounds()
            if x1 < left or x2 > right or y1 < top or y2 > bottom:
                continue
            if _overlaps(word,words+recovered):
                continue
            recovered.append(word)
    return _finish(words,recovered)


def recover_edges(words, frame, recognize):
    """Retry high-contrast rows only when letter-sized ink remains beyond them."""
    import cv2
    import numpy as np
    recovered=[]; attempts=0
    for row in horizontal_rows(words,lambda word:word.bounds(),split_gaps=False):
        if len(row)<2: continue
        boxes=[word.bounds() for word in row]
        x1=min(box[0] for box in boxes); x2=max(box[2] for box in boxes)
        y1=min(box[1] for box in boxes); y2=max(box[3] for box in boxes)
        height=y2-y1
        if height<12: continue
        left=max(0,int(x1-height*6)); right=min(frame.shape[1],int(x2+height*6))
        top=max(0,int(y1-height*.20)); bottom=min(frame.shape[0],int(y2+height*.20))
        candidate=False
        for box,low,high in [(boxes[0],left,int(x1)-2),(boxes[-1],int(x2)+2,right)]:
            if high-low<3: continue
            edge=cv2.cvtColor(frame[max(0,int(y1)):int(y2),low:high,:3],cv2.COLOR_BGR2GRAY)
            if int(edge.max())-int(edge.min())<24: continue
            bx1,by1,bx2,by2=map(int,box)
            sample=cv2.cvtColor(frame[max(0,by1):by2,max(0,bx1):bx2,:3],cv2.COLOR_BGR2GRAY)
            if not sample.size: continue
            dark,background,light=np.percentile(sample,[10,50,90])
            if max(light-background,background-dark)<30: continue
            mask=edge>(background+light)/2 if light-background>=background-dark else edge<(dark+background)/2
            _,_,stats,_=cv2.connectedComponentsWithStats(mask.astype(np.uint8),8)
            if any(height*.5<=h<=height*1.1 and max(2,height*.05)<=w<=height*3 and area>=height*.3
                    for _,_,w,h,area in stats[1:]):
                candidate=True; break
        if not candidate: continue
        gray=cv2.cvtColor(frame[top:bottom,left:right,:3],cv2.COLOR_BGR2GRAY)
        _,binary=cv2.threshold(gray,0,255,cv2.THRESH_BINARY|cv2.THRESH_OTSU)
        result=recognize(cv2.cvtColor(binary,cv2.COLOR_GRAY2BGR)); attempts+=1
        for value in result['words']:
            word=OCRWord.model_validate(value)
            word.polygon=[[x+left,y+top] for x,y in word.polygon]
            wx1,wy1,wx2,wy2=word.bounds()
            # This pass only repairs outside row ends; internal gaps use Paddle.
            if not (wx2<=x1 or wx1>=x2) or not (y1<=(wy1+wy2)/2<=y2): continue
            if wx1<left or wx2>right or wy1<top or wy2>bottom: continue
            if not _overlaps(word,words+recovered): recovered.append(word)
        if attempts>=2: break
    return _finish(words,recovered)
