"""Private, verified backup of the stopped canonical renderer's named volume.

Never stops containers, rewrites live state, or deletes files/volumes. Confirmation
is mandatory because a full media snapshot can exceed the repository size gate.
"""
import argparse
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def receipt_summary(path):
    with closing(sqlite3.connect(f'file:{path.as_posix()}?mode=ro', uri=True)) as db:
        integrity = [row[0] for row in db.execute('PRAGMA integrity_check')]
        if integrity != ['ok']:
            raise RuntimeError('Renderer SQLite integrity check failed')
        rows = db.execute('SELECT id,data FROM tasks ORDER BY id').fetchall()
    states = Counter(str(json.loads(raw).get('state')) for _, raw in rows)
    return {'integrity': 'ok', 'receipts': len(rows), 'states': dict(states),
            'receipt_digest': hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()}


def secure_directory(path):
    path.mkdir(parents=True, exist_ok=False)
    if os.name == 'nt':
        owner = subprocess.check_output(['whoami'], text=True).strip()
        subprocess.run(['icacls', str(path), '/inheritance:r', '/grant:r',
                        f'{owner}:(OI)(CI)F', 'SYSTEM:(OI)(CI)F'],
                       check=True, capture_output=True)
    else:
        path.chmod(0o700)


def snapshot(container, destination, recovery_root, *, confirmed=False):
    if not confirmed:
        raise ValueError('Confirm the full snapshot size before copying private state')
    destination, recovery_root = destination.resolve(), recovery_root.resolve()
    project = Path(__file__).resolve().parents[1]
    if (destination == recovery_root or not destination.is_relative_to(recovery_root)
            or destination.is_relative_to(project) or destination.exists()):
        raise ValueError('Snapshot must be a new directory inside the private recovery root')
    raw = subprocess.check_output(['docker', 'inspect', container])
    config = json.loads(raw)[0]
    if config['State']['Running']:
        raise ValueError('Quiesce the named renderer before snapshotting')
    storage = next((m for m in config['Mounts'] if m['Destination'] == '/MoneyPrinterTurbo/storage'), None)
    if not storage or storage['Type'] != 'volume' or storage.get('Name') != 'converza-vea-storage':
        raise ValueError('Renderer does not use the expected canonical named volume')
    active = subprocess.check_output(['docker', 'ps', '-q', '--filter', 'volume=converza-vea-storage']).strip()
    if active:
        raise ValueError('Another running container still uses canonical storage')
    secure_directory(destination)
    # Docker inspection contains private environment values; never print it.
    (destination / 'docker-inspect.json').write_bytes(raw)
    saved = destination / 'storage'
    saved.mkdir()
    subprocess.run(['docker', 'cp', f'{container}:/MoneyPrinterTurbo/storage/.', str(saved)], check=True, capture_output=True)
    subprocess.run(['docker', 'cp', f'{container}:/MoneyPrinterTurbo/config.toml', str(destination / 'config.toml')], check=True, capture_output=True)
    files = []
    for path in sorted(saved.rglob('*')):
        if path.is_symlink():
            raise ValueError('Review symlinks before accepting the snapshot')
        if path.is_file():
            files.append({'path': path.relative_to(saved).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
    summary = receipt_summary(saved / 'renderer-state.sqlite3')
    if any(state not in ('-1', '1') for state in summary['states']):
        raise ValueError('Unfinished receipts require reconciliation before cutover')
    report = {'snapshot': str(destination), 'container': container, 'image': config['Image'], 'volume': storage['Name'],
              'files': len(files), 'bytes': sum(item['bytes'] for item in files),
              'config_sha256': digest(destination / 'config.toml'), **summary}
    (destination / 'files.json').write_text(json.dumps(files, indent=2), encoding='utf-8')
    (destination / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    # Verify the copied bytes again before declaring this a usable rollback point.
    if any(digest(saved / item['path']) != item['sha256'] for item in files):
        raise RuntimeError('Snapshot checksum verification failed')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container', default='converza-vea-renderer-1')
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--recovery-root', type=Path, default=Path('E:/Coding/_Converza_recovery'))
    parser.add_argument('--confirm-backup', action='store_true')
    args = parser.parse_args()
    print(json.dumps(snapshot(args.container, args.destination, args.recovery_root, confirmed=args.confirm_backup)))
