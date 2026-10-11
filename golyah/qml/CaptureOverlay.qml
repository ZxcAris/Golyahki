import QtQuick
import QtQuick.Window

Window {
    id: overlayWindow
    objectName: "captureOverlay"
    property var popup
    property var overlayData: backend.overlay
    property int hoveredWord: -1
    property int hoveredSentence: -1
    visible: overlayData.visible
    x: overlayData.left; y: overlayData.top
    width: overlayData.width; height: overlayData.height
    flags: Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | (overlayData.passive ? Qt.WindowDoesNotAcceptFocus : 0)
    transientParent: null
    // A nonzero alpha keeps clear text areas clickable in native layered windows.
    color: "#01000000"
    Component.onCompleted: backend.attachOverlay(overlayWindow)
    onVisibleChanged: {
        hoveredWord = -1; hoveredSentence = -1
        if (visible) { raise(); activateOverlay() }
    }
    function activateOverlay() {
        if (!overlayData.passive) { requestActivate(); overlayFocus.forceActiveFocus() }
    }
    onActiveChanged: if (active) overlayFocus.forceActiveFocus()
    function wordAt(x, y) {
        const px = x * overlayData.pixelWidth / width, py = y * overlayData.pixelHeight / height
        let best = null, distance = Infinity
        for (const word of overlayData.words) {
            const b = word.displayBounds
            if (px < b.left || px >= b.left + b.width || py < b.top || py >= b.top + b.height) continue
            const score = Math.pow((px - b.left - b.width / 2) / b.width, 2) + Math.pow((py - b.top - b.height / 2) / b.height, 2)
            if (score < distance) { best = word; distance = score }
        }
        return best
    }
    function updateHover(x, y) {
        const word = wordAt(x, y)
        hoveredWord = word ? word.id : -1
        hoveredSentence = word ? word.sentenceId : -1
    }
    Connections {
        target: backend
        function onAppearanceChanged() { textDimming.requestPaint() }
        function onOverlayChanged() {
            hoveredWord = -1; hoveredSentence = -1
            textDimming.requestPaint()
        }
    }

    Canvas {
        id: textDimming
        objectName: "textDimming"
        anchors.fill: parent
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.clearRect(0, 0, width, height)
            ctx.fillStyle = Qt.rgba(0, 0, 0, backend.appearance.overlayDim / 100)
            ctx.fillRect(0, 0, width, height)
            // Remove dimming from complete lines, including spaces between words.
            // Wrapped sentences retain their contour instead of exposing empty areas.
            ctx.globalCompositeOperation = "destination-out"
            ctx.fillStyle = "black"
            const sx = width / overlayWindow.overlayData.pixelWidth
            const sy = height / overlayWindow.overlayData.pixelHeight
            for (const line of overlayWindow.overlayData.sentenceLines) {
                const x = line.left * sx, y = line.top * sy
                const w = line.width * sx, h = line.height * sy
                const r = Math.min(7, w / 2, h / 2)
                ctx.beginPath()
                ctx.moveTo(x + r, y)
                ctx.lineTo(x + w - r, y)
                ctx.quadraticCurveTo(x + w, y, x + w, y + r)
                ctx.lineTo(x + w, y + h - r)
                ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h)
                ctx.lineTo(x + r, y + h)
                ctx.quadraticCurveTo(x, y + h, x, y + h - r)
                ctx.lineTo(x, y + r)
                ctx.quadraticCurveTo(x, y, x + r, y)
                ctx.closePath()
                ctx.fill()
            }
            ctx.globalCompositeOperation = "source-over"
        }
    }

    Item {
        id: overlayFocus
        anchors.fill: parent; focus: true
        Keys.onEscapePressed: backend.closeOverlay()
        Repeater {
            model: overlayWindow.overlayData.words
            delegate: Rectangle {
                id: wordRect
                required property var modelData
                objectName: "captureWord_" + modelData.id
                property bool selected: overlayWindow.overlayData.selected.indexOf(modelData.id) >= 0 &&
                    (overlayWindow.overlayData.multiSelect || (overlayWindow.popup && overlayWindow.popup.visible))
                property bool hovered: overlayWindow.hoveredWord === modelData.id
                property var box: modelData.highlightBounds || modelData.displayBounds
                x: box.left * overlayWindow.width / overlayWindow.overlayData.pixelWidth
                y: box.top * overlayWindow.height / overlayWindow.overlayData.pixelHeight
                width: box.width * overlayWindow.width / overlayWindow.overlayData.pixelWidth
                height: box.height * overlayWindow.height / overlayWindow.overlayData.pixelHeight
                color: selected ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.56)
                    : hovered ? Qt.rgba(Theme.accent.r, Theme.accent.g, Theme.accent.b, 0.46) : "transparent"
                radius: 2
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: overlayWindow.hoveredWord >= 0 ? Qt.PointingHandCursor : Qt.ArrowCursor
            onPositionChanged: mouse => overlayWindow.updateHover(mouse.x, mouse.y)
            onExited: { overlayWindow.hoveredWord = -1; overlayWindow.hoveredSentence = -1 }
            onClicked: mouse => {
                if (overlayWindow.overlayData.stage !== "ready") return
                const word = overlayWindow.wordAt(mouse.x, mouse.y)
                if (word) {
                    overlayWindow.activateOverlay()
                    // Ctrl+LMB and Ctrl+Alt+LMB both toggle the same selection.
                    const multiple = (mouse.modifiers & Qt.ControlModifier) !== 0
                    if ((mouse.modifiers & Qt.ShiftModifier) !== 0)
                        backend.chooseRange(word.id, multiple)
                    else
                        backend.chooseWord(word.id, multiple)
                    overlayWindow.updateHover(mouse.x, mouse.y)
                } else {
                    backend.closeOverlay()
                }
            }
        }
    }
}
