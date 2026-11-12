"""Portable paths for the workspace layout and the published knd/ checkout."""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site' if (ROOT / 'site/index.html').is_file() else ROOT
WORK = ROOT / 'build'
SOURCES = ROOT / 'source-assets'
INTERFACES = SOURCES / 'interfaces'
PRIVATE_REPO = 'knd-presentation-sources'

def raw_media():
    """Raw owl generations live in the private repo, not in the public checkout."""
    override = os.environ.get('KND_PRIVATE_SOURCES')
    if override:
        path = Path(override).expanduser().resolve() / 'source-assets/raw-media'
        if path.is_dir():
            return path
        raise FileNotFoundError(f'KND_PRIVATE_SOURCES has no source-assets/raw-media: {path}')
    for base in [ROOT, ROOT.parent.parent / PRIVATE_REPO / 'knd', ROOT.parent / PRIVATE_REPO / 'knd']:
        path = base / 'source-assets/raw-media'
        if any(path.glob('*.mp4')):
            return path
    raise FileNotFoundError(f'Raw owl generations missing; clone the private {PRIVATE_REPO} next to this checkout or set KND_PRIVATE_SOURCES')

def previous_media():
    override = os.environ.get('KND_PREVIOUS_MEDIA')
    if override:
        return Path(override).expanduser().resolve()
    for candidate in [ROOT.parent / 'media', ROOT / '.publish/release/media']:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError('Original media directory missing; clone the whole repository or set KND_PREVIOUS_MEDIA')

def font_path(bold=False):
    override = os.environ.get('KND_FONT_BOLD' if bold else 'KND_FONT') or os.environ.get('KND_FONT')
    if override:
        path = Path(override).expanduser()
        if path.is_file():
            return path
        raise FileNotFoundError(f'Font file does not exist: {path}')
    candidates = [
        Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / ('arialbd.ttf' if bold else 'arial.ttf'),
        Path('/usr/share/fonts/truetype/dejavu') / ('DejaVuSans-Bold.ttf' if bold else 'DejaVuSans.ttf'),
        Path('/usr/share/fonts/truetype/liberation2') / ('LiberationSans-Bold.ttf' if bold else 'LiberationSans-Regular.ttf'),
        Path('/System/Library/Fonts/Supplemental') / ('Arial Bold.ttf' if bold else 'Arial.ttf'),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError('Install a Cyrillic-capable font or set KND_FONT / KND_FONT_BOLD')
