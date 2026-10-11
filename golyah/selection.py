from __future__ import annotations

import re
from .models import OCRWord


ABBREVIATIONS = {'mr.', 'mrs.', 'ms.', 'dr.', 'prof.', 'e.g.', 'i.e.', 'etc.'}


def ends_sentence(token: str) -> bool:
    token = token.rstrip('"”’\'')
    return bool(re.search(r'[.!?]$', token)) and token.casefold() not in ABBREVIATIONS


def reading_order(words: list[OCRWord]) -> list[OCRWord]:
    return sorted(words, key=lambda w: (w.block, w.line, w.bounds()[0]))


def word_at(words: list[dict], x: float, y: float) -> dict | None:
    """Use the same padded, half-open word regions as the overlay's pointer selection."""
    best, distance = None, float('inf')
    for word in words:
        box = word['displayBounds']
        if not (box['left'] <= x < box['left'] + box['width'] and
                box['top'] <= y < box['top'] + box['height']):
            continue
        score = ((x - box['left'] - box['width'] / 2) / box['width']) ** 2 + \
                ((y - box['top'] - box['height'] / 2) / box['height']) ** 2
        if score < distance:
            best, distance = word, score
    return best


def highlight_layout(words: list[OCRWord]) -> tuple[list[dict], list[dict]]:
    """Group actual word boxes into sentences, with one highlight per wrapped line."""
    groups, current = [], []
    for word in reading_order(words):
        if current and word.block != current[-1].block:
            groups.append(current); current = []
        current.append(word)
        token = word.text
        if len(current) > 1 and re.fullmatch(r'[.!?]["”’\']?', token):
            token = current[-2].text + token
        if ends_sentence(token):
            groups.append(current); current = []
    if current:
        groups.append(current)
    word_groups, segments, visuals, highlights = {}, [], {}, {}
    rows={}
    for word in words: rows.setdefault((word.block,word.line),[]).append(word)
    row_bounds={key:(min(w.bounds()[1] for w in items), max(w.bounds()[3] for w in items))
                for key,items in rows.items()}
    for key,items in rows.items():
        top,bottom=row_bounds[key]; height=bottom-top
        pad=max(2,min(12,height*.18))
        vt,vb=top-pad,bottom+pad
        others=[value for other,value in row_bounds.items() if other!=key and other[0]==key[0]]
        for ot,ob in others:
            if ot+ob<top+bottom: vt=max(vt,(ob+top)/2)
            if ot+ob>top+bottom: vb=min(vb,(bottom+ot)/2)
        ordered=sorted(items,key=lambda w:w.bounds()[0])
        for index,word in enumerate(ordered):
            left,word_top,right,word_bottom=word.bounds()
            wl,wr=left-pad,right+pad
            if index:
                wl=max(wl,(ordered[index-1].bounds()[2]+left)/2)
            if index+1<len(ordered):
                wr=min(wr,(right+ordered[index+1].bounds()[0])/2)
            visuals[word.id]={'left':wl,'top':vt,'width':max(1,wr-wl),'height':max(1,vb-vt)}
            # Keep generous row-based click regions, but draw the highlight
            # around this word's actual box, including mixed font sizes/baselines.
            word_pad=max(2,min(6,(word_bottom-word_top)*.12))
            hl,hr=max(wl,left-word_pad),min(wr,right+word_pad)
            ht,hb=max(vt,word_top-word_pad),min(vb,word_bottom+word_pad)
            highlights[word.id]={'left':hl,'top':ht,'width':max(1,hr-hl),'height':max(1,hb-ht)}
    for sentence_id, group in enumerate(groups):
        lines = {}
        for word in group:
            word_groups[word.id] = sentence_id
            lines.setdefault(word.line, []).append(word)
        for items in lines.values():
            # Transparent text contours have more breathing room than click regions.
            # Do not clip descenders at the boundary between two selectable rows.
            key=(items[0].block,items[0].line)
            top,bottom=row_bounds[key]; pad=max(4,min(24,(bottom-top)*.24))
            left=min(w.bounds()[0] for w in items)-pad
            right=max(w.bounds()[2] for w in items)+pad
            segments.append({'sentenceId': sentence_id, 'sentenceIds':[sentence_id],
                'left':left,'top':top-pad,'width':right-left,'height':bottom-top+2*pad,
                '_row':key})
    # A sentence break such as "Well..." must not darken the middle of a text row.
    merged=[]
    for segment in sorted(segments,key=lambda s:(s['_row'],s['left'])):
        previous=merged[-1] if merged else None
        if (previous and previous['_row']==segment['_row'] and
                segment['left']-previous['left']-previous['width'] <= segment['height']*.65):
            previous['width']=max(previous['left']+previous['width'],segment['left']+segment['width'])-previous['left']
            previous['sentenceIds'].extend(segment['sentenceIds'])
        else:
            merged.append(segment)
    segments=merged
    # Join small gaps between wrapped lines, while keeping the contour shaped
    # to the actual line lengths. A single Canvas fill avoids darker overlaps.
    for block in set(word.block for word in words):
        lines=sorted((s for s in segments if s['_row'][0]==block),key=lambda s:s['top'])
        for upper,lower in zip(lines,lines[1:]):
            gap=lower['top']-upper['top']-upper['height']
            if 0<gap<=max(upper['height'],lower['height'])*.6:
                upper['height']+=gap/2+1
                lower['top']-=gap/2+1; lower['height']+=gap/2+1
    for segment in segments: segment.pop('_row')
    values = [{**w.model_dump(), 'sentenceId': word_groups[w.id], 'displayBounds':visuals[w.id],
               'highlightBounds':highlights[w.id]} for w in words]
    return values, segments


def selection(words: list[OCRWord], selected_ids: list[int]) -> dict:
    ordered = reading_order(words)
    chosen = [w for w in ordered if w.id in selected_ids]
    if not chosen:
        return {"term": "", "sentence": "", "positions": []}
    blocks = {w.block for w in chosen}
    context_words = [w for w in ordered if w.block in blocks]
    pieces, offsets, cursor = [], {}, 0
    previous_block = None
    for w in context_words:
        join = ("\n" if previous_block != w.block else " ") if pieces else ""
        if pieces and (re.fullmatch(r"[.,!?;:%)\]}]+", w.text)
                       or re.fullmatch(r"['’]+", w.text)
                       or pieces[-1].endswith(("'", "’", "(", "[", "{"))):
            join = ""
        cursor += len(join)
        offsets[w.id] = [cursor, cursor + len(w.text)]
        pieces.append(join + w.text)
        cursor += len(w.text)
        previous_block = w.block
    paragraph = "".join(pieces)
    first = offsets.get(chosen[0].id, [0, 0])[0]
    last = offsets.get(chosen[-1].id, [len(paragraph), len(paragraph)])[1]
    cuts = [0] + [m.end() for m in re.finditer(r"[.!?][\"’”']?\s+", paragraph)
                  if ends_sentence(paragraph[:m.end()].strip().rsplit(maxsplit=1)[-1])] + [len(paragraph)]
    start = max(c for c in cuts if c <= first)
    end = min(c for c in cuts if c >= last)
    fragment = paragraph[start:end]
    trim = len(fragment) - len(fragment.lstrip())
    sentence = fragment.strip()
    positions = [[offsets[w.id][0] - start - trim, offsets[w.id][1] - start - trim]
                 for w in chosen if w.id in offsets]
    term = " ".join(w.text for w in chosen).strip("*.,!?;:()[]{}\"“”")
    indexes = [ordered.index(w) for w in chosen]
    display = ""
    for i, w in enumerate(chosen):
        if i:
            display += " … " if indexes[i] != indexes[i - 1] + 1 else " "
        display += w.text
    return {"term": term, "display": display, "sentence": sentence, "positions": positions}
