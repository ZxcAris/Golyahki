"""The same drawn mark is used in the window, tray, and Windows executable."""
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap


DEFAULT_ACCENT = '#929ac2'
BACKGROUND = '#151922'
SILHOUETTE_COMMANDS = (
    ('M', 98, 52),
    ('C', 116, 50, 136, 67, 140, 88),
    ('C', 140, 111, 124, 135, 111, 160),
    ('L', 93, 200),
    ('C', 86, 214, 72, 218, 63, 203),
    ('C', 42, 170, 46, 145, 56, 117),
    ('L', 74, 72),
    ('C', 79, 61, 87, 55, 98, 52),
    ('Z',),
    ('M', 163, 71),
    ('C', 181, 66, 195, 74, 200, 89),
    ('C', 210, 119, 197, 143, 180, 170),
    ('L', 157, 203),
    ('C', 150, 213, 133, 208, 135, 195),
    ('C', 139, 174, 155, 154, 156, 128),
    ('C', 157, 113, 151, 99, 150, 87),
    ('C', 149, 78, 155, 74, 163, 71),
    ('Z',),
)
MARK_PATH = ' '.join(command[0] + ' '.join(map(str, command[1:])) for command in SILHOUETTE_COMMANDS)


def mark_svg(color=DEFAULT_ACCENT, tile=False):
    backdrop = f'<rect width="256" height="256" rx="57" fill="{BACKGROUND}"/>' if tile else ''
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
            f'{backdrop}<path d="{MARK_PATH}" fill="{color}"/></svg>')


def silhouette_path():
    path = QPainterPath()
    operations = {'M': path.moveTo, 'C': path.cubicTo, 'L': path.lineTo, 'Z': path.closeSubpath}
    for operation, *coordinates in SILHOUETTE_COMMANDS:
        operations[operation](*coordinates)
    return path


def icon_pixmap(accent=DEFAULT_ACCENT, size=256):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.scale(size / 256, size / 256)
    painter.setBrush(QColor(BACKGROUND))
    painter.drawRoundedRect(QRectF(0, 0, 256, 256), 57, 57)
    painter.setBrush(QColor(accent))
    painter.drawPath(silhouette_path())
    painter.end()
    return pixmap


def app_icon(accent=DEFAULT_ACCENT):
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(icon_pixmap(accent, size))
    return icon
