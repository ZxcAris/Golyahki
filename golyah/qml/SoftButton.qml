import QtQuick
import "."
import QtQuick.Controls

Button {
    id: control
    property bool accent: false
    property bool quiet: false
    implicitHeight: Math.max(40, font.pixelSize + 22)
    font.family: Theme.uiFont
    font.pixelSize: Theme.px(14)
    leftPadding: 14
    rightPadding: 14
    contentItem: Text {
        text: control.text
        font: control.font
        color: !control.enabled ? Theme.faint : control.accent ? Theme.accentInk : Theme.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
    background: Rectangle {
        radius: 10
        color: control.accent ? (control.down ? Theme.accent : Theme.accent)
            : control.quiet ? (control.hovered ? Theme.raised : "transparent")
            : control.hovered ? Theme.raised : Theme.surface
        border.width: control.quiet || control.accent ? 0 : 1
        border.color: Theme.border
        opacity: control.enabled ? 1 : 0.5
    }
}
