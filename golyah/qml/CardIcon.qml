import QtQuick

Canvas {
    property string kind: "sparkle"
    property color ink: "#c8ced4"
    implicitWidth: 18
    implicitHeight: 18
    onKindChanged: requestPaint()
    onInkChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onPaint: {
        const c = getContext("2d")
        c.reset()
        c.clearRect(0, 0, width, height)
        c.scale(width / 20, height / 20)
        c.strokeStyle = ink
        c.fillStyle = ink
        c.lineWidth = 1.5
        c.lineCap = "round"
        c.lineJoin = "round"
        c.beginPath()
        if (kind === "search") {
            c.arc(8, 8, 5, 0, Math.PI * 2)
            c.moveTo(12, 12); c.lineTo(17, 17)
        } else if (kind === "book") {
            c.moveTo(10, 5); c.lineTo(10, 17)
            c.moveTo(10, 5); c.quadraticCurveTo(5, 2, 2, 5); c.lineTo(2, 16); c.quadraticCurveTo(6, 13, 10, 17)
            c.quadraticCurveTo(14, 13, 18, 16); c.lineTo(18, 5); c.quadraticCurveTo(14, 2, 10, 5)
        } else if (kind === "layers") {
            c.moveTo(2, 6); c.lineTo(10, 2); c.lineTo(18, 6); c.lineTo(10, 10); c.closePath()
            c.moveTo(2, 10); c.lineTo(10, 14); c.lineTo(18, 10)
            c.moveTo(2, 14); c.lineTo(10, 18); c.lineTo(18, 14)
        } else if (kind === "palette") {
            c.arc(10, 10, 8, 0, Math.PI * 2); c.stroke(); c.beginPath()
            for (const point of [[6,6],[11,5],[15,9]]) { c.moveTo(point[0]+1,point[1]); c.arc(point[0],point[1],1,0,Math.PI*2) }
            c.moveTo(11,14); c.arc(10,14,1,0,Math.PI*2)
        } else if (kind === "settings") {
            for (const y of [5,10,15]) { c.moveTo(2,y); c.lineTo(18,y) }
            c.stroke(); c.beginPath()
            for (const point of [[7,5],[13,10],[8,15]]) { c.moveTo(point[0]+2,point[1]); c.arc(point[0],point[1],2,0,Math.PI*2) }
        } else if (kind === "eye") {
            c.moveTo(2, 10)
            c.bezierCurveTo(6, 3, 14, 3, 18, 10)
            c.bezierCurveTo(14, 17, 6, 17, 2, 10)
            c.closePath()
            c.stroke()
            c.beginPath(); c.arc(10, 10, 2.4, 0, Math.PI * 2)
        } else if (kind === "speaker") {
            c.moveTo(3,7); c.lineTo(7,7); c.lineTo(11,3); c.lineTo(11,17); c.lineTo(7,13); c.lineTo(3,13); c.closePath()
            c.moveTo(14,6); c.quadraticCurveTo(18,10,14,14)
        } else if (kind === "stop") {
            c.rect(5,5,10,10)
        } else if (kind === "plus") {
            c.moveTo(10, 4); c.lineTo(10, 16)
            c.moveTo(4, 10); c.lineTo(16, 10)
        } else if (kind === "check") {
            c.moveTo(4, 10); c.lineTo(8, 14); c.lineTo(16, 6)
        } else if (kind === "chevron") {
            c.moveTo(7, 4); c.lineTo(13, 10); c.lineTo(7, 16)
        } else if (kind === "edit") {
            c.moveTo(4, 13); c.lineTo(13, 4); c.lineTo(16, 7)
            c.lineTo(7, 16); c.lineTo(3, 17); c.closePath()
            c.moveTo(11, 6); c.lineTo(14, 9)
        } else {
            c.moveTo(8, 2); c.lineTo(10, 7); c.lineTo(15, 9)
            c.lineTo(10, 11); c.lineTo(8, 16); c.lineTo(6, 11)
            c.lineTo(1, 9); c.lineTo(6, 7); c.closePath()
            c.moveTo(16, 2); c.lineTo(16, 6)
            c.moveTo(14, 4); c.lineTo(18, 4)
        }
        c.stroke()
    }
}
