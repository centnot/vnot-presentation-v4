"""Prepare only public KND assets. No server credentials or private keys are copied."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
from project_paths import ROOT, SITE, WORK, previous_media, font_path

PREVIOUS = previous_media()
CLIPS = {
    'erknm': 'V3_s313_v4',
    'ervk': 'V1_s102',
    'monitoring': 'V4_s406_v3',
    'risks': 'V11_s1101',
    'drones': 'V8_s802_v3',
    'ai-cameras': 'V9_s910_v4',
    'assistant': 'V10_s1001_v3',
}

def run(command):
    subprocess.run(command, check=True, cwd=WORK)

def prepare():
    import segno
    (SITE / 'assets').mkdir(exist_ok=True)
    (SITE / 'media').mkdir(exist_ok=True)
    WORK.mkdir(exist_ok=True)
    for name in ['cover-bg.png', 'content-bg.png', 'closing-bg.png', 'forum-logo.png']:
        source = ROOT / 'template-assets' / name
        if source.is_file():
            shutil.copy2(source, SITE / 'assets' / name)
        elif not (SITE / 'assets' / name).is_file():
            raise FileNotFoundError(f'Template asset missing: {name}')
    for target, source in CLIPS.items():
        corrected = WORK / 'video-review/repaired' / (target + '.mp4')
        if corrected.exists():
            shutil.copy2(corrected, SITE / 'media' / (target + '.mp4'))
            for suffix, seek in [('first', ['-ss', '0']), ('last', ['-sseof', '-0.08'])]:
                run(['ffmpeg', '-v', 'error', '-y', *seek, '-i', str(corrected), '-frames:v', '1', '-q:v', '2', str(SITE / f'media/{target}-{suffix}.jpg')])
            continue
        if target in {'assistant', 'ervk', 'monitoring', 'erknm'}:
            # Preserve checked public edits if temporary review renders are removed.
            if all((SITE / 'media' / (target + suffix)).exists() for suffix in ['.mp4', '-first.jpg', '-last.jpg']):
                continue
            raise FileNotFoundError('Run scripts/repair_video_interfaces.py before preparing the site')
        for suffix, destination in [('.mp4', '.mp4'), ('_first.jpg', '-first.jpg'), ('_last.jpg', '-last.jpg')]:
            shutil.copy2(PREVIOUS / (source + suffix), SITE / 'media' / (target + destination))
    content = json.loads((SITE / 'content.json').read_text('utf-8'))
    for instruction in content['instructions']:
        if instruction.get('qr'):
            segno.make(instruction['url'], error='m', micro=False).save(SITE / instruction['qr'], scale=8, dark='#001657', light='#ffffff', border=4)
    # Punycode: a Cyrillic URL is encoded in Kanji mode and some scanners return garbage.
    segno.make('https://' + 'онлайнинспекция.рф'.encode('idna').decode(), error='m', micro=False).save(SITE / 'assets/qr-online.svg', scale=8, dark='#001657', light='#ffffff', border=4)
    lines = [content['title'], content['organization'], 'Рабочая версия к форуму, 12 ноября 2026 года', '', content['intro'], '']
    pending = ['МАТЕРИАЛЫ ДЛЯ ФИНАЛЬНОЙ ВЕРСИИ', '']
    if content.get('needs'):
        pending += ['Вся презентация', *['- ' + value for value in content['needs']], '']
    for index, section in enumerate(content['sections'], 1):
        lines += [f"{index}. {section['title']}", f"ПОКАЗ: {section['cue']}", '', *section['notes'], '']
        if section.get('remarks'):
            lines += ['ДЛЯ ДОКЛАДЧИКА:', *['- ' + value for value in section['remarks']], '']
        if section['needs']:
            pending += [f"{index}. {section['title']}", *['- ' + value for value in section['needs']], '']
        lines += ['-' * 65, '']
    lines += ['ЗАКЛЮЧЕНИЕ', '', content['outro'], '']
    (SITE / 'speech.txt').write_text('\n'.join(lines), encoding='utf-8-sig', newline='\n')
    pending_root = ROOT / 'materials' if (ROOT / 'materials').is_dir() else ROOT
    (pending_root / 'Материалы для финальной версии.txt').write_text('\n'.join(pending), encoding='utf-8-sig', newline='\n')
    (SITE / '.nojekyll').touch()
    print('Prepared public assets, QR codes, speaker text and pending-material list.')

def inspector():
    target = SITE / 'media/inspector.mp4'
    repaired = [WORK / 'video-review/repaired' / (name + '.mp4') for name in ['remote', 'onsite', 'execution']]
    if not all(path.exists() for path in repaired):
        if target.exists():
            print('Retained the checked Inspector edit; temporary source renders are absent.')
            return
        raise FileNotFoundError('Run scripts/repair_video_interfaces.py before building Inspector')
    clips = repaired
    if not target.exists() or any(path.stat().st_mtime > target.stat().st_mtime for path in [*clips, Path(__file__)]):
        captions = ['Дистанционно: объект по видеосвязи', 'Очно: чек-лист и фотофиксация', 'Предписание: подтвердить устранение']
        args = ['ffmpeg', '-hide_banner', '-loglevel', 'warning', '-y']
        filters = []
        shutil.copy2(font_path(bold=True), WORK / 'caption-font.ttf')
        # The generated prescription scene double-exposes frame 70 at its own cut; hold frame 69 instead.
        fixes = ['', '', 'split[main][held];[main][held]freezeframes=first=70:last=70:replace=69,']
        for index, (clip, caption) in enumerate(zip(clips, captions)):
            args += ['-i', str(clip)]
            (WORK / f'caption-{index}.txt').write_text(caption, encoding='utf-8')
            # 1890x1080 like the other clips: a 1920 canvas left black side bars inside the site frame.
            filters.append(f"[{index}:v]{fixes[index]}scale=1890:1080,setsar=1,settb=AVTB,setpts=PTS-STARTPTS,drawbox=x=0:y=ih-148:w=iw:h=148:color=0x001657@0.92:t=fill,drawtext=fontfile='caption-font.ttf':textfile='caption-{index}.txt':fontsize=48:fontcolor=white:x=70:y=h-98[v{index}]")
        filters.append('[v0][v1][v2]concat=n=3:v=1:a=0[out]')
        (WORK / 'inspector-filter.txt').write_text(';\n'.join(filters), encoding='utf-8')
        args += ['-filter_complex_script', 'inspector-filter.txt', '-map', '[out]', '-an', '-r', '24', '-fps_mode', 'cfr', '-c:v', 'libx264', '-profile:v', 'high', '-level:v', '4.1', '-preset', 'fast', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(target)]
        run(args)
    for suffix, seek in [('first', ['-ss', '0']), ('last', ['-sseof', '-0.10'])]:
        run(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', *seek, '-i', str(target), '-frames:v', '1', '-q:v', '2', str(SITE / f'media/inspector-{suffix}.jpg')])
    print('Combined Inspector clip and posters ready.')

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    prepare()
    inspector()
