"""Back up stopped renderer mounts and stage a verified storage merge.

Never removes source files, containers, or volumes. Destination must be a new
directory in the private recovery area, not inside a source mount.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def snapshot(containers, destination, canonical_storage):
    destination = destination.resolve()
    if destination.exists():
        raise ValueError('Use a new private recovery directory')
    raw = subprocess.check_output(['docker', 'inspect', *containers])
    configurations = json.loads(raw)
    if any(item['State']['Running'] for item in configurations):
        raise ValueError('Quiesce the named containers before snapshotting')
    sources = []
    for config in configurations:
        for mount in config['Mounts']:
            if mount['Type'] == 'bind':
                source = Path(mount['Source']).resolve()
                if source not in sources:
                    sources.append(source)
    if canonical_storage.exists():
        sources.append(canonical_storage.resolve())
    if any(destination == source or destination.is_relative_to(source) for source in sources):
        raise ValueError('Recovery must be outside every source')
    destination.mkdir(parents=True)
    (destination/'docker-inspect.json').write_bytes(raw)
    merged = destination/'storage'
    merged.mkdir()
    manifest = []
    for index, source in enumerate(sources):
        backup = destination/'mounts'/str(index)
        if source.is_dir():
            shutil.copytree(source, backup)
            files = [p for p in source.rglob('*') if p.is_file()]
        else:
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            files = [source]
        for path in files:
            relative = path.relative_to(source) if source.is_dir() else Path(path.name)
            saved = backup/relative if source.is_dir() else backup
            sha = digest(path)
            if digest(saved) != sha:
                raise RuntimeError('Snapshot checksum mismatch')
            manifest.append({'source': str(path), 'backup': str(saved.relative_to(destination)), 'sha256': sha})
            if source.name == 'storage':
                target = merged/relative
                if target.exists() and digest(target) != sha:
                    raise RuntimeError(f'Storage merge conflict: {relative}')
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, target)
    (destination/'files.json').write_text(json.dumps(manifest, indent=2))
    print(json.dumps({'verified_files': len(manifest), 'merged_storage_files': sum(p.is_file() for p in merged.rglob('*')), 'snapshot': str(destination)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--containers', nargs='+', required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--canonical-storage', type=Path, required=True)
    args = parser.parse_args()
    snapshot(args.containers, args.destination, args.canonical_storage)
