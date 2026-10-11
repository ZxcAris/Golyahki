"""Check the packaged GUI and OCR without a Python executable on PATH."""
import json
import os
import subprocess
import tempfile
import sys
from pathlib import Path
from multiprocessing.shared_memory import SharedMemory
import numpy as np
from PIL import Image

root = Path(__file__).resolve().parents[1]
build = Path(sys.argv[1]).resolve() if len(sys.argv)>1 else root/'dist/Golyahki'
fixture = root / 'test-results' / 'ocr-fixture.png'
assert fixture.exists(), 'Run scripts/check_ocr.py first'
env = os.environ.copy()
env.pop('PYTHONPATH', None)
env.pop('PYTHONHOME', None)
windows = os.environ.get('SystemRoot', 'C:/Windows')
env['PATH'] = os.pathsep.join([str(Path(windows) / 'System32'), windows])
report = {}
with tempfile.TemporaryDirectory(prefix='golyah-build-check-') as temporary:
    directory = Path(temporary)
    with Image.open(fixture) as image:
        frame=np.array(image.convert('RGBA'))[:,:,[2,1,0,3]].copy()
    memory=SharedMemory(create=True,size=frame.nbytes)
    try:
        np.ndarray(frame.shape,dtype=np.uint8,buffer=memory.buf)[:]=frame
        payload=''.join(json.dumps({'id':i,'memory':memory.name,'shape':frame.shape,'engine':engine})+'\n'
                        for i,engine in ((1,'auto'),(2,'paddle')))
        worker = subprocess.run([str(build / 'Golyahki-OCR.exe'), '--ocr-worker'], input=payload,
            cwd=directory, env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=45)
    finally:
        memory.close();memory.unlink()
    assert worker.returncode == 0, worker.stderr[-3000:]
    results={response['id']:response['result'] for line in worker.stdout.splitlines()
             if line.startswith('GOLYAH_JSON:')
             for response in [json.loads(line.removeprefix('GOLYAH_JSON:'))]}
    result=results[1]
    assert any(w['text'] == 'quick' for w in result['words'])
    from golyah.windows_ocr import WindowsOCR,WindowsOCRUnavailable
    try:
        WindowsOCR().initialize()
    except WindowsOCRUnavailable:
        pass
    else:
        assert result['engine']=='WindowsOCR',result.get('fallback')
    assert results[2]['engine']=='PaddleOCR' and len(results[2]['words'])==20
    report['ocr'] = {'tokens': len(result['words']), 'seconds': result['seconds'], 'engine':result['engine'],
        'paddle_verified':True,'paddle_seconds':results[2]['seconds'], 'embedded_models': True, 'memory_protocol': 'shared_memory'}
    for name, options in [('main', []), ('appearance', ['--smoke-page', '3']), ('builder', ['--smoke-page', '4']), ('settings', ['--smoke-page', '5']), ('ocr-popup', ['--smoke-ocr', str(fixture)])]:
        image = directory / (name + '.png')
        gui = subprocess.run([str(build / 'Golyahki.exe'), '--smoke', str(image),
            '--data-dir', str(directory / 'data'), *options], cwd=directory, env=env, timeout=50)
        assert gui.returncode == 0 and image.exists(), f'GUI check failed: {name}, exit={gui.returncode}'
        destination = root / 'test-results' / ('packed-' + name + '.png')
        destination.write_bytes(image.read_bytes())
        report[name] = {'exit': gui.returncode, 'screenshot': str(destination)}
report['python_on_path'] = False
report['build_bytes'] = sum(p.stat().st_size for p in build.rglob('*') if p.is_file())
(root / 'test-results' / 'build-report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
print(json.dumps(report, indent=2))
