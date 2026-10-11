import QtQuick
import "."
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: main
    width: 1280; height: 900; minimumWidth: 1040; minimumHeight: 680
    visible: true; title: "Golyahki"
    color: Theme.background
    font.family: Theme.uiFont
    font.pixelSize: Theme.px(15)
    palette.window: Theme.surface
    palette.windowText: Theme.text
    palette.base: Theme.background
    palette.alternateBase: Theme.raised
    palette.text: Theme.text
    palette.button: Theme.raised
    palette.buttonText: Theme.text
    palette.highlight: Theme.accent
    palette.highlightedText: Theme.accentInk
    property int page: 0
    property int settingsPage: 0
    readonly property var pageTitles: ["Поиск слова", "Мои слова", "Словари", "Оформление", "Конструктор Anki", "Настройки"]
    property var statuses: ({saved: "Сохранено", draft: "Черновик", preview: "Проверить", pending_anki: "Ожидает Anki"})

    Component.onCompleted: backend.initialize()
    Connections {
        target: backend
        function onCaptureRequested() {
            if (preview.visible) preview.close()
            cardPopup.manuallyPlaced = false
            main.hide()
            cardPopup.hide()
            if (overlayWindow.visible) overlayWindow.hide()
            captureDelay.restart()
        }
        function onCaptureFailed() {
            backend.closeOverlay()
            main.show(); main.raise(); main.requestActivate()
        }
        function onPreviewReady() {
            if (cardPopup.visible) cardPopup.enableKeyboard()
            preview.fill()
            preview.open()
        }
        function onCardChanged() {
            if (backend.overlay.visible && backend.card.term) {
                cardPopup.acceptsKeyboard = false
                cardPopup.show()
                cardPopup.raise()
                if (!backend.overlay.passive) cardPopup.requestActivate()
            } else if (backend.overlay.visible) {
                cardPopup.hide()
            }
        }
        function onResetCard() { if (backend.overlay.visible) cardPopup.place() }
    }
    Timer { id: captureDelay; interval: backend.overlay.settleMs || 70; onTriggered: backend.startCapture() }

    RowLayout {
        anchors.fill: parent; spacing: 0
        Rectangle {
            Layout.preferredWidth: 232; Layout.fillHeight: true; color: Theme.sidebar
            ColumnLayout {
                anchors.fill: parent; anchors.margins: 22; spacing: 10
                RowLayout {
                    spacing: 6
                    Image { source: "BrandMark.svg"; Layout.preferredWidth: 34; Layout.preferredHeight: 34; fillMode: Image.PreserveAspectFit }
                    Label { text: "Golyahki"; font.pixelSize: Theme.px(29); font.weight: Font.Medium; color: Theme.text }
                }
                Label { text: "СЛОВА ИЗ ВАШЕГО МИРА"; font.pixelSize: Theme.px(10); font.letterSpacing: 1.7; color: Theme.faint }
                Item { Layout.preferredHeight: 30 }
                Repeater {
                    model: ["Поиск", "Мои слова", "Словари", "Оформление", "Конструктор Anki", "Настройки"]
                    delegate: Button {
                        id: navButton
                        required property string modelData
                        required property int index
                        Layout.fillWidth: true; implicitHeight: Math.max(46, Theme.px(14) * 2 + 12)
                        hoverEnabled: true; Accessible.name: modelData
                        background: Rectangle {
                            radius: 11; color: main.page === navButton.index ? Theme.accentSoft : navButton.hovered ? Theme.surface : "transparent"
                            border.color: Theme.accent; border.width: navButton.activeFocus ? 1 : 0
                        }
                        contentItem: RowLayout {
                            spacing: 12
                            CardIcon { kind: ["search", "book", "layers", "palette", "layers", "settings"][navButton.index]; ink: main.page === navButton.index ? Theme.accent : Theme.muted; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                            Label { text: navButton.modelData; color: main.page === navButton.index ? Theme.text : Theme.muted; font.pixelSize: Theme.px(14); Layout.fillWidth: true; wrapMode:Text.Wrap }
                        }
                        onClicked: main.page = index
                    }
                }
                Item { Layout.fillHeight: true }
                Label { Layout.fillWidth: true; text: "Захват экрана\n" + backend.settings.hotkey
                    color: Theme.muted; font.pixelSize: Theme.px(13); lineHeight: 1.5 }
                SoftButton { Layout.fillWidth: true; text: "Захватить"; enabled: !backend.busy
                    onClicked: backend.requestCapture() }
                Label { text: backend.version + " · Ваш личный словарь"; font.pixelSize: Theme.px(11); color: Theme.faint }
            }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 0
            Rectangle {
                Layout.fillWidth: true; implicitHeight: 78; color: Theme.background
                RowLayout {
                    anchors.fill: parent; anchors.leftMargin: 28; anchors.rightMargin: 28
                    Label { text: main.pageTitles[main.page]; font.pixelSize: Theme.px(18); font.weight: Font.DemiBold; color: Theme.text }
                    Item { Layout.fillWidth: true }
                    Label { text: backend.settings.hotkey; color: Theme.muted; font.pixelSize: Theme.px(12) }
                    SoftButton { text: "Захватить текст"; accent: true; enabled: !backend.busy; onClicked: backend.requestCapture() }
                }
                Rectangle { height: 1; anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom; color: Theme.border }
            }
            StackLayout {
                Layout.fillWidth: true; Layout.fillHeight: true; currentIndex: main.page
                Item {
                    RowLayout {
                        objectName: "searchRow"
                        anchors.fill: parent; anchors.margins: 28; spacing: 26
                        ColumnLayout {
                            objectName: "searchInputs"
                            Layout.preferredWidth: 255; Layout.maximumWidth: 255; Layout.minimumWidth: 200
                            Layout.fillHeight: true; spacing: 15
                            Label { text: "Новое слово,\nзнакомый контекст"; font.pixelSize: Theme.px(21); font.weight: Font.DemiBold; wrapMode: Text.Wrap; Layout.fillWidth: true }
                            Label { Layout.fillWidth: true; text: "Из словаря, книги или прямо с экрана."
                                color: Theme.muted; wrapMode: Text.Wrap; font.pixelSize: Theme.px(14) }
                            Field { id: searchTerm; Layout.fillWidth: true; placeholderText: "Слово или фраза"
                                selectByMouse: true; onAccepted: backend.lookup(text, searchContext.text) }
                            TextBox { id: searchContext; Layout.fillWidth: true; Layout.preferredHeight: 145
                                placeholderText: "Исходное предложение\n(необязательно)"; wrapMode: TextEdit.Wrap; selectByMouse: true }
                            SoftButton { Layout.fillWidth: true; text: "Найти"; accent: true; enabled: !backend.busy && searchTerm.text.trim().length > 0
                                onClicked: backend.lookup(searchTerm.text, searchContext.text) }
                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
                            Label { Layout.fillWidth: true; text: "Читайте. Выбирайте слова.\nСохраняйте важное."
                                color: Theme.muted; wrapMode: Text.Wrap; font.pixelSize: Theme.px(14); lineHeight: 1.6 }
                            SoftButton { text: "Импортировать словарь"; Layout.fillWidth: true
                                onClicked: backend.chooseDictionary(); enabled: !backend.busy }
                            Item { Layout.fillHeight: true }
                        }
                        Rectangle {
                            objectName: "searchCard"
                            Layout.fillHeight: true; Layout.fillWidth: true; Layout.minimumWidth: 350
                            Layout.preferredWidth: backend.appearance.cardWidth; Layout.maximumWidth: backend.appearance.cardWidth; radius: backend.appearance.cardRadius; color: Theme.cardBackground
                            gradient: backend.appearance.cardGradient ? mainCardGradient : null
                            Gradient { id: mainCardGradient; GradientStop { position:0; color:Theme.cardBackground } GradientStop { position:1; color:Theme.cardBackgroundEnd } }
                            border.color: Theme.cardBorder
                            WordCard { objectName: "mainWordCard"; anchors.fill: parent; anchors.margins: 22 }
                        }
                    }
                }
                Item {
                  ColumnLayout {
                    anchors.fill: parent; anchors.margins: 28
                    spacing: 18
                    Label { text: "Ваша коллекция"; font.pixelSize: Theme.px(28); font.weight: Font.DemiBold }
                    Label { text: "Слова, контекст и объяснения — всё в одном месте."; color: Theme.muted }
                    RowLayout {
                        Layout.fillWidth: true
                        Field { id: recordQuery; Layout.fillWidth: true; placeholderText: "Поиск по словам, переводу и контексту"
                            onTextChanged: recordSearchTimer.restart() }
                        Timer { id: recordSearchTimer; interval: 150; onTriggered: backend.filterRecords(recordQuery.text, draftCheck.checked) }
                        CheckBox { id: draftCheck; text: "Черновики"; onToggled: backend.filterRecords(recordQuery.text, checked) }
                        SoftButton { text: "Импорт JSON"; onClicked: backend.transferDictionary(true) }
                        SoftButton { text: "Экспорт JSON"; onClicked: backend.transferDictionary(false) }
                    }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 10
                        model: backend.saved
                        ScrollBar.vertical: ScrollBar {}
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width; height: savedContent.implicitHeight + 28
                            radius: 12; color: Theme.surface; border.color: Theme.border
                            RowLayout {
                                id: savedContent; x: 16; y: 14; width: parent.width - 32
                                ColumnLayout {
                                    Layout.fillWidth: true; spacing: 5
                                    Label { text: modelData.term; font.pixelSize: Theme.px(21); font.weight: Font.DemiBold }
                                    Label { text: modelData.sentence || "Без контекста"; Layout.fillWidth: true
                                        elide: Text.ElideRight; color: Theme.muted; font.pixelSize: Theme.px(14) }
                                    Label { text: main.statuses[modelData.status] || modelData.status
                                        color: modelData.status === "saved" ? Theme.accent : "#e6b593"; font.pixelSize: Theme.px(12) }
                                }
                                SoftButton { text: modelData.status === "saved" ? "Открыть" : "Продолжить"
                                    enabled: !backend.busy; onClicked: { backend.loadRecord(modelData.uid); main.page = 0 } }
                                SoftButton { text: "×"; quiet: true; onClicked: backend.deleteRecord(modelData.uid) }
                            }
                        }
                        Label { anchors.centerIn: parent; visible: backend.saved.length === 0
                            text: "Добавьте первое слово кнопкой + на карточке.\nПри сбое Gemini здесь останется черновик."
                            horizontalAlignment: Text.AlignHCenter; color: Theme.muted; lineHeight: 1.7 }
                    }
                }
                  }
                Item {
                  ColumnLayout {
                    anchors.fill: parent; anchors.margins: 28
                    spacing: 18
                    Label { text: "Подключённые словари"; font.pixelSize: Theme.px(28); font.weight: Font.DemiBold }
                    Label { text: "Yomitan ZIP и JSON. Приоритет выше — словарь появляется первым."; color: Theme.muted; Layout.fillWidth: true; wrapMode: Text.Wrap }
                    RowLayout {
                        SoftButton { text: "+ Импортировать словарь"; accent: true; onClicked: backend.chooseDictionary(); enabled: !backend.busy }
                        Label { text: "Повторный импорт обновляет словарь."; color: Theme.faint; font.pixelSize: Theme.px(13) }
                    }
                    ListView {
                        Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10; clip: true; model: backend.dictionaries
                        delegate: Rectangle {
                            required property var modelData
                            width: ListView.view.width; height: 105; radius: 12; color: Theme.surface
                            RowLayout {
                                anchors.fill: parent; anchors.margins: 16
                                CheckBox { checked: !!modelData.enabled; onToggled: backend.configureDictionary(modelData.id, checked, modelData.priority) }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Label { text: modelData.title; font.pixelSize: Theme.px(21); font.weight: Font.DemiBold }
                                    Label { text: modelData.count.toLocaleString() + " записей · " + modelData.revision; color: Theme.muted; font.pixelSize: Theme.px(13) }
                                }
                                Label { text: "Приоритет"; color: Theme.muted; font.pixelSize: Theme.px(12) }
                                SpinBox { from: -999; to: 999; value: modelData.priority; editable: true
                                    onValueModified: backend.configureDictionary(modelData.id, !!modelData.enabled, value) }
                                SoftButton { text: "Удалить"; quiet: true; onClicked: backend.deleteDictionary(modelData.id) }
                            }
                        }
                        Label { anchors.centerIn: parent; visible: backend.dictionaries.length === 0
                            text: "Импортируйте wty-en-ru.zip, чтобы начать поиск."; color: Theme.muted }
                    }
                }
                  }
                Item {
                    AppearancePage { anchors.fill: parent; anchors.margins: 28 }
                }
                Item {
                    Loader { anchors.fill:parent; anchors.margins:28; active:main.page === 4; source:"CardBuilderPage.qml" }
                }
                Item {
                  ScrollView {
                    anchors.fill: parent; anchors.margins: 28
                    clip: true; contentWidth: availableWidth
                    ColumnLayout {
                        width: parent.width; spacing: 17
                        Label { text: "Настройки"; font.pixelSize: Theme.px(28); font.weight: Font.DemiBold }
                        RowLayout {
                            Layout.fillWidth: true; spacing: 10
                            Repeater {
                                model: ["Захват экрана", "Gemini", "Anki"]
                                delegate: SoftButton {
                                    required property string modelData
                                    required property int index
                                    text: modelData; accent: main.settingsPage === index; quiet: main.settingsPage !== index
                                    onClicked: main.settingsPage = index
                                }
                            }
                            Item { Layout.fillWidth: true }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 17; visible: main.settingsPage === 0
                        Label { text: "ЗАХВАТ ЭКРАНА"; font.pixelSize: Theme.px(11); font.letterSpacing: 1.5; color: Theme.accent }
                        RowLayout {
                            Layout.fillWidth: true
                            Field { id: hotkeyField; objectName: "captureHotkey"; text: backend.settings.hotkey; Layout.preferredWidth: 210; placeholderText: "Alt+Q" }
                            Choice { id: captureMode; objectName: "captureMode"; Layout.fillWidth: true; model: ["Окна", "Экраны"]
                                currentIndex: ["window", "monitor"].indexOf(backend.settings.captureMode)
                                onActivated: index => backend.selectCaptureSource(index === 0 ? "window" : "monitor",
                                    index === 0 ? backend.settings.windowId : backend.settings.screenId) }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Choice {
                                id: captureSource; objectName: "captureSource"; Layout.fillWidth: true
                                model: captureMode.currentIndex === 0 ? backend.settings.windows : backend.settings.screens
                                textRole: "label"; valueRole: "id"
                                currentIndex: {
                                    let wanted = captureMode.currentIndex === 0 ? backend.settings.windowId : backend.settings.screenId
                                    let values = captureMode.currentIndex === 0 ? backend.settings.windows : backend.settings.screens
                                    return values.findIndex(item => item.id === wanted)
                                }
                                displayText: currentIndex >= 0 ? currentText : (captureMode.currentIndex === 0 ? "Выберите открытое окно" : "Выберите экран")
                                onActivated: index => backend.selectCaptureSource(captureMode.currentIndex === 0 ? "window" : "monitor", currentValue)
                                ToolTip.visible: hovered && currentIndex >= 0
                                ToolTip.text: currentText
                            }
                            SoftButton { objectName: "refreshCaptureSources"; text: "Обновить список"; quiet: true; onClicked: backend.refreshCaptureSources() }
                        }
                        Label { Layout.fillWidth: true; font.pixelSize: Theme.px(13); color: Theme.muted; wrapMode: Text.Wrap
                            text: captureMode.currentIndex === 0 ? "Выбранное окно откроется поверх остальных; свёрнутое окно восстановится перед распознаванием."
                                : backend.settings.hotkey + " распознаёт выбранный экран, независимо от положения курсора." }
                        Label { Layout.fillWidth: true; font.pixelSize: Theme.px(13); color: Theme.muted; wrapMode: Text.Wrap
                            text: "Alt+Q открывает слово под курсором. Ctrl+Alt+Q добавляет или убирает следующие слова; карточка фразы обновляется сразу. Также можно использовать Ctrl+ЛКМ." }
                        CheckBox {
                            objectName: "focusOnHover"
                            text: "Переключать ввод на Golyahki при наведении"
                            checked: backend.settings.focusOnHover
                            onToggled: backend.setFocusOnHover(checked)
                        }
                        Label { Layout.fillWidth: true; font.pixelSize: Theme.px(13); color: Theme.muted; wrapMode: Text.Wrap
                            text: "Включите, если игра всё ещё реагирует на кнопки карточки. Используйте режим «окно без рамки»: эксклюзивная полноэкранная игра может сворачиваться при переключении ввода. После закрытия оверлея управление возвращается игре." }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Дополнительная кнопка мыши"; color: Theme.muted }
                            Choice {
                                objectName: "overlayMouseButton"; Layout.fillWidth: true
                                model: ["Не использовать", "Mouse 4 · Назад", "Mouse 5 · Вперёд"]
                                currentIndex: ["none", "mouse4", "mouse5"].indexOf(backend.settings.overlayMouseButton)
                                onActivated: index => backend.setOverlayMouseButton(["none", "mouse4", "mouse5"][index])
                            }
                        }
                        Label { Layout.fillWidth: true; font.pixelSize: Theme.px(13); color: Theme.muted; wrapMode: Text.Wrap
                            text: "Выбранная боковая кнопка выбирает слова и нажимает кнопки карточки. Ctrl добавляет слово к выделению. ЛКМ также работает. Вне Golyahki назначение кнопки сохраняется." }
                        RowLayout {
                            Layout.fillWidth: true
                            Label { text: "Распознавание текста"; color: Theme.muted }
                            Choice { objectName: "ocrEngine"; Layout.fillWidth: true
                                model: ["Авто · WindowsOCR, резерв PaddleOCR", "WindowsOCR · быстро", "PaddleOCR · сложные шрифты"]
                                currentIndex: ["auto","windows","paddle"].indexOf(backend.settings.ocrEngine)
                                onActivated: index => backend.selectOCREngine(["auto","windows","paddle"][index]) }
                        }
                        Label { Layout.fillWidth: true; wrapMode: Text.Wrap; font.pixelSize: Theme.px(13); color: Theme.muted
                            text: "Авто использует WindowsOCR и проверяет пропуски между словами через PaddleOCR. Первая такая проверка может занять несколько секунд. Для сложных шрифтов можно выбрать PaddleOCR." }
                        SoftButton { text: "Захватить выбранный источник"; enabled: !backend.busy && captureSource.currentIndex >= 0
                            onClicked: backend.requestCapture() }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 17; visible: main.settingsPage === 1
                        Label { text: "GEMINI"; font.pixelSize: Theme.px(11); font.letterSpacing: 1.5; color: Theme.accent }
                        Label { text: backend.settings.hasKey ? "✓ API-ключ сохранён в Windows" : "Добавьте свой API-ключ Google AI Studio"
                            color: backend.settings.hasKey ? Theme.accent : Theme.muted }
                        RowLayout {
                            Layout.fillWidth: true
                            Field { id: keyField; Layout.fillWidth: true; placeholderText: "Новый API-ключ"; echoMode: TextInput.Password; selectByMouse: true }
                            SoftButton { text: "Сохранить ключ"; enabled: keyField.text.length > 0; onClicked: { backend.saveKey(keyField.text); keyField.clear() } }
                            SoftButton { text: "Удалить"; quiet: true; enabled: backend.settings.hasKey; onClicked: backend.saveKey("") }
                        }
                        RowLayout {
                            Layout.fillWidth: true
                            Choice { id: modelField; Layout.fillWidth: true; editable: true
                                model: backend.settings.models.length ? backend.settings.models : [backend.settings.model]
                                editText: backend.settings.model }
                            SoftButton { text: "Доступные модели"; enabled: !backend.busy; onClicked: backend.checkModels() }
                        }
                        Label { objectName: "thinkingStatus"; Layout.fillWidth: true
                            text: backend.thinkingStatus(modelField.editText)
                            wrapMode: Text.Wrap; color: Theme.accent; font.pixelSize: Theme.px(13) }
                        CheckBox { objectName: "geminiFallback"; Layout.fillWidth: true
                            text: "Использовать Flash Lite 3.5 при лимите Gemini 2.5 Flash"
                            checked: backend.settings.geminiFallback
                            onToggled: backend.setGeminiFallback(checked) }
                        Label { Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(13)
                            text: "Если лимит Flash исчерпан, новые ответы запрашиваются у Flash Lite 3.5 с минимумом размышлений. Если обе модели достигли лимита, приложение покажет время повтора." }
                        Label { Layout.fillWidth: true; text: "Explain и Context Translator вызываются по кнопке. При сохранении приложение запрашивает недостающие результаты."
                            wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(14) }
                        }
                        ColumnLayout {
                            Layout.fillWidth: true; spacing: 17; visible: main.settingsPage === 2
                        Label { text: "ANKI"; font.pixelSize: Theme.px(11); font.letterSpacing: 1.5; color: Theme.accent }
                        RowLayout {
                            Layout.fillWidth: true
                            Choice { id: deckField; objectName: "ankiDeck"; Layout.fillWidth: true
                                model: ["Только Dictionary"].concat(backend.settings.decks.length
                                    ? backend.settings.decks : backend.settings.deck ? [backend.settings.deck] : [])
                                currentIndex: Math.max(0, model.indexOf(backend.settings.deck))
                                onActivated: index => backend.selectAnkiDeck(index > 0 ? currentText : "") }
                            SoftButton { text: "Подключить Anki"; enabled: !backend.busy; onClicked: backend.checkAnki() }
                        }
                        Label { Layout.fillWidth: true; text: backend.settings.deck
                            ? "Плюс в карточке сохраняет слово в Dictionary и колоду «" + backend.settings.deck + "». Anki должна быть открыта. При ошибке слово остаётся в черновиках для повторной отправки."
                            : "Запустите Anki с AnkiConnect, нажмите «Подключить Anki» и выберите колоду. Выбор сохраняется сразу."
                            wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(14) }
                        Label { Layout.fillWidth: true; text: "Карточка: слово и предложение → перевод, Explain, употребление, разбор контекста и примеры. Словарные пометки, транскрипция и синонимы переносятся, если они есть. Оформление карточек настраивается в разделе «Оформление» и сохраняет тёмный фон в Anki."
                            wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(13) }
                        }
                        SoftButton { text: "Сохранить настройки"; accent: true; enabled: !backend.busy
                            onClicked: backend.saveSettings(hotkeyField.text, ["window", "monitor"][captureMode.currentIndex], modelField.editText, backend.settings.deck) }
                        Item { Layout.preferredHeight: 25 }
                    }
                }
                }
            }
            Rectangle {
                Layout.fillWidth: true; Layout.preferredHeight: footerContent.implicitHeight + 22
                color: Theme.sidebar
                RowLayout {
                    id: footerContent; x: 22; y: 11; width: parent.width - 44
                    BusyIndicator { running: backend.busy; visible: backend.busy; Layout.preferredWidth: 22; Layout.preferredHeight: 22 }
                    Label { text: backend.status; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(12) }
                    SoftButton { text: "Отмена"; visible: backend.busy; quiet: true; onClicked: backend.cancel() }
                }
            }
        }
    }

    Dialog {
        id: preview; objectName: "savePreview"; modal: true; title: "Проверьте карточку"
        property string recordUid: ""
        property bool confirmed: false
        parent: cardPopup.visible ? cardPopup.contentItem : main.contentItem
        height: Math.min(710, parent.height - 30); anchors.centerIn: parent
        width: Math.min(700, parent.width - 30)
        background: Rectangle { color: Theme.surface; radius: 16; border.color: Theme.border }
        function fill() {
            recordUid = backend.card.uid
            confirmed = false
            translationEdit.text = backend.card.translation
            definitionEdit.text = backend.card.definition_en
            usageEdit.text = backend.card.usage_en
            contextTranslationEdit.text = backend.card.sentence_translation
            contextExplanationEdit.text = backend.card.context_explanation
            examplesEdit.text = backend.card.examples.map(e => e.en + "\n" + e.ru).join("\n\n")
        }
        function saveEdits() {
            if (backend.card.uid !== recordUid) return
            const examples = examplesEdit.text.trim() ? examplesEdit.text.trim().split(/\n\s*\n/).map(block => {
                const lines = block.split("\n"); return {en: lines[0], ru: lines.slice(1).join("\n")}
            }) : []
            backend.updatePreview(JSON.stringify({translation: translationEdit.text, definition_en: definitionEdit.text,
                usage_en: usageEdit.text, sentence_translation: contextTranslationEdit.text,
                context_explanation: contextExplanationEdit.text, examples: examples}))
        }
        onClosed: { if (!confirmed) saveEdits() }
        contentItem: ScrollView {
            clip: true; contentWidth: availableWidth
            ColumnLayout {
                width: parent.width; spacing: 9
                Label { text: backend.card.term; font.pixelSize: Theme.px(25); font.weight: Font.DemiBold }
                Label { text: backend.card.sentence || "Без исходного предложения"; wrapMode: Text.Wrap; Layout.fillWidth: true; color: Theme.muted }
                Label { text: "Перевод"; font.pixelSize: Theme.px(12) }
                TextBox { id: translationEdit; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "English definition"; font.pixelSize: Theme.px(12) }
                TextBox { id: definitionEdit; objectName: "previewDefinition"; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "Usage"; font.pixelSize: Theme.px(12) }
                TextBox { id: usageEdit; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "Перевод предложения"; font.pixelSize: Theme.px(12); visible: !!backend.card.sentence }
                TextBox { id: contextTranslationEdit; visible: !!backend.card.sentence; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "Объяснение контекста"; font.pixelSize: Theme.px(12); visible: !!backend.card.sentence }
                TextBox { id: contextExplanationEdit; visible: !!backend.card.sentence; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "Примеры: английская строка, затем русская; пустая строка разделяет примеры"; wrapMode: Text.Wrap; Layout.fillWidth: true; font.pixelSize: Theme.px(12) }
                TextBox { id: examplesEdit; Layout.fillWidth: true; wrapMode: TextEdit.Wrap; selectByMouse: true }
                Label { text: "Источник: " + backend.card.sources.join(" · ") + " · Gemini " + backend.card.llm_model
                    wrapMode: Text.Wrap; Layout.fillWidth: true; color: Theme.faint; font.pixelSize: Theme.px(12) }
            }
        }
        footer: RowLayout {
            spacing: 14
            SoftButton { text: "Оставить для проверки"; quiet: true; onClicked: preview.close() }
            Item { Layout.fillWidth: true }
            SoftButton {
                text: backend.card.destination === "anki" ? "Добавить в Anki" : "Сохранить в Dictionary"; accent: true
                onClicked: {
                    preview.saveEdits()
                    if (backend.confirmSave()) { preview.confirmed = true; preview.close() }
                }
            }
        }
    }

    CaptureOverlay { id: overlayWindow; popup: cardPopup }

    Window {
        id: cardPopup; objectName: "wordPopup"
        property bool acceptsKeyboard: false
        property bool manuallyPlaced: false
        function enableKeyboard() {
            acceptsKeyboard = true
            show(); requestActivate()
        }
        transientParent: null
        title: "Golyahki · " + backend.card.term
        width: Math.min(backend.appearance.cardWidth, overlayWindow.screen.width - 40)
        height: Math.min(710, overlayWindow.screen.height - 60, Math.max(400, popupCard.naturalHeight + 76))
        minimumWidth: 320; minimumHeight: 400
        flags: Qt.Tool | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint |
            Qt.WindowStaysOnTopHint | (backend.overlay.passive && !acceptsKeyboard ? Qt.WindowDoesNotAcceptFocus : 0)
        color: Theme.cardBackground
        onHeightChanged: if (visible) place()
        onWidthChanged: if (visible) place()
        function place() {
            const targetScreen = manuallyPlaced ? screen : overlayWindow.screen
            const frame = backend.windowFrameMargins(cardPopup)
            const left = targetScreen.virtualX + frame.left, top = targetScreen.virtualY + frame.top
            const right = targetScreen.virtualX + targetScreen.width - frame.right
            const bottom = targetScreen.virtualY + targetScreen.height - frame.bottom
            if (manuallyPlaced) {
                x = Math.max(left, Math.min(x, right - width))
                y = Math.max(top, Math.min(y, bottom - height))
                return
            }
            let nextX = backend.overlay.anchorX + 18 + frame.left
            let nextY = backend.overlay.anchorY + 20 + frame.top
            if (nextX + width > right) nextX = backend.overlay.anchorX - width - 18 - frame.right
            if (nextY + height > bottom) nextY = backend.overlay.anchorY - height - 20 - frame.bottom
            x = Math.max(left, Math.min(nextX, right - width))
            y = Math.max(top, Math.min(nextY, bottom - height))
        }
        Rectangle {
            anchors.fill: parent; color: Theme.cardBackground
            radius: backend.appearance.cardRadius; border.color: Theme.cardBorder
            gradient: backend.appearance.cardGradient ? popupGradient : null
            Gradient { id: popupGradient; GradientStop { position:0; color:Theme.cardBackground } GradientStop { position:1; color:Theme.cardBackgroundEnd } }
        }
        ColumnLayout {
            anchors.fill: parent; anchors.margins: 20; spacing: 10
            WordCard { id: popupCard; objectName: "popupWordCard"; Layout.fillWidth: true; Layout.fillHeight: true; focus: true
                onEditingRequested: cardPopup.enableKeyboard()
                Keys.onEscapePressed: backend.closeOverlay() }
            RowLayout {
                Layout.fillWidth: true
                BusyIndicator { running: backend.busy; visible: backend.busy; Layout.preferredWidth: 24; Layout.preferredHeight: 24 }
                Label { text: backend.status; textFormat: Text.PlainText; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(12) }
                SoftButton { text: "Отмена"; visible: backend.busy; quiet: true; onClicked: backend.cancel() }
            }
        }
        Connections {
            target: backend
            function onOverlayChanged() {
                if (!backend.overlay.visible) {
                    if (cardPopup.visible && preview.visible) preview.close()
                    cardPopup.hide()
                    cardPopup.manuallyPlaced = false
                }
            }
        }
    }
}
