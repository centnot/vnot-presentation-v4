"""Extract review contact sheets from the actual public MP4s; never alter sources."""
from pathlib import Path
import json
import cv2
from PIL import Image, ImageDraw, ImageFont
from project_paths import ROOT, SITE, font_path

OUT = ROOT / 'build' / 'video-review'
OUT.mkdir(parents=True, exist_ok=True)
FONT = ImageFont.truetype(str(font_path()), 20)

def frame(path, seconds):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    capture.set(cv2.CAP_PROP_POS_FRAMES, min(count - 1, round(seconds * fps)))
    ok, bgr = capture.read()
    if not ok:
        # Some old exports advertise one extra frame in their container.
        capture.set(cv2.CAP_PROP_POS_FRAMES, max(0, min(count - 3, round(seconds * fps) - 1)))
        ok, bgr = capture.read()
    capture.release()
    if not ok:
        raise ValueError(f'Cannot decode {path.name} at {seconds}')
    return Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))

def sheet(path, times, output, crop=None, width=480, columns=4):
    samples = []
    for seconds in times:
        im = frame(path, seconds)
        if crop:
            im = im.crop(crop)
        im = im.resize((width, round(im.height * width / im.width)), Image.Resampling.LANCZOS)
        samples.append(im)
    height = max(im.height for im in samples) + 30
    result = Image.new('RGB', (columns * width, ((len(samples) + columns - 1) // columns) * height), '#081225')
    draw = ImageDraw.Draw(result)
    for index, (im, seconds) in enumerate(zip(samples, times)):
        x, y = index % columns * width, index // columns * height
        result.paste(im, (x, y + 30))
        draw.text((x + 8, y + 3), f'{path.stem}  {seconds:05.2f}s', font=FONT, fill='white')
    result.save(output, quality=92)

def main():
    metadata = []
    for path in sorted((SITE / 'media').glob('*.mp4')):
        cap = cv2.VideoCapture(str(path))
        fps, count = cap.get(cv2.CAP_PROP_FPS), int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        duration = count / fps
        n = 24 if duration > 10 else 16
        times = [round(i * (duration - 1 / fps) / (n - 1), 4) for i in range(n)]
        sheet(path, times, OUT / f'{path.stem}-sheet.jpg')
        metadata.append(dict(file=path.name, fps=fps, frames=count, width=width, height=height, duration=duration, samples=times))
    (OUT / 'metadata.json').write_text(json.dumps(metadata, indent=2), encoding='utf-8')
    print(json.dumps([{k: v for k, v in row.items() if k != 'samples'} for row in metadata], indent=2))

if __name__ == '__main__':
    main()
