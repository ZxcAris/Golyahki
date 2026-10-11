import os
import threading
import time
from pathlib import Path
import pytest

os.environ.setdefault('QT_QUICK_CONTROLS_STYLE', 'Basic')
from PySide6.QtCore import QObject, QUrl, Qt, QPoint, QPointF, QMetaObject
from PySide6.QtWidgets import QApplication
from PySide6.QtQuick import QQuickWindow
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

from golyah.bridge import Bridge
from golyah.storage import Storage
from golyah.models import Explanation, ContextTranslation, Enrichment, Entry, Sense, Example


def visual_child(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_child(child, name)
        if found is not None:
            return found


def test_qml_shift_range_and_native_position_is_preserved(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'range-drag.sqlite'))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]
    main.hide()
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    popup = main.findChild(QQuickWindow, 'wordPopup')
    try:
        bridge._overlay.update(visible=True, stage='ready', left=0, top=0, width=800, height=500,
                               pixelWidth=800, pixelHeight=500)
        bridge.set_ocr_words([
            {'id': i, 'text': text, 'polygon': [[x,y],[x+65,y],[x+65,y+30],[x,y+30]],
             'confidence': 1, 'line': line, 'block': 0}
            for i, (text,x,y,line) in enumerate([
                ('Something',80,160,0), ('may',180,160,0), ('appear',270,160,0),
                ('on',80,205,1), ('TV.',180,205,1)])])
        bridge.overlayChanged.emit()
        QTest.qWait(100)
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(100,175))
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(200,220))
        QTest.qWait(50)
        assert bridge.record.term == 'Something may appear on TV'
        assert bridge.overlay['selected'] == [0,1,2,3,4]
        assert all(visual_child(overlay.contentItem(), 'captureWord_' + str(i)).property('selected') for i in range(5))
        assert visual_child(popup.contentItem(), 'popupDragHandle') is None
        popup.setPosition(380, 100)
        bridge.windowMoveStarted.emit(int(popup.winId()))
        QTest.qWait(50)
        assert popup.property('manuallyPlaced')
        assert abs(popup.x() - 380) <= 2 and abs(popup.y() - 100) <= 2
        snapshot = Path(__file__).resolve().parents[1] / 'test-results/native-drag-card.png'
        snapshot.parent.mkdir(exist_ok=True)
        assert popup.grabWindow().save(str(snapshot))
        position = popup.position()
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, QPoint(290,175))
        QTest.qWait(50)
        assert bridge.overlay['selected'] == [0,1,2]
        assert popup.position() == position, 'Changing the phrase must preserve the dragged position'
        bridge.record.definition_en = 'An explanation that arrives after dragging the card.'
        bridge.cardChanged.emit()
        QTest.qWait(50)
        assert popup.position() == position
        assert QMetaObject.invokeMethod(popup, 'place')
        assert popup.position() == position
        bridge.closeOverlay()
        QTest.qWait(30)
        assert not popup.property('manuallyPlaced') and not popup.isVisible()
    finally:
        bridge.close()
        for window in (overlay,popup,main):
            window.close()
        engine.deleteLater()
        QTest.qWait(20)


def test_popup_buttons_return_after_llm_timeout(tmp_path):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'deadline.sqlite'))
    release = threading.Event()
    class Stalled:
        def generate(self, record, mode, cancel):
            release.wait(3)
            return Explanation(definition_en='Weather forecasters expect dense fog.',
                usage_en='A weather prediction.', translation_ru='Метеорологи прогнозируют сильный туман.'), 'test'
    bridge.gemini = Stalled()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]
    popup = main.findChild(QQuickWindow,'wordPopup')
    overlay = main.findChild(QQuickWindow,'captureOverlay')
    main.hide()
    try:
        bridge.lookup('meteorologists are predicting heavy fog',
            'In other Inaba-related news, meteorologists are predicting heavy fog throughout the region.')
        popup.show(); QTest.qWait(100)
        explain = visual_child(popup.contentItem(),'explainButton')
        context = visual_child(popup.contentItem(),'contextTranslatorButton')
        assert explain.isEnabled() and context.isEnabled()
        bridge._llm_timer.setInterval(60)
        bridge.requestLLM('both')
        app.processEvents()
        assert not explain.isEnabled() and not context.isEnabled()
        QTest.qWait(100)
        assert not bridge.busy and explain.isEnabled() and context.isEnabled()
        release.set()
        QTest.qWait(50)
        bridge._llm_timer.setInterval(1000)
        point = explain.mapToScene(QPointF(explain.width()/2,explain.height()/2))
        QTest.mouseClick(popup,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,point.toPoint())
        deadline = time.monotonic()+3
        while bridge.busy and time.monotonic()<deadline:
            QTest.qWait(20)
        assert bridge.record.explain and 'Метеорологи' in bridge.record.translation
        assert explain.isEnabled() and context.isEnabled()
    finally:
        release.set()
        bridge.close()
        for window in (overlay,popup,main): window.close()
        engine.deleteLater(); QTest.qWait(20)


@pytest.mark.parametrize('scale',[1,1.25,1.5,2])
def test_word_highlight_stays_on_actual_word_at_each_scale(tmp_path,scale):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'word-boxes.sqlite'))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend',bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    main = engine.rootObjects()[0]; main.hide()
    overlay = main.findChild(QQuickWindow,'captureOverlay')
    popup = main.findChild(QQuickWindow,'wordPopup')
    try:
        bridge._overlay.update(visible=True,left=0,top=0,width=800,height=500,
            pixelWidth=800*scale,pixelHeight=500*scale)
        boxes = [(100,190,180,226),(200,202,240,220),(260,208,310,228)]
        bridge.set_ocr_words([{'id':i,'text':text,'line':0,'block':0,'confidence':1,
            'polygon':[[x*scale,y*scale] for x,y in [(l,t),(r,t),(r,b),(l,b)]]}
            for i,(text,(l,t,r,b)) in enumerate(zip(['Large','small','lower.'],boxes))])
        bridge.overlayChanged.emit(); QTest.qWait(80)
        for i,(l,t,r,b) in enumerate(boxes):
            item = visual_child(overlay.contentItem(),'captureWord_'+str(i))
            assert abs(item.x()-l) <= 6 and abs(item.y()-t) <= 6
            assert abs(item.x()+item.width()-r) <= 6
            assert abs(item.y()+item.height()-b) <= 6
            QTest.mouseMove(overlay,QPoint(500,100)); QTest.qWait(10)
            QTest.mouseMove(overlay,QPoint(round((l+r)/2),round((t+b)/2)))
            QTest.qWait(20)
            assert overlay.property('hoveredWord') == i, (scale,i,overlay.property('hoveredWord'))
        assert visual_child(overlay.contentItem(),'captureWord_1').height() < visual_child(overlay.contentItem(),'captureWord_0').height()
    finally:
        bridge.close()
        for window in (overlay,popup,main): window.close()
        engine.deleteLater(); QTest.qWait(20)


@pytest.mark.parametrize('width', [370, 500])
def test_redesigned_card_order_independent_examples_and_plus(tmp_path, width):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'card.sqlite'))
    entry = Entry(word='experience', pos='v', tags=['Figurative'], ipa='/ɪkˈspɪəriəns/',
        definition_en='To undergo or encounter a situation or event.', synonyms=['undergo', 'encounter'],
        senses=[Sense(translation='испытывать; переживать', examples=[
            Example(en='You may experience a delay.', ru='Возможна задержка.')]),
            Sense(translation='испытать на себе', definition_en='To learn about something by going through it.', examples=[
                Example(en='I experienced it myself.', ru='Я испытал это на себе.')])])
    class Dictionary:
        def lookup(self, term): return [entry]
        def list(self): return []
    calls = []
    class Provider:
        def generate(self, record, mode, cancel):
            calls.append(mode)
            if mode == 'context':
                return ContextTranslation(translation_ru='Возможна задержка.',
                    explanation_ru='В предложении говорится о возможной задержке.'), 'test'
            return Explanation(definition_en='To have something happen to you.',
                usage_en='Used for events or feelings.', translation_ru='испытывать'), 'test'
    bridge.dictionary = Dictionary()
    bridge.gemini = Provider()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    assert engine.rootObjects()
    main = engine.rootObjects()[0]
    popup = main.findChild(QQuickWindow, 'wordPopup')
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    main.hide()
    bridge.lookup('experience', 'You may experience a delay.')
    popup.setWidth(width)
    popup.show(); QTest.qWait(120)
    card = visual_child(popup.contentItem(), 'popupWordCard')
    def item(name): return visual_child(popup.contentItem(), name)
    def click(name):
        button = item(name)
        scroller = card.property('contentItem')
        scroller.setProperty('contentY', 0)
        QTest.qWait(30)
        point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
        if point.y() > popup.height() - 60:
            scroller.setProperty('contentY', point.y() - popup.height()/2)
            QTest.qWait(30)
            point = button.mapToScene(QPointF(button.width()/2, button.height()/2))
        QTest.mouseClick(popup, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point.toPoint())
        QTest.qWait(40)
    def await_idle():
        deadline = time.monotonic() + 3
        while bridge.busy and time.monotonic() < deadline: QTest.qWait(20)
        assert not bridge.busy
    try:
        ordered = ['selectedWord', 'wordMetadata', 'showTranslation', 'dictionaryDefinition',
            'wordSynonyms', 'explainButton', 'contextSection', 'contextSentence', 'contextTranslatorButton']
        ys = [item(name).mapToScene(QPointF(0, 0)).y() for name in ordered]
        assert ys == sorted(ys)
        assert item('wordPronunciation').property('text') == entry.ipa
        assert not card.property('translationVisible')
        assert item('addWordButton').mapToScene(QPointF(0,0)).x() > item('selectedWord').mapToScene(QPointF(0,0)).x()
        click('showTranslation')
        assert card.property('translationVisible')
        assert not item('senseExamples_0').isVisible() and not item('senseExamples_1').isVisible()
        click('senseExamplesToggle_0')
        assert item('senseExamples_0').isVisible() and not item('senseExamples_1').isVisible()
        click('senseExamplesToggle_1')
        assert item('senseExamples_0').isVisible() and item('senseExamples_1').isVisible()
        click('senseRow_1')
        assert bridge.record.sense_index == 1
        assert item('dictionaryDefinition').property('text') == entry.senses[1].definition_en
        assert item('senseExamples_0').isVisible() and item('senseExamples_1').isVisible()
        click('showTranslation')
        assert not card.property('translationVisible')
        click('explainButton'); await_idle()
        click('contextTranslatorButton'); await_idle()
        assert calls == ['explain', 'context']
        click('addWordButton'); await_idle()
        assert bridge.storage.get_record(bridge.record.uid).status == 'saved'
        assert card.property('added') and not item('addWordButton').isEnabled()
        assert not main.findChild(QObject, 'savePreview').property('visible')
        bridge.lookup('another', '')
        QTest.qWait(30)
        assert not card.property('translationVisible')
        assert not item('contextTranslatorButton').isEnabled()
    finally:
        bridge.close()
        for window in [overlay, popup, main]: window.close()
        engine.deleteLater(); QTest.qWait(20)


def test_qml_word_selection_and_popup_save_preview(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge = Bridge(Storage(tmp_path / 'gui.sqlite'))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'golyah/qml/Main.qml')))
    assert engine.rootObjects(), 'QML must load without errors'
    main = engine.rootObjects()[0]
    overlay = main.findChild(QQuickWindow, 'captureOverlay')
    popup = main.findChild(QQuickWindow, 'wordPopup')
    preview = main.findChild(QObject, 'savePreview')
    try:
        bridge._overlay.update(visible=True, left=0, top=0, width=800, height=500,
            pixelWidth=800, pixelHeight=500,stage='recognizing')
        bridge.overlayChanged.emit(); QTest.qWait(100)
        hint=visual_child(overlay.contentItem(),'selectionHint')
        assert hint is None, 'No recognition or selection banner is displayed'
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(200, 215))
        QTest.qWait(30)
        assert bridge.overlay['visible'] and bridge.overlay['stage'] == 'recognizing'
        assert overlay.isVisible(), 'An early word click must not cancel recognition'
        bridge._overlay['stage']='ready'
        bridge.set_ocr_words([
                {'id': i, 'text': text, 'polygon': [[x,200],[x+65,200],[x+65,230],[x,230]],
                 'confidence': 1, 'line': 0, 'block': 0}
                for i, (text, x) in enumerate([('A', 100), ('quick', 180), ('look.', 260)])])
        bridge.overlayChanged.emit()
        QTest.qWait(200)
        assert overlay.color().alpha() == 1 and overlay.transientParent() is None
        assert overlay.mask().isEmpty(), 'A word-only mask would prevent screen dimming'
        assert 'image' not in bridge.overlay
        QTest.mouseMove(overlay, QPoint(500, 100))
        QTest.qWait(50)
        QTest.mouseMove(overlay, QPoint(200, 215))
        deadline = time.monotonic() + 2
        while overlay.property('hoveredWord') != 1 and time.monotonic() < deadline:
            QTest.qWait(20)
        assert overlay.property('hoveredWord') == 1
        assert overlay.property('hoveredSentence') == 0
        assert visual_child(overlay.contentItem(), 'captureWord_1').property('hovered')
        assert not visual_child(overlay.contentItem(), 'captureWord_2').property('hovered')
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(200, 215))
        ctrl_alt = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, ctrl_alt, QPoint(280, 215))
        assert bridge.overlay['selected'] == [1, 2]
        assert popup.isVisible() and bridge.record.term == 'quick look'
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, ctrl_alt, QPoint(280, 215))
        assert bridge.overlay['selected'] == [1] and bridge.record.term == 'quick'
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ControlModifier, QPoint(280, 215))
        assert bridge.overlay['selected'] == [1, 2], 'Both shortcuts share one selection'
        import golyah.bridge as module
        monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: QPoint(280,215))}))
        bridge.requestHotkeySelection(); QTest.qWait(20)
        assert bridge.overlay['selected'] == [1] and popup.isVisible() and bridge.record.term == 'quick'
        bridge.selectionHotkeyTriggered.emit(); QTest.qWait(20)
        assert bridge.overlay['selected'] == [1, 2] and popup.isVisible()
        assert visual_child(overlay.contentItem(),'selectionHint') is None
        assert bridge.record.term == 'quick look' and bridge.record.sentence == 'A quick look.'
        assert popup.isVisible()
        assert popup.flags() & Qt.WindowType.WindowType_Mask == Qt.WindowType.Tool
        card = main.findChild(QObject, 'popupWordCard')
        assert not card.property('translationVisible')
        main.hide()

        class Provider:
            def generate(self, record, mode, cancel):
                return Enrichment(explain=Explanation(definition_en='A short glance.',
                    usage_en='Describes looking briefly.', translation_ru='быстрый взгляд'),
                    context=ContextTranslation(translation_ru='Быстрый взгляд.', explanation_ru='О коротком взгляде.')), 'test'
        bridge.gemini = Provider()
        bridge.prepareSave('dictionary')
        deadline = time.monotonic() + 3
        while bridge.busy and time.monotonic() < deadline:
            QTest.qWait(20)
        assert preview.property('visible') and preview.property('width') > 400
        assert preview.property('parent') == popup.contentItem()
        definition = main.findChild(QObject, 'previewDefinition')
        definition.setProperty('text', 'My manual explanation.')
        bridge.overlayKeyTriggered.emit(0x1b)
        QTest.qWait(50)
        assert not preview.property('visible') and not popup.isVisible() and not overlay.isVisible()
        assert bridge.storage.get_record(bridge.record.uid).definition_en == 'My manual explanation.'
        assert not main.isVisible()
        assert not bridge.overlay['words']
        # A repeated hotkey selects the current word from the existing overlay.
        import golyah.bridge as module
        monkeypatch.setattr(module, 'QCursor', type('Cursor', (), {'pos': staticmethod(lambda: QPoint(200,215))}))
        bridge._overlay.update(visible=True, stage='ready')
        bridge.set_ocr_words([{'id': 0, 'text': 'quick', 'polygon': [[180,200],[245,200],[245,230],[180,230]],
                              'confidence': 1, 'line': 0, 'block': 0}])
        bridge.overlayChanged.emit(); QTest.qWait(50)
        bridge.requestHotkeyCapture(); QTest.qWait(50)
        assert popup.isVisible() and bridge.record.term == 'quick'
        QTest.keyClick(popup, Qt.Key.Key_Escape); QTest.qWait(50)
        assert not popup.isVisible() and not overlay.isVisible(), 'QML fallback also closes both windows'
        bridge._overlay.update(visible=True, stage='ready')
        bridge.set_ocr_words([{'id': 0, 'text': 'quick', 'polygon': [[180,200],[245,200],[245,230],[180,230]],
                              'confidence': 1, 'line': 0, 'block': 0}])
        bridge.overlayChanged.emit(); QTest.qWait(50)
        bridge.requestHotkeyCapture(); QTest.qWait(50)
        assert popup.isVisible()
        popup.hide(); QTest.qWait(50)
        assert not popup.isVisible() and overlay.isVisible()
        generation = bridge._generation
        QTest.keyClick(overlay, Qt.Key.Key_Return); QTest.qWait(50)
        bridge.overlayKey(0x0d); QTest.qWait(50)
        assert not popup.isVisible() and bridge._generation == generation, 'Enter does not reopen a selected word'
        bridge.requestHotkeyCapture(); QTest.qWait(50)
        assert popup.isVisible(), 'Alt+Q can reopen the card without new OCR'
        bridge.requestHotkeySelection(); QTest.qWait(50)
        assert not popup.isVisible() and overlay.isVisible() and not bridge.record.term
        QTest.keyClick(overlay, Qt.Key.Key_Return); QTest.qWait(50)
        bridge.overlayKey(0x0d); QTest.qWait(50)
        assert not popup.isVisible(), 'Enter no longer confirms or reopens a selection'
        bridge.requestHotkeySelection(); QTest.qWait(50)
        assert popup.isVisible() and bridge.record.term == 'quick'
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50,50))
        QTest.qWait(50)
        assert not overlay.isVisible() and not popup.isVisible() and not main.isVisible()
        assert not bridge.overlay['words'] and not bridge.overlay['selected'] and not bridge.overlayKeys.enabled
        # Early clicks keep recognition running; Escape cancels it explicitly.
        bridge._overlay.update(visible=True, stage='recognizing')
        bridge._ocr_pending = {123: True}
        bridge.overlayChanged.emit(); QTest.qWait(50)
        QTest.mouseClick(overlay, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(50,50))
        QTest.qWait(50)
        assert overlay.isVisible() and bridge._ocr_pending == {123: True}
        bridge.overlayKeyTriggered.emit(0x1b)
        QTest.qWait(50)
        assert not overlay.isVisible() and not bridge._ocr_pending and not bridge._capture_starting
        bridge.message('Контрольная ошибка захвата.', False)
        bridge.captureFailed.emit()
        QTest.qWait(50)
        assert main.isVisible() and bridge.status == 'Контрольная ошибка захвата.'
        # Explicit source choices must remain visible when lists refresh/reorder.
        bridge._settings.update(windows=[{'id':'99:123', 'label':'Chosen reader'}])
        bridge.selectCaptureSource('window', '99:123')
        QTest.qWait(50)
        mode = main.findChild(QObject, 'captureMode')
        source = main.findChild(QObject, 'captureSource')
        assert mode.property('currentIndex') == 0
        assert source.property('currentText') == 'Chosen reader'
        assert main.findChild(QObject, 'captureHotkey').property('text') == 'Alt+Q'
    finally:
        bridge.close()
        for window in [overlay, popup, main]:
            window.close()
        engine.deleteLater()
        QTest.qWait(20)


@pytest.mark.parametrize('scale',[1,1.5,2])
def test_hover_is_unique_between_wrapped_rows_after_plain_click(tmp_path,scale):
    app=QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    bridge=Bridge(Storage(tmp_path/'hover.sqlite'))
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend',bridge)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'golyah/qml/Main.qml')))
    main=engine.rootObjects()[0]; main.hide()
    overlay=main.findChild(QQuickWindow,'captureOverlay')
    popup=main.findChild(QQuickWindow,'wordPopup')
    try:
        bridge._overlay.update(visible=True,left=0,top=0,width=800,height=500,
            pixelWidth=800*scale,pixelHeight=500*scale)
        # Real OCR bounds can overlap vertically while describing different rows.
        bridge.set_ocr_words([{'id':i,'text':text,
            'polygon':[[x*scale,y*scale] for x,y in [(100,top),(250,top),(250,bottom),(100,bottom)]],
            'confidence':1,'line':i,'block':0}
            for i,(text,top,bottom) in enumerate([('upper',190,240),('lower.',232,282)])])
        bridge.overlayChanged.emit(); QTest.qWait(100)
        upper=visual_child(overlay.contentItem(),'captureWord_0')
        lower=visual_child(overlay.contentItem(),'captureWord_1')
        QTest.mouseMove(overlay,QPoint(500,100));QTest.qWait(30)
        assert upper.property('color').alpha()==0 and lower.property('color').alpha()==0
        assert visual_child(overlay.contentItem(),'sentenceHighlights') is None
        assert visual_child(overlay.contentItem(),'textDimming') is not None
        pixels=overlay.grabWindow()
        assert not pixels.isNull()
        factor=pixels.width()/overlay.width()
        def alpha_at(x,y):
            return pixels.pixelColor(round(x*factor),round(y*factor)).alpha()
        assert alpha_at(160,215) <= 1 and alpha_at(160,260) <= 1, 'Text keeps its original brightness'
        assert alpha_at(160,236) <= 1, 'Wrapped lines form a continuous clear contour'
        assert 70 <= alpha_at(500,100) <= 76, 'The surrounding screen has stronger dimming'
        assert 70 <= alpha_at(300,260) <= 76, 'Space beyond a shorter line stays dimmed'
        QTest.mouseMove(overlay,QPoint(500,100))
        QTest.mouseClick(overlay,Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,QPoint(160,215))
        QTest.qWait(50); assert popup.isVisible()
        assert upper.property('selected'), 'The clicked word stays marked while its card is open'
        popup.hide()
        QTest.mouseMove(overlay,QPoint(500,100)); QTest.mouseMove(overlay,QPoint(160,260)); QTest.qWait(50)
        upper=visual_child(overlay.contentItem(),'captureWord_0')
        lower=visual_child(overlay.contentItem(),'captureWord_1')
        assert overlay.property('hoveredWord')==1
        assert not upper.property('hovered') and lower.property('hovered')
        assert not upper.property('selected') and not lower.property('selected')
        assert upper.property('color').alpha()==0 and lower.property('color').alpha()>0
        # A shared row boundary must resolve to exactly one word at any scale.
        QTest.mouseMove(overlay,QPoint(160,236)); QTest.qWait(30)
        assert sum(item.property('hovered') for item in (upper,lower))==1
        QTest.mouseMove(overlay,QPoint(160,215)); QTest.qWait(30)
        assert upper.property('hovered') and not lower.property('hovered')
    finally:
        bridge.close()
        for window in [overlay,popup,main]:window.close()
        engine.deleteLater();QTest.qWait(20)
