import QtQuick
import QtQuick.Controls as Controls

Controls.ComboBox {
    id: root
    property bool popupInWindow: false
    implicitHeight: Math.max(44, font.pixelSize + 24)
    leftPadding: 13; rightPadding: 34
    background: Rectangle {
        color: Theme.surface; radius: 10
        border.color: root.activeFocus ? Theme.accent : Theme.border
    }
    indicator: Text {
        x: root.width - width - 12; y: (root.height - height) / 2
        text: "⌄"; color: Theme.muted; font.pixelSize: 21
    }
    delegate: Controls.ItemDelegate {
        required property int index
        required property var modelData
        width: root.width - 12
        text: root.textRole ? root.model[index][root.textRole] : modelData
        font: root.font
        highlighted: root.highlightedIndex === index
        palette.text: Theme.text
        background: Rectangle {
            radius: 7; color: parent.highlighted ? Theme.accentSoft : parent.hovered ? Theme.surface : "transparent"
        }
    }
    popup: Controls.Popup {
        popupType: root.popupInWindow ? Controls.Popup.Window : Controls.Popup.Item
        objectName: root.objectName + "Popup"
        y: root.height + 5; width: root.width
        implicitHeight: Math.min(contentItem.implicitHeight + 12, 360)
        padding: 6
        background: Rectangle { color: Theme.raised; radius: 12; border.color: Theme.border }
        contentItem: ListView {
            clip: true; implicitHeight: contentHeight
            model: root.popup.visible ? root.delegateModel : null
            currentIndex: root.highlightedIndex
            Controls.ScrollIndicator.vertical: Controls.ScrollIndicator {}
        }
    }
}
