"""Use the system Edge WebView2 runtime; never collect Qt WebEngine."""
from pathlib import Path
from PyInstaller.utils.hooks import get_package_paths
from PyInstaller.utils.hooks.qt import pyside6_library_info

# Windows wheels place DLLs at the package root; QLibraryInfo's bin path
# identifies Qt tools and may not contain the runtime libraries.
root = Path(get_package_paths('PySide6')[1])
destination = pyside6_library_info.qt_rel_dir
hiddenimports = ['PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtQuick']
binaries = [(str(root / name), destination)
            for name in ('Qt6WebView.dll', 'Qt6WebViewQuick.dll')]
plugin = Path(pyside6_library_info.location['PluginsPath']) / 'webview/qtwebview_webview2.dll'
binaries.append((str(plugin), str(Path(destination) / 'plugins/webview')))
datas = []
