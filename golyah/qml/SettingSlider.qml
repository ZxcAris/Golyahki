import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

ColumnLayout {
    id: root
    property string label
    property string settingKey
    property real fromValue
    property real toValue
    property real settingValue
    property real increment: 1
    property string suffix: ""
    RowLayout {
        Layout.fillWidth: true
        Label { text: root.label; Layout.fillWidth: true; color: Theme.muted; font.pixelSize: Theme.px(13); wrapMode: Text.Wrap }
        Label { text: (root.increment < 1 ? root.settingValue.toFixed(2) : Math.round(root.settingValue)) + root.suffix; color: Theme.accent; font.pixelSize: Theme.px(13) }
    }
    Slider {
        id: slider
        objectName: root.settingKey + "Slider"
        Layout.fillWidth: true
        from: root.fromValue; to: root.toValue; stepSize: root.increment; value: root.settingValue
        onMoved: backend.setAppearance(JSON.stringify({[root.settingKey]: root.increment < 1 ? Number(value.toFixed(2)) : Math.round(value)}))
        background: Rectangle {
            x: slider.leftPadding; y: slider.topPadding + slider.availableHeight / 2 - height / 2
            width: slider.availableWidth; height: 5; radius: 3; color: Theme.border
            Rectangle { width: slider.visualPosition * parent.width; height: parent.height; radius: 3; color: Theme.accent }
        }
        handle: Rectangle {
            x: slider.leftPadding + slider.visualPosition * (slider.availableWidth - width)
            y: slider.topPadding + slider.availableHeight / 2 - height / 2
            implicitWidth: 22; implicitHeight: 22; radius: 11
            color: slider.pressed ? Theme.accent : Theme.surface
            border.color: Theme.accent; border.width: 2
        }
    }
}
