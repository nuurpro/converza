"""Create a non-secret keep/remove/preserve manifest from verified recovery metadata."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main(recovery):
    recovery = recovery.resolve()
    source = json.loads((recovery/'manifest.json').read_text(encoding='utf-8'))
    if not all(row['verified'] for row in source['roots'] + source['repositories']):
        raise ValueError('Preservation is not verified')
    original = {row['path'].casefold(): row for row in json.loads((recovery/'Converza.files.json').read_text())}
    retired = {str((ROOT.parent/'Converza_hermes').resolve())}
    deleted = subprocess.check_output(['git', '-C', str(ROOT), 'diff', '--name-only', '--diff-filter=D', '09a3902', '--',
        'core', 'web', 'Milo', 'identities', 'main.py', 'db.py', 'agents', 'lib', 'migrations',
        'package.json', 'package-lock.json', 'requirements.txt', 'static', 'tests', '.env.example'], text=True).splitlines()
    def original_hash(path):
        entry = original.get(path.casefold())
        if entry:
            return entry['sha256']
        return hashlib.sha256(subprocess.check_output(['git', '-C', str(ROOT), 'show', f'09a3902:{path}'])).hexdigest()
    report = {
        'supported_root': str(ROOT), 'recovery_directory': str(recovery),
        'completion': 'blocked_physical_retirement_and_desktop_cwd',
        'keep': ['core/main.py', 'core/db.py', 'core/lib', 'core/services', 'core/manager',
                 'core/migrations', 'core/tests', 'core/evals', 'core/scripts', 'web',
                 'Milo/identity.md', 'Sleyz/identity.md', 'Sleyz/sales_main.py', 'Sleyz/agents',
                 'Sleyz/routers', 'Sleyz/db', 'Sleyz/personas', 'Sleyz/bridge', 'Vea/identity.md',
                 'Vea/services/MoneyPrinterTurbo/app', 'Vea/services/MoneyPrinterTurbo/video_presets',
                 'Vea/services/MoneyPrinterTurbo/test', 'Vea/services/MoneyPrinterTurbo/LICENSE',
                 'compose.yml', 'deployment', 'scripts', 'docs'],
        'removed_source_files': [{'path': path, 'original_sha256': original_hash(path)}
                                 for path in deleted],
        'preserved_roots': source['roots'],
        'preserved_git_repositories': source['repositories'],
        'pending_retirement': [{'path': row['root'], 'state': 'preserved_not_removed',
                                'gate': 'desktop_cwd_and_Git_worktree_unregister' if Path(row['root']).name in ('Converza_ai', 'Converza_hermes', 'converza_bot') else 'directory_deletion_policy'}
                               for row in source['roots'] if Path(row['root']).resolve() != ROOT.resolve() and str(Path(row['root']).resolve()) not in retired],
        'retired_roots': [{'path': path, 'method': 'git worktree remove --force after verified preservation'} for path in retired],
        'unregistered_nested_worktrees': ['converza_bot/.claude/worktrees/sad-bhaskara-9ffede',
            'Converza_ai/.claude/worktrees/pensive-wozniak-353232', 'Converza_ai/.claude/worktrees/mystifying-wozniak-b43996'],
        'pending_supported_tree_cleanup': ['Sleyz/support-bot', 'Sleyz/intention', 'Vea/photo-bot', '_archive',
            'Vea/services/MoneyPrinterTurbo/webui', 'Vea/services/MoneyPrinterTurbo/webui.bat',
            'Vea/services/MoneyPrinterTurbo/webui.sh', 'Vea/services/MoneyPrinterTurbo/cli.py',
            'Vea/services/MoneyPrinterTurbo/docker-compose.yml',
            'Vea/services/MoneyPrinterTurbo/docker-compose.gpu.yml',
            'Vea/services/MoneyPrinterTurbo/docker-compose.release.yml'],
        'renderer': {'storage_volume': 'converza-vea-storage', 'port': 8080,
            'snapshot': str(recovery/'renderer-final'), 'verified_storage_files': 110,
            'legacy_containers': 'removed_after_verified_cutover', 'volumes_deleted': False},
        'secrets': 'Private archives and configuration only; no secret values are included here.',
    }
    (ROOT/'docs/consolidation-manifest.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Manifest: {len(deleted)} removed source files, {len(report['pending_retirement'])} preserved pending roots")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recovery', type=Path)
    main(parser.parse_args().recovery)
