from golyah.ocr import convert_result
from golyah.selection import highlight_layout,selection


def test_individual_ocr_detections_recover_wrapped_dialogue_and_separate_speaker():
    items=[('Weather',78,64,326,121),('announcer',346,78,635,118),
        ('In',105,159,160,207),('other',173,154,342,211),('Inaba-related',358,151,763,212),
        ('news,',777,158,954,213),('meteorologists',978,152,1412,215),
        ('predicting',213,217,515,281),('heavy',530,218,715,282),('fog',733,218,846,281),
        ('throughout',862,220,1192,278),('the',1208,219,1319,279),('are',100,235,195,275),
        ('year.',98,301,239,347)]
    words=convert_result({'rec_texts':[i[0] for i in items],'rec_scores':[.99]*len(items),
        'text_word':[[i[0]] for i in items], 'text_word_boxes':[[list(i[1:])] for i in items]})
    annotated,lines=highlight_layout(words)
    assert len(set(w['sentenceId'] for w in annotated))==2
    assert len(lines)==4
    chosen=next(w.id for w in words if w.text=='meteorologists')
    assert selection(words,[chosen])['sentence']=='In other Inaba-related news, meteorologists are predicting heavy fog throughout the year.'
    assert [w.text for w in sorted(words,key=lambda w:(w.block,w.line,w.bounds()[0]))][:2]==['Weather','announcer']
    heights={w['displayBounds']['height'] for w in annotated if w['line']==2}
    assert len(heights)==1, 'Short lowercase letters must receive the full text row height'


def test_ctc_edge_bearings_use_actual_detector_bounds():
    words=convert_result({'rec_texts':['Weather'], 'rec_scores':[.99],
        'text_word':[['Weather']], 'text_word_boxes':[[[105,64,312,121]]],
        'rec_polys':[[[78,64],[326,67],[325,121],[78,118]]]})
    assert words[0].bounds()==(78,64,326,121)
    values,_=highlight_layout(words)
    b=values[0]['displayBounds']
    assert b['left']<78 and b['left']+b['width']>326


def test_contours_have_room_for_descenders_and_merge_sentence_breaks_on_a_row():
    items=[('Well...',47,126,241,177),('we',277,142,365,174),
        ('thought',392,126,620,177),('people',648,126,837,177),
        ('Midnight',50,194,306,245),('Channel.',333,194,557,242)]
    words=convert_result({'rec_texts':[i[0] for i in items],'rec_scores':[.99]*len(items),
        'text_word':[[i[0]] for i in items],'text_word_boxes':[[list(i[1:])] for i in items]})
    values,lines=highlight_layout(words)
    assert len(lines)==2 and lines[0]['sentenceIds']==[0,1]
    assert len(set(word['sentenceId'] for word in values))==2
    assert lines[0]['left']<=36 and lines[0]['top']<=115
    assert lines[0]['left']+lines[0]['width']>=848
    assert lines[1]['top']+lines[1]['height']>=257
    assert lines[1]['width']<550, 'Shorter wrapped rows retain their contour'
    from golyah.selection import word_at
    assert word_at(values,260,150) is None, 'The larger clear contour does not select a neighboring word'


def test_overlapping_detector_rows_share_context_without_overlapping_hover_boxes():
    items=[('Weather',75,65,307,118),('announcer',311,78,602,116),
           ('The',96,170,208,227),('region',205,171,387,237),('has',392,172,495,227),
           ('seen',499,183,621,224),('an',628,177,703,226),('abnormal',711,167,973,228),('amount',983,174,1191,224),
           ('of',88,231,141,312),('fog',167,231,257,312),('over',254,242,383,303),('the',386,241,485,302),
           ('past',481,239,608,305),('few',609,239,721,303),('years,',706,245,883,304),
           ('and',882,237,997,304),('the',996,236,1096,300),
           ('cause',95,319,246,366),('of',257,312,328,363),('the',318,307,417,366),
           ('climate',419,305,622,367),('change',627,306,826,377),('is',819,315,877,364),('unknown.',885,310,1159,368)]
    words=convert_result({'rec_texts':[i[0] for i in items],'rec_scores':[.99]*len(items),
        'text_word':[[i[0]] for i in items], 'text_word_boxes':[[list(i[1:])] for i in items]})
    values,lines=highlight_layout(words)
    assert len(set(w['sentenceId'] for w in values))==2
    assert selection(words,[2])['sentence']=='The region has seen an abnormal amount of fog over the past few years, and the cause of the climate change is unknown.'
    body=sorted((s for s in lines if s['sentenceId']==1),key=lambda s:s['top'])
    assert len(body)==3
    row_boxes=[next(w['displayBounds'] for w in values if w['line']==line) for line in (1,2,3)]
    for upper,lower in zip(row_boxes,row_boxes[1:]):
        assert upper['top']+upper['height']<=lower['top']
