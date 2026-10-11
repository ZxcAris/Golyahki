import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property var word: backend.card
    property bool compact: false
    property bool expanded: !compact
    property bool previewOnly: false
    property bool allowCreate: false
    spacing: 8
    function toggle(mode, checked) {
        let modes = (word.learning_modes || ["forward"]).slice()
        if (checked && modes.indexOf(mode) < 0) modes.push(mode)
        if (!checked) modes = modes.filter(m => m !== mode)
        backend.setRecordStudyModes(word.uid, JSON.stringify(modes))
    }
    SoftButton {
        objectName: "studyModesToggle"
        visible: root.compact
        text: "Варианты Anki · " + (root.word.learning_modes || ["forward"]).length + (root.expanded ? "  ⌃" : "  ⌄")
        quiet: true; font.pixelSize: Theme.px(12)
        onClicked: root.expanded = !root.expanded
    }
    ColumnLayout {
        visible: root.expanded; Layout.fillWidth: true; spacing: 3
        Label { visible: !root.compact; text: "ОБУЧЕНИЕ ЭТОГО СЛОВА"; font.pixelSize: Theme.px(11); color: Theme.faint; font.letterSpacing: 1 }
        Repeater {
            model: [{key:"forward",label:"Слово → перевод"},{key:"reverse",label:"Перевод → слово"},{key:"gap",label:"Предложение с пропуском"}]
            delegate: CheckBox {
                id: modeCheck
                required property var modelData
                objectName: "studyMode_" + modelData.key
                text: modelData.label; checked: (root.word.learning_modes || ["forward"]).indexOf(modelData.key) >= 0
                enabled: !root.previewOnly && !backend.busy && !!root.word.term && (modelData.key !== "gap" || !!root.word.gap_available)
                font.pixelSize: Theme.px(13)
                onClicked: { root.toggle(modelData.key, checked); checked = Qt.binding(() => (root.word.learning_modes || ["forward"]).indexOf(modelData.key) >= 0) }
            }
        }
        Label { visible: !root.word.gap_available; text: "Для пропуска нужен контекст с выбранным словом."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(11) }
        SoftButton {
            objectName: "syncStudyModes"
            visible: !root.previewOnly && (!!root.word.has_anki || !!root.word.saved_to_anki || root.allowCreate || !root.compact)
            Layout.fillWidth: true
            text: root.word.anki_modes_pending ? "Обновить варианты в Anki" : root.word.has_anki || root.word.saved_to_anki ? "Проверить варианты в Anki" : "Создать варианты в Anki"
            accent: !!root.word.anki_modes_pending; quiet: !root.word.anki_modes_pending
            enabled: !backend.busy && !!root.word.complete && (!!root.word.stored || !!root.word.saved)
            onClicked: backend.syncStudyModes(root.word.uid)
        }
        Label { visible: !!root.word.anki_modes_pending; text: "Выбор сохранён локально; Anki ожидает обновления."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.accent; font.pixelSize: Theme.px(11) }
    }
}
