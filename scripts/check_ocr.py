"""Exercise real OCR twice on a reproducible image; does not access user screen content."""
import json
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from golyah.ocr import OCRRunner

sys.stdout.reconfigure(encoding="utf-8")
folder = Path("test-results")
folder.mkdir(exist_ok=True)
image = Image.new("RGB", (1920, 1080), "#292f2c")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 36)
for i, line in enumerate(["She gave them a quick look.", "You will experience a challenging battle.", "I went home after running in the park."]):
    draw.text((110, 120 + i * 100), line, font=font, fill="#e6eee8")
path = folder / "ocr-fixture.png"
image.save(path)
runner = OCRRunner('paddle' if '--paddle' in sys.argv else 'auto')
results = []
for i in range(2):
    start = time.perf_counter()
    result = runner.recognize(str(path))
    result["totalSeconds"] = round(time.perf_counter() - start, 3)
    results.append(result)
    print("OCR_RUN", i + 1, json.dumps(result, ensure_ascii=False), flush=True)
(folder / "ocr-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
assert any("quick" in w["text"].lower() for w in results[-1]["words"])
