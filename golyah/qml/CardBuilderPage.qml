import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtWebView

Item {
    id: root
    objectName: "cardBuilderPage"
    property string mode: "forward"
    property string side: "front"
    property bool enabledOnly: false
    readonly property var blocks: backend.cardBuilder.layouts[mode][side]
    function updatePreview() { backend.setAnkiPreview(mode, side) }
    onModeChanged: updatePreview()
    onSideChanged: updatePreview()
    Component.onCompleted: updatePreview()
    RowLayout {
        anchors.fill: parent; spacing: 24
        ColumnLayout {
            Layout.preferredWidth: 370; Layout.maximumWidth: 410; Layout.fillHeight: true; spacing: 12
            Label { text: "Ваша карточка Anki"; font.pixelSize: Theme.px(23); font.weight: Font.DemiBold; color: Theme.text; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Label { text: "Выберите поля для вопроса и ответа. Меняйте порядок стрелками; пустые поля скрываются."; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(12) }
            Choice {
                objectName: "builderModeChoice"; Layout.fillWidth: true
                model: ["Слово → перевод", "Перевод → слово", "Предложение с пропуском"]
                currentIndex: ["forward","reverse","gap"].indexOf(root.mode)
                onActivated: root.mode = ["forward","reverse","gap"][currentIndex]
            }
            RowLayout {
                Layout.fillWidth: true
                SoftButton { objectName: "builderFront"; text: "Вопрос"; accent: root.side === "front"; quiet: root.side !== "front"; Layout.fillWidth: true; onClicked: root.side = "front" }
                SoftButton { objectName: "builderBack"; text: "Ответ"; accent: root.side === "back"; quiet: root.side !== "back"; Layout.fillWidth: true; onClicked: root.side = "back" }
            }
            CheckBox { objectName:"builderEnabledOnly"; text:"Показать только включённые"; checked:root.enabledOnly; onToggled:root.enabledOnly=checked; font.pixelSize:Theme.px(12) }
            ListView {
                objectName: "builderBlocks"
                Layout.fillWidth: true; Layout.fillHeight: true; clip: true; spacing: 6
                model: root.blocks
                ScrollBar.vertical: ScrollBar {}
                delegate: Rectangle {
                    required property var modelData
                    required property int index
                    width: ListView.view.width
                    height: root.enabledOnly && !modelData.visible ? 0 : Math.max(48, blockRow.implicitHeight + 8)
                    visible: height > 0
                    color: modelData.visible ? Theme.surface : "transparent"; radius: 9
                    border.color: Theme.border
                    RowLayout {
                        id: blockRow; anchors.fill: parent; anchors.leftMargin: 3; anchors.rightMargin: 5; spacing: 3
                        CheckBox {
                            objectName: "builderBlock_" + modelData.key
                            text: modelData.label; checked: modelData.visible
                            enabled: !modelData.required
                            Layout.fillWidth: true; font.pixelSize: Theme.px(12)
                            onClicked: backend.setBuilderBlock(root.mode, root.side, modelData.key, checked)
                            ToolTip.visible: hovered && modelData.required; ToolTip.text: "Основной вопрос и ответ обязательны"
                        }
                        SoftButton { objectName:"builderUp_"+modelData.key; text:"↑"; implicitWidth:32; implicitHeight:32; quiet:true; enabled:index>0; Accessible.name:"Поднять "+modelData.label; onClicked:backend.moveBuilderBlock(root.mode,root.side,modelData.key,-1) }
                        SoftButton { objectName:"builderDown_"+modelData.key; text:"↓"; implicitWidth:32; implicitHeight:32; quiet:true; enabled:index<root.blocks.length-1; Accessible.name:"Опустить "+modelData.label; onClicked:backend.moveBuilderBlock(root.mode,root.side,modelData.key,1) }
                    }
                }
            }
            SoftButton { objectName: "applyCardBuilder"; Layout.fillWidth: true; text: "Применить конструктор к Anki"; accent: true; enabled: !backend.busy; onClicked: backend.applyAnkiAppearance() }
            SoftButton { objectName: "resetCardBuilder"; text: "Стандартный порядок блоков"; quiet: true; Layout.fillWidth: true; onClicked: backend.resetCardBuilder() }
        }
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true; spacing: 10
            Label { text: "ПРЕДПРОСМОТР НА ВАШЕМ СЛОВЕ"; color: Theme.faint; font.pixelSize: Theme.px(11); font.letterSpacing: 1; Layout.fillWidth: true; wrapMode: Text.Wrap }
            Choice {
                objectName: "builderWordChoice"; Layout.fillWidth: true
                popupInWindow: true
                model: backend.builderWords; textRole: "label"; valueRole: "uid"
                currentIndex: model.findIndex(r => r.uid === backend.builderWord.uid)
                displayText: currentIndex >= 0 ? currentText : "Сначала найдите или сохраните слово"
                onActivated: backend.selectBuilderWord(currentValue)
            }
            Rectangle {
                Layout.fillWidth: true; Layout.fillHeight: true; radius: 12; color: Theme.background; border.color:Theme.border; clip:true
                WebView {
                    id: webPreview
                    objectName: "ankiWebPreview"
                    anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 1
                    // A native child needs initialization while visible. Keep its
                    // bounds empty until HTML loads to avoid its white host window.
                    height: loadProgress === 100 ? parent.height - 2 : 0
                    settings.javaScriptEnabled: false
                    settings.localStorageEnabled: false
                    settings.localContentCanAccessFileUrls: false
                    settings.allowFileAccess: false
                    function refresh() { loadHtml(backend.ankiPreviewHtml, "about:blank") }
                    Component.onCompleted: refresh()
                    Connections { target:backend; function onAnkiPreviewChanged() { webPreview.refresh() } }
                }
            }
            Rectangle {
                Layout.fillWidth: true; implicitHeight: modesPanel.implicitHeight + 24
                Layout.maximumHeight: root.height * 0.45
                color:Theme.surface; radius:12; border.color:Theme.border
                Flickable {
                    anchors.fill:parent; anchors.margins:12; clip:true
                    contentWidth:width; contentHeight:modesPanel.implicitHeight
                    boundsBehavior:Flickable.StopAtBounds
                    ScrollBar.vertical:ScrollBar {}
                    StudyModes { id:modesPanel; objectName:"builderStudyModes"; width:parent.width; word:backend.builderWord; compact:true; expanded:root.height>600; allowCreate:true }
                }
            }
            Label { text: "Макет сохраняется сразу. Кнопка применения обновляет шаблоны в открытой Anki. Выбор обучения сохраняется отдельно для каждого слова."; color:Theme.muted; font.pixelSize:Theme.px(11); Layout.fillWidth:true; wrapMode:Text.Wrap }
        }
    }
}
