"""Acquire runtime resources from an installed, licensed font package.

Docker installs Debian's fonts-dejavu-core. Native installations can set
MPT_FONT_PATH to DejaVuSans.ttf from their own DejaVu package installation.
No font binaries or generated media belong in source control.
"""
import os
from pathlib import Path
import shutil


def prepare_resources(root=None, font_path=None):
    root = Path(root) if root else Path(__file__).resolve().parents[1]
    source = Path(font_path or os.getenv('MPT_FONT_PATH', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'))
    if not source.is_file():
        raise FileNotFoundError('Install fonts-dejavu-core or set MPT_FONT_PATH to an installed DejaVuSans.ttf')
    for relative in ('resource/fonts', 'resource/songs', 'resource/public', 'storage/tasks'):
        (root / relative).mkdir(parents=True, exist_ok=True)
    target = root / 'resource/fonts/DejaVuSans.ttf'
    if source.resolve() != target.resolve():
        shutil.copyfile(source, target)
    return target


if __name__ == '__main__':
    print(prepare_resources())
