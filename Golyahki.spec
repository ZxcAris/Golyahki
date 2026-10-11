from pathlib import Path
import importlib.metadata
from PyInstaller.utils.hooks import collect_all, copy_metadata
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo
from golyah import __version__

root = Path(SPECPATH)
def version_info(name):
    version = tuple(int(part) for part in __version__.split('.')) + (0,)
    return VSVersionInfo(ffi=FixedFileInfo(filevers=version, prodvers=version, mask=0x3f,
        flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)), kids=[
        StringFileInfo([StringTable('040904B0', [StringStruct('FileDescription', 'Golyahki screen vocabulary'),
            StringStruct('FileVersion', __version__), StringStruct('ProductVersion', __version__),
            StringStruct('ProductName', 'Golyahki'), StringStruct('InternalName', name),
            StringStruct('OriginalFilename', name + '.exe')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])
datas, binaries, hiddenimports = [], [], []
for package in ('paddle', 'paddleocr', 'paddlex', 'keyring', 'dxcam', 'comtypes', 'winrt'):
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
datas += [(str(root / 'golyah' / 'qml'), 'golyah/qml'),
          (str(root / 'golyah' / 'data'), 'golyah/data'),
          (str(root / 'golyah' / 'schemas'), 'golyah/schemas')]
# PaddleX checks distribution metadata at runtime, including optional imports.
for distribution in importlib.metadata.distributions():
    name = distribution.metadata.get('Name')
    if name and name.lower() != 'golyah':
        datas += copy_metadata(name)
models = Path.home() / '.paddlex' / 'official_models'
for model in ('PP-OCRv5_mobile_det', 'en_PP-OCRv5_mobile_rec'):
    source = models / model
    if not (source / 'inference.pdiparams').exists():
        raise RuntimeError('Run scripts/check_ocr.py first to download ' + model)
    for file in source.iterdir():
        if file.is_file() and file.name in ('inference.pdiparams', 'inference.json', 'inference.pdmodel', 'inference.yml', 'config.json'):
            datas.append((str(file), 'models/' + model))

a = Analysis([str(root / 'launcher.py')], pathex=[str(root)],
    binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    hookspath=[str(root / 'hooks')],
    excludes=['pytest', 'IPython', 'tkinter', 'PySide6.QtWebEngineWidgets',
              'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick',
              'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets'],
    noarchive=False)
# Qt uses the ICU API supplied by Windows 11. An unrelated Poppler ICU from
# the build host's PATH has incompatible exports and must not shadow it.
a.binaries = [item for item in a.binaries
              if Path(item[0]).name.lower() not in ('icuuc.dll', 'icudt78.dll')
              and not Path(item[0]).name.lower().startswith('opencv_videoio_ffmpeg')]
# Inference does not compile extensions or use development/debug resources.
a.datas = [item for item in a.datas
           if Path(item[0]).name.lower() not in ('direct_url.json', 'record', 'installer', 'requested')
           and not (item[0].replace('\\', '/').startswith('paddle/') and Path(item[0]).suffix.lower()
                   in ('.h', '.hpp', '.cuh', '.lib'))]
pyz = PYZ(a.pure)
gui = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Golyahki',
          debug=False, strip=False, upx=False, console=False, icon=str(root / 'assets' / 'golyahki.ico'),
          version=version_info('Golyahki'))
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='Golyahki-OCR',
             debug=False, strip=False, upx=False, console=True, icon=str(root / 'assets' / 'golyahki.ico'),
             version=version_info('Golyahki-OCR'))
coll = COLLECT(gui, worker, a.binaries, a.datas, strip=False, upx=False, name='Golyahki')
