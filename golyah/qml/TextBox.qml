import QtQuick
import QtQuick.Controls as Controls

Controls.TextArea {
    id: root
    leftPadding: 13; rightPadding: 13; topPadding: 12; bottomPadding: 12
    color: Theme.text; placeholderTextColor: Theme.faint
    selectionColor: Theme.accent; selectedTextColor: Theme.accentInk
    background: Rectangle {
        color: Theme.surface; radius: 10
        border.color: root.activeFocus ? Theme.accent : Theme.border
    }
}
