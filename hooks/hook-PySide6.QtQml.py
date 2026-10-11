"""Bundle only the QML modules used by Golyahki's Basic controls."""
from pathlib import Path

from PyInstaller.utils.hooks.qt import add_qt6_dependencies, pyside6_library_info

hiddenimports, binaries, datas = add_qt6_dependencies(__file__)
source = Path(pyside6_library_info.location['QmlImportsPath']).resolve()
destination = Path(pyside6_library_info.qt_rel_dir) / 'qml'
modules = (
    'QML', 'QtQml', 'QtQml/Models', 'QtQml/WorkerScript',
    'QtQuick', 'QtQuick/Window', 'QtQuick/Layouts', 'QtQuick/Templates', 'QtQuick/Shapes',
    'QtQuick/Controls', 'QtQuick/Controls/impl', 'QtQuick/Controls/Basic',
    'QtQuick/Controls/Basic/impl', 'QtQuick/Dialogs',
    'QtQuick/Dialogs/quickimpl', 'Qt/labs/folderlistmodel', 'QtWebView',
)
for module in modules:
    folder = source / module
    qmldir = folder / 'qmldir'
    if not qmldir.exists():
        continue
    libs, files = pyside6_library_info._process_qml_plugin(qmldir)
    for file in libs:
        binaries.append((str(file), str(destination / file.parent.relative_to(source))))
    for file in files:
        if module == 'QtWebView' and file.name == 'qmldir':
            # Qt ships an optional WebEngine backend. Its qmldir metadata lists
            # that dependency even when the native Windows backend is selected.
            generated = Path(__file__).parent / 'generated/QtWebView/qmldir'
            generated.parent.mkdir(parents=True, exist_ok=True)
            generated.write_text(qmldir.read_text(encoding='utf-8').replace(
                'depends QtWebEngine auto\n', ''), encoding='utf-8')
            datas.append((str(generated), str(destination / module)))
        else:
            datas.append((str(file), str(destination / file.parent.relative_to(source))))
