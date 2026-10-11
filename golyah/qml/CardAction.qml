import QtQuick
import "."
import QtQuick.Controls
import QtQuick.Layouts

Button {
    id: control
    property string symbol: ""
    property bool quiet: false
    property bool accent: false
    property string tooltip: ""
    implicitHeight: Math.max(34, font.pixelSize + 15)
    implicitWidth: Math.max(34, implicitContentWidth + leftPadding + rightPadding)
    leftPadding: text.length ? 11 : 8
    rightPadding: text.length ? 11 : 8
    topPadding: 7
    bottomPadding: 7
    font.family: Theme.cardFont
    font.pixelSize: Theme.cp(13)
    hoverEnabled: true
    Accessible.name: text || tooltip
    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip
    ToolTip.delay: 450
    contentItem: RowLayout {
        spacing: 7
        CardIcon {
            visible: control.symbol.length > 0
            kind: control.symbol
            ink: control.accent ? Theme.cardAccent : control.enabled ? Theme.cardText : Theme.cardMuted
            Layout.preferredWidth: 16
            Layout.preferredHeight: 16
        }
        Label {
            visible: control.text.length > 0
            text: control.text
            textFormat: Text.PlainText
            font: control.font
            color: control.enabled ? Theme.cardText : Theme.cardMuted
        }
    }
    background: Rectangle {
        radius: 8
        color: control.down ? Theme.cardSoft : control.hovered ? Theme.cardPanel
            : control.quiet ? "transparent" : Theme.cardPanel
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.cardAccent
        opacity: control.enabled ? 1 : 0.55
    }
}
