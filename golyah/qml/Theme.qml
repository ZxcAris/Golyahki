pragma Singleton
import QtQuick

QtObject {
    readonly property var preferences: backend.appearance
    readonly property color background: "#11141b"
    readonly property color sidebar: "#151922"
    readonly property color surface: "#1c212c"
    readonly property color raised: "#262d3b"
    readonly property color border: "#303849"
    readonly property color text: "#edf0f7"
    readonly property color muted: "#9ca7ba"
    readonly property color faint: "#748096"
    readonly property color accent: preferences.accent
    readonly property color accentSoft: Qt.tint(surface, Qt.rgba(accent.r, accent.g, accent.b, 0.13))
    readonly property color accentInk: accent.r * 0.299 + accent.g * 0.587 + accent.b * 0.114 > 0.6 ? "#131722" : "#ffffff"
    readonly property string uiFont: preferences.uiFont
    readonly property real scale: preferences.uiFontSize / 15
    readonly property string cardFont: preferences.cardFont
    readonly property color cardBackground: preferences.cardBackground
    readonly property color cardBackgroundEnd: preferences.cardBackgroundEnd
    readonly property color cardText: preferences.cardText
    readonly property color cardMuted: preferences.cardMuted
    readonly property color cardAccent: preferences.cardAccent
    readonly property color cardBorder: preferences.cardBorder
    readonly property color cardSoft: Qt.tint(cardBackground, Qt.rgba(cardAccent.r, cardAccent.g, cardAccent.b, 0.12))
    readonly property color cardPanel: Qt.tint(cardBackground, Qt.rgba(cardText.r, cardText.g, cardText.b, 0.035))
    readonly property real cardScale: preferences.cardFontSize / 15
    function px(size) { return Math.round(size * scale) }
    function cp(size) { return Math.round(size * cardScale) }
}
