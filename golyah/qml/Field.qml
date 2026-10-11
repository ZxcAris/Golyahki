import QtQuick
import QtQuick.Controls as Controls

Controls.TextField {
    id: root
    implicitHeight: Math.max(44, font.pixelSize + 24)
    leftPadding: 13; rightPadding: 13; topPadding: 10; bottomPadding: 10
    color: Theme.text; placeholderTextColor: Theme.faint
    selectionColor: Theme.accent; selectedTextColor: Theme.accentInk
    background: Rectangle {
        color: Theme.surface; radius: 10
        border.color: root.activeFocus ? Theme.accent : Theme.border
    }
}
