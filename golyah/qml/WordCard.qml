import QtQuick
import "."
import QtQuick.Controls
import QtQuick.Layouts

ScrollView {
    id: root
    font.family: Theme.cardFont
    property var cardData: backend.card
    property bool previewOnly: false
    property bool translationVisible: false
    property bool examplesOpen: false
    property var expandedSenses: ({})
    property bool llmExamplesOpen: false
    property bool etymologyOpen: false
    property bool notesOpen: false
    property bool editOpen: false
    readonly property real naturalHeight: cardBody.implicitHeight
    signal editingRequested()
    property var entry: cardData.entries && cardData.entries.length
        ? cardData.entries[cardData.entry_index || 0] : null
    property var sense: entry && entry.senses.length
        ? entry.senses[Math.min(cardData.sense_index || 0, entry.senses.length - 1)] : null
    property string dictionaryDefinition: sense && sense.definition_en
        ? sense.definition_en : entry ? entry.definition_en || "" : ""
    property var wordSynonyms: entry && entry.synonyms.length ? entry.synonyms : cardData.synonyms || []
    property bool added: !!cardData.saved && (!backend.settings.deck || !!cardData.saved_to_anki)
    property string entryKey: (cardData.entry_index || 0) + "|" + (entry ? entry.dictionary + "|" + entry.pos : "")
    property var explanationExamples: (cardData.examples || []).filter(ex =>
        !sense || !sense.examples.some(item => item.en === ex.en && item.ru === ex.ru))
    clip: true
    rightPadding: 6
    contentWidth: availableWidth
    ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
    ScrollBar.vertical.policy: ScrollBar.AsNeeded
    onEntryKeyChanged: { expandedSenses = ({}); etymologyOpen = false; notesOpen = false }
    onCardDataChanged: {
        termEdit.text = cardData.term || ""
        sentenceEdit.text = cardData.sentence || ""
    }
    function partOfSpeech(pos) {
        const names = {v: "Verb", verb: "Verb", n: "Noun", noun: "Noun", adj: "Adjective",
            adjective: "Adjective", adv: "Adverb", adverb: "Adverb", prep: "Preposition",
            pron: "Pronoun", conj: "Conjunction", interj: "Interjection", det: "Determiner"}
        return (pos || "").split(/\s+/).map(token => names[token] || token).join(" · ")
    }
    function entryLabel(value) {
        const pos = partOfSpeech(value.pos)
        const multipleDictionaries = (cardData.entries || []).some(other => other.dictionary !== value.dictionary)
        return pos ? pos + (multipleDictionaries ? " · " + value.dictionary : "") : value.dictionary
    }
    function exampleCount(count) {
        const last = count % 10, tens = count % 100
        return count + " " + (last === 1 && tens !== 11 ? "пример"
            : last >= 2 && last <= 4 && (tens < 12 || tens > 14) ? "примера" : "примеров")
    }
    function toggleSense(index) {
        const updated = Object.assign({}, expandedSenses)
        updated[index] = !updated[index]
        expandedSenses = updated
    }
    Connections {
        target: backend
        function onResetCard() {
            if (root.previewOnly) return
            root.translationVisible = false
            root.examplesOpen = false
            root.expandedSenses = ({})
            root.llmExamplesOpen = false
            root.etymologyOpen = false
            root.notesOpen = false
            root.editOpen = false
            if (root.contentItem && root.contentItem.contentY !== undefined) root.contentItem.contentY = 0
        }
    }

    ColumnLayout {
        id: cardBody
        width: root.availableWidth
        spacing: backend.appearance.cardSpacing
        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Label {
                objectName: "selectedWord"
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                text: root.cardData.term || "Your next word"
                textFormat: Text.PlainText
                font.pixelSize: Theme.cp(30)
                fontSizeMode: Text.HorizontalFit
                minimumPixelSize: Theme.cp(20)
                font.weight: Font.DemiBold
                color: Theme.cardText
                wrapMode: Text.Wrap
            }
            CardAction {
                objectName: "addWordButton"
                symbol: root.added ? "check" : "plus"
                accent: true
                tooltip: root.added ? "Слово сохранено" : backend.settings.deck
                    ? "Добавить в Dictionary и Anki" : "Добавить в Dictionary"
                enabled: !!root.cardData.term && !backend.busy && !root.added
                Layout.alignment: Qt.AlignTop
                onClicked: if (!root.previewOnly) backend.addWord()
            }
        }
        Flow {
            objectName: "wordMetadata"
            Layout.fillWidth: true
            spacing: 8
            visible: !!root.entry && (!!root.entry.pos || !!root.entry.ipa
                || (root.entry.tags && root.entry.tags.length) || root.cardData.entries.length > 1)
            ComboBox {
                id: posSelector
                objectName: "entrySelector"
                visible: root.cardData.entries && root.cardData.entries.length > 1
                model: (root.cardData.entries || []).map(e => root.entryLabel(e))
                currentIndex: root.cardData.entry_index || 0
                width: Math.min(root.availableWidth, 220, Math.max(88, selectorMetrics.advanceWidth + 42))
                height: 27
                leftPadding: 9; rightPadding: 25
                font.pixelSize: Theme.cp(12)
                palette.text: Theme.cardText
                palette.button: Theme.cardPanel
                contentItem: Label {
                    text: posSelector.displayText
                    textFormat: Text.PlainText
                    font: posSelector.font; color: Theme.cardText
                    verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight
                }
                indicator: CardIcon {
                    kind: "chevron"; rotation: 90; ink: Theme.cardMuted
                    width: 12; height: 12; x: posSelector.width - 21; y: 8
                }
                background: Rectangle { color: Theme.cardPanel; radius: 4 }
                onActivated: backend.selectSense(currentIndex, 0)
            }
            TextMetrics { id: selectorMetrics; font: posSelector.font; text: posSelector.displayText }
            Rectangle {
                visible: !!root.entry && !!root.entry.pos && root.cardData.entries.length <= 1
                width: posLabel.implicitWidth + 16; height: 27; radius: 4; color: Theme.cardPanel
                Label { id: posLabel; anchors.centerIn: parent; text: root.entry ? root.partOfSpeech(root.entry.pos) : ""
                    color: Theme.cardText; font.pixelSize: Theme.cp(12); textFormat: Text.PlainText }
            }
            Repeater {
                model: root.entry ? root.entry.tags || [] : []
                delegate: Rectangle {
                    required property string modelData
                    width: tagLabel.implicitWidth + 16; height: 27; radius: 4; color: Theme.cardPanel
                    Label { id: tagLabel; anchors.centerIn: parent; text: modelData
                        textFormat: Text.PlainText; color: Theme.cardMuted; font.pixelSize: Theme.cp(12) }
                }
            }
            Label {
                objectName: "wordPronunciation"
                text: root.entry ? root.entry.ipa || "" : ""
                textFormat: Text.PlainText
                visible: text.length > 0
                height: 27; verticalAlignment: Text.AlignVCenter
                color: Theme.cardMuted; font.pixelSize: Theme.cp(13)
            }
        }
        StudyModes {
            Layout.fillWidth: true
            word: root.cardData; compact: true; previewOnly: root.previewOnly
            visible: !root.previewOnly && !!root.cardData.term
        }
        Label {
            Layout.fillWidth: true
            text: root.cardData.lemma && root.cardData.lemma !== root.cardData.term
                ? "Начальная форма: " + root.cardData.lemma : ""
            visible: text.length > 0
            textFormat: Text.PlainText
            font.pixelSize: Theme.cp(12); color: Theme.cardMuted; wrapMode: Text.Wrap
        }
        Label {
            Layout.fillWidth: true
            text: root.cardData.selection_preview || ""
            visible: text.indexOf(" … ") >= 0
            textFormat: Text.PlainText
            wrapMode: Text.Wrap; color: Theme.cardAccent; font.pixelSize: Theme.cp(13)
        }
        CardAction {
            objectName: "showTranslation"
            symbol: "eye"
            text: root.translationVisible ? "Hide translation" : "Show translation"
            enabled: !!root.cardData.term
            onClicked: root.translationVisible = !root.translationVisible
        }
        ColumnLayout {
            objectName: "dictionaryTranslations"
            Layout.fillWidth: true
            visible: root.translationVisible
            spacing: 7
            Repeater {
                model: root.entry ? root.entry.senses : []
                delegate: ColumnLayout {
                    id: senseItem
                    required property var modelData
                    required property int index
                    property bool expanded: root.examplesOpen || !!root.expandedSenses[index]
                    Layout.fillWidth: true
                    spacing: 3
                    Button {
                        objectName: "senseRow_" + senseItem.index
                        Layout.fillWidth: true
                        implicitHeight: contentItem.implicitHeight + 14
                        leftPadding: 7; rightPadding: 10; topPadding: 7; bottomPadding: 7
                        hoverEnabled: true
                        Accessible.name: senseItem.modelData.translation
                        background: Rectangle { radius: 6
                            color: senseItem.index === root.cardData.sense_index ? Theme.cardSoft
                                : parent.hovered ? Theme.cardPanel : "transparent" }
                        contentItem: RowLayout {
                            spacing: 10
                            Rectangle {
                                Layout.preferredWidth: 21; Layout.preferredHeight: 21
                                Layout.alignment: Qt.AlignTop
                                radius: 11; color: "transparent"
                                border.color: senseItem.index === root.cardData.sense_index ? Theme.cardAccent : Theme.cardBorder
                                Label { anchors.centerIn: parent; text: senseItem.index + 1; font.pixelSize: Theme.cp(11)
                                    color: senseItem.index === root.cardData.sense_index ? Theme.cardAccent : Theme.cardMuted }
                            }
                            Label {
                                Layout.fillWidth: true; Layout.preferredWidth: 1
                                text: senseItem.modelData.translation; textFormat: Text.PlainText
                                wrapMode: Text.Wrap; font.pixelSize: Theme.cp(15); color: Theme.cardText; lineHeight: backend.appearance.cardLineHeight
                            }
                        }
                        onClicked: if (!root.previewOnly) backend.selectSense(root.cardData.entry_index, senseItem.index)
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        visible: senseItem.modelData.examples && senseItem.modelData.examples.length > 0
                        Item { Layout.preferredWidth: 31 }
                        CardAction {
                            objectName: "senseExamplesToggle_" + senseItem.index
                            quiet: true
                            text: (senseItem.expanded ? "⌄  " : "›  ") + root.exampleCount(senseItem.modelData.examples.length)
                            implicitHeight: 28; leftPadding: 0; rightPadding: 8
                            font.pixelSize: Theme.cp(12)
                            onClicked: root.toggleSense(senseItem.index)
                        }
                        Item { Layout.fillWidth: true }
                    }
                    ColumnLayout {
                        objectName: "senseExamples_" + senseItem.index
                        Layout.fillWidth: true
                        Layout.leftMargin: 38
                        Layout.rightMargin: 10
                        Layout.topMargin: 3
                        Layout.bottomMargin: 6
                        visible: senseItem.expanded
                        spacing: 9
                        Repeater {
                            model: senseItem.modelData.examples || []
                            delegate: Label {
                                required property var modelData
                                Layout.fillWidth: true
                                text: modelData.en + (modelData.ru ? " — " + modelData.ru : "")
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Theme.cardMuted; font.pixelSize: Theme.cp(13); lineHeight: backend.appearance.cardLineHeight
                            }
                        }
                    }
                }
            }
            Label {
                Layout.fillWidth: true
                text: root.cardData.translation || "Перевода в словаре нет. Нажмите Explain."
                visible: !root.entry
                textFormat: Text.PlainText
                wrapMode: Text.Wrap; color: Theme.cardText; font.pixelSize: Theme.cp(15)
            }
        }
        Label {
            objectName: "dictionaryDefinition"
            Layout.fillWidth: true
            text: root.dictionaryDefinition
            visible: text.length > 0
            textFormat: Text.PlainText
            wrapMode: Text.Wrap; color: Theme.cardText; font.pixelSize: Theme.cp(15); lineHeight: backend.appearance.cardLineHeight
        }
        Label {
            objectName: "wordSynonyms"
            Layout.fillWidth: true
            text: root.wordSynonyms.length ? "Synonyms: " + root.wordSynonyms.join(", ") : ""
            visible: text.length > 0
            textFormat: Text.PlainText
            wrapMode: Text.Wrap; font.pixelSize: Theme.cp(13); color: Theme.cardMuted; font.italic: true
        }
        CardAction {
            quiet: true
            text: (root.etymologyOpen ? "⌄  " : "›  ") + "Этимология"
            visible: root.translationVisible && !!root.entry && !!root.entry.etymology
            implicitHeight: 28; leftPadding: 0; font.pixelSize: Theme.cp(12)
            onClicked: root.etymologyOpen = !root.etymologyOpen
        }
        Label {
            Layout.fillWidth: true
            text: root.entry ? root.entry.etymology : ""
            textFormat: Text.PlainText
            visible: root.etymologyOpen && root.translationVisible
            wrapMode: Text.Wrap; font.pixelSize: Theme.cp(13); color: Theme.cardMuted; lineHeight: backend.appearance.cardLineHeight
        }
        CardAction {
            quiet: true
            text: (root.notesOpen ? "⌄  " : "›  ") + "Словарные заметки"
            visible: root.translationVisible && !!root.entry && !!root.entry.extra
                && root.entry.extra !== root.entry.etymology
            implicitHeight: 28; leftPadding: 0; font.pixelSize: Theme.cp(12)
            onClicked: root.notesOpen = !root.notesOpen
        }
        Label {
            Layout.fillWidth: true
            text: root.entry ? root.entry.extra : ""
            textFormat: Text.PlainText
            visible: root.notesOpen && root.translationVisible
            wrapMode: Text.Wrap; font.pixelSize: Theme.cp(13); color: Theme.cardMuted
        }
        CardAction {
            objectName: "explainButton"
            symbol: "sparkle"; text: "Explain"; quiet: true; leftPadding: 2
            enabled: !!root.cardData.term && !backend.busy
            onClicked: if (!root.previewOnly) backend.requestLLM("explain")
        }
        Rectangle {
            Layout.fillWidth: true
            visible: !!root.cardData.explain
            implicitHeight: explanationResult.implicitHeight + 28
            radius: 8; color: Theme.cardPanel; border.color: Theme.cardBorder
            ColumnLayout {
                id: explanationResult
                x: 14; y: 14; width: parent.width - 28; spacing: 10
                Label { text: "Explanation"; font.pixelSize: Theme.cp(11); color: Theme.cardMuted }
                Label { Layout.fillWidth: true; text: root.cardData.definition_en || ""
                    textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: Theme.cp(15); color: Theme.cardText; lineHeight: backend.appearance.cardLineHeight }
                Label { Layout.fillWidth: true; text: root.cardData.usage_en || ""
                    textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: Theme.cp(13); color: Theme.cardMuted; lineHeight: backend.appearance.cardLineHeight }
                CardAction {
                    quiet: true
                    text: (root.llmExamplesOpen ? "⌄  " : "›  ") + "Examples · " + root.explanationExamples.length
                    visible: root.explanationExamples.length > 0
                    implicitHeight: 26; leftPadding: 0; font.pixelSize: Theme.cp(12)
                    onClicked: root.llmExamplesOpen = !root.llmExamplesOpen
                }
                ColumnLayout {
                    Layout.fillWidth: true; visible: root.llmExamplesOpen; spacing: 9
                    Repeater {
                        model: root.explanationExamples
                        delegate: Label {
                            required property var modelData
                            Layout.fillWidth: true
                            text: modelData.en + (modelData.ru && root.translationVisible ? " — " + modelData.ru : "")
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap; font.pixelSize: Theme.cp(13); color: Theme.cardMuted; lineHeight: backend.appearance.cardLineHeight
                        }
                    }
                }
            }
        }
        Rectangle { Layout.fillWidth: true; implicitHeight: 1; color: Theme.cardBorder; Layout.topMargin: 3; Layout.bottomMargin: 2 }
        RowLayout {
            objectName: "contextSection"
            Layout.fillWidth: true
            Label { text: "Context"; color: Theme.cardText; font.pixelSize: Theme.cp(15); font.weight: Font.DemiBold }
            Item { Layout.fillWidth: true }
            CardAction {
                objectName: "editContextButton"
                symbol: root.editOpen ? "check" : "edit"
                quiet: true
                tooltip: root.editOpen ? "Сохранить текст" : "Изменить слово и предложение"
                enabled: !backend.busy
                onClicked: {
                    if (root.editOpen && !root.previewOnly) backend.editContext(termEdit.text, sentenceEdit.text)
                    root.editOpen = !root.editOpen
                    if (root.editOpen) root.editingRequested()
                }
            }
        }
        Label {
            objectName: "contextSentence"
            Layout.fillWidth: true
            text: root.cardData.sentence_html || "Добавьте предложение, чтобы увидеть контекст."
            textFormat: Text.StyledText
            wrapMode: Text.Wrap
            color: root.cardData.sentence ? Theme.cardText : Theme.cardMuted
            font.pixelSize: Theme.cp(14); lineHeight: backend.appearance.cardLineHeight
            visible: !root.editOpen
        }
        TextField { id: termEdit; Layout.fillWidth: true; visible: root.editOpen; placeholderText: "Слово или фраза" }
        TextArea { id: sentenceEdit; Layout.fillWidth: true; visible: root.editOpen
            placeholderText: "Исходное предложение"; wrapMode: TextEdit.Wrap; selectByMouse: true }
        CardAction {
            objectName: "contextTranslatorButton"
            symbol: "sparkle"; text: "Context translator"; quiet: true; leftPadding: 2
            enabled: !!root.cardData.term && !!root.cardData.sentence && !backend.busy
            onClicked: if (!root.previewOnly) backend.requestLLM("context")
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: contextResult.implicitHeight + 28
            radius: 8; color: Theme.cardPanel; border.color: Theme.cardBorder
            visible: !!root.cardData.context
            ColumnLayout {
                id: contextResult
                x: 14; y: 14; width: parent.width - 28; spacing: 10
                Label { text: "Перевод и контекст"; font.pixelSize: Theme.cp(11); color: Theme.cardMuted }
                Label { Layout.fillWidth: true; text: root.cardData.sentence_translation || ""
                    textFormat: Text.PlainText; wrapMode: Text.Wrap; font.pixelSize: Theme.cp(15); color: Theme.cardText; lineHeight: backend.appearance.cardLineHeight }
                Label { Layout.fillWidth: true; text: root.cardData.context_explanation || ""
                    textFormat: Text.PlainText; wrapMode: Text.Wrap; color: Theme.cardMuted; font.pixelSize: Theme.cp(13); lineHeight: backend.appearance.cardLineHeight }
            }
        }
        Flow {
            Layout.fillWidth: true; spacing: 8; Layout.topMargin: 8
            Label { objectName: "llmModelLabel"; text: "Gemini · Flash Lite 3.5"
                visible: root.cardData.llm_model === "gemini-3.5-flash-lite"
                height: 24; verticalAlignment: Text.AlignVCenter
                color: Theme.cardMuted; font.pixelSize: Theme.cp(11) }
            Label { text: root.entry ? root.entry.dictionary : ""
                textFormat: Text.PlainText
                visible: text.length > 0; height: 24; verticalAlignment: Text.AlignVCenter
                color: Theme.cardMuted; font.pixelSize: Theme.cp(11) }
            Repeater {
                model: root.entry ? root.entry.sources : []
                delegate: CardAction {
                    required property string modelData
                    visible: /^https?:\/\//i.test(modelData)
                    text: modelData.indexOf("kaikki") >= 0 ? "Kaikki ↗" : "Wiktionary ↗"
                    quiet: true; implicitHeight: 24; leftPadding: 0; rightPadding: 4; font.pixelSize: Theme.cp(11)
                    onClicked: if (/^https?:\/\//i.test(modelData)) Qt.openUrlExternally(modelData)
                }
            }
        }
        Label {
            Layout.fillWidth: true
            text: root.cardData.error || ""
            visible: text.length > 0
            textFormat: Text.PlainText
            color: "#dfad91"; wrapMode: Text.Wrap; font.pixelSize: Theme.cp(12)
        }
        CardAction {
            text: "Повторить добавление"; symbol: "plus"
            visible: !!root.cardData.error
            enabled: !backend.busy
            onClicked: if (!root.previewOnly) backend.addWord()
        }
        Item { Layout.preferredHeight: 10 }
    }
}
