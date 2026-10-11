import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs

RowLayout {
    id: root
    property string label
    property string settingKey
    property string colorValue
    spacing: 10
    Label { text: root.label; Layout.fillWidth: true; wrapMode: Text.Wrap; color: Theme.muted; font.pixelSize: Theme.px(13) }
    Button {
        objectName: root.settingKey + "ColorPicker"
        implicitWidth: 34; implicitHeight: 34; hoverEnabled: true
        Accessible.name: "Выбрать цвет: " + root.label
        background: Rectangle { color: root.colorValue; radius: 8; border.color: Theme.border; border.width: 1 }
        onClicked: { picker.selectedColor = root.colorValue; picker.open() }
    }
    Field {
        objectName: root.settingKey + "ColorHex"
        Layout.preferredWidth: 105
        text: root.colorValue.toUpperCase(); maximumLength: 7; selectByMouse: true
        font.family: "Consolas"; font.pixelSize: Theme.px(12)
        onEditingFinished: {
            backend.setAppearance(JSON.stringify({[root.settingKey]: text.trim()}))
            text = Qt.binding(() => root.colorValue.toUpperCase())
        }
    }
    ColorDialog {
        id: picker
        objectName: root.settingKey + "ColorDialog"
        title: root.label
        options: ColorDialog.DontUseNativeDialog
        onAccepted: backend.setAppearance(JSON.stringify({[root.settingKey]: selectedColor.toString()}))
    }
}
