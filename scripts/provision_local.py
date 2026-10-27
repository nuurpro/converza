"""Generate missing private local service secrets without printing them."""
from pathlib import Path
import argparse
import secrets

from dotenv import dotenv_values, set_key

root = Path(__file__).resolve().parents[1]
path = root/'core/.env'
if not path.exists():
    raise SystemExit('Create core/.env from core/.env.example first')
values = dotenv_values(path)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--adopt-existing', action='store_true', help='Copy missing channel settings from supported service-local env files')
args = parser.parse_args()
channel_keys = {'SALES_BOT_TOKEN', 'MANAGER_BOT_TOKEN', 'SALES_BOT_USERNAME',
                'SALES_WEBHOOK_SECRET', 'MANAGER_WEBHOOK_SECRET',
                'INSTAGRAM_APP_SECRET', 'INSTAGRAM_VERIFY_TOKEN', 'INSTAGRAM_CONNECTIONS', 'INSTAGRAM_GRAPH_VERSION'}
if args.adopt_existing:
    for source in (root/'Sleyz/.env', root/'core/manager/.env'):
        if not source.exists():
            continue
        for key, value in dotenv_values(source).items():
            current = values.get(key) or ''
            if key in channel_keys and value and (not current or current.startswith(('replace_', 'generate_', 'your_'))):
                if value.startswith(('replace_', 'generate_', 'your_')):
                    continue
                set_key(path, key, value)
                values[key] = value
                print(f'Adopted {key} from {source.relative_to(root)}')
for key in ('MPT_API_KEY', 'MANAGER_WEBHOOK_SECRET'):
    current = values.get(key) or ''
    if not current or current.startswith(('replace_', 'generate_', 'your_')):
        set_key(path, key, secrets.token_urlsafe(32))
        print(f'Provisioned {key} in private core/.env')
