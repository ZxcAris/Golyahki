"""Screen text geometry for reading order and overlay layout."""
from __future__ import annotations

from statistics import median
import numpy as np


def bounds(polygon):
    points=np.asarray(polygon)
    return tuple(float(v) for v in (*points.min(axis=0),*points.max(axis=0)))


def horizontal_rows(items, get_bounds, split_gaps=True):
    """Recover baselines when OCR detects each word as a separate text line."""
    rows=[]; row_stats=[]
    values=[(item,get_bounds(item)) for item in items]
    for item,box in sorted(values,key=lambda value:(value[1][1],value[1][0])):
        x1,y1,x2,y2=box; height=max(y2-y1,1)
        candidates=[]
        for index,row in enumerate(rows):
            top,bottom=row_stats[index]
            rh=max(bottom-top,1); overlap=min(y2,bottom)-max(y1,top)
            distance=abs((y1+y2-top-bottom)/2)
            if overlap/min(height,rh)>=.5 and distance<=max(height,rh)*.4 and min(height,rh)/max(height,rh)>=.45:
                candidates.append((distance,index))
        if candidates:
            index=min(candidates)[1]
            rows[index].append((item,box))
            row_stats[index]=(median(b[1] for _,b in rows[index]),median(b[3] for _,b in rows[index]))
        else:
            rows.append([(item,box)]); row_stats.append((y1,y2))
    segments=[]
    for row in sorted(rows,key=lambda r:median(b[1] for _,b in r)):
        row=sorted(row,key=lambda value:value[1][0])
        height=median(b[3]-b[1] for _,b in row)
        current=[]
        previous=None
        for item,box in row:
            if split_gaps and current and box[0]-previous[2]>max(12,height*1.8):
                segments.append(current); current=[]
            current.append(item)
            previous=box
        if current: segments.append(current)
    return segments


def assign_text_rows(words):
    rows=horizontal_rows(words,lambda w:w.bounds())
    groups=[]
    for line,row in enumerate(rows):
        boxes=[w.bounds() for w in row]
        x1=min(b[0] for b in boxes); y1=min(b[1] for b in boxes)
        x2=max(b[2] for b in boxes); y2=max(b[3] for b in boxes)
        height=max(y2-y1,1)
        candidate=None
        for group in reversed(groups):
            gx1,gy1,gx2,gy2,bid=group
            gap=y1-gy2; gh=gy2-gy1
            aligned=abs(x1-gx1)<=max(height,gh)*.75
            overlap=min(x2,gx2)-max(x1,gx1)
            # Detected descenders and the next row's ascenders may overlap.
            # Baseline separation still distinguishes wrapped rows from peers.
            separated=(y1+y2-gy1-gy2)/2>=max(height,gh)*.6
            if -min(height,gh)*.25<=gap<=max(height,gh)*.42 and separated and (aligned or overlap>=min(x2-x1,gx2-gx1)*.6):
                candidate=group; break
        if candidate is None:
            candidate=[x1,y1,x2,y2,len(groups)]; groups.append(candidate)
        else:
            candidate[:4]=[x1,y1,x2,y2]
        for word in row:
            word.line=line; word.block=candidate[4]
