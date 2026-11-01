"""Read-only deployment preflight. Does not execute SQL or query customer rows."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx

REQUIRED_RPCS = ('workspace_save_passport', 'pending_approval_feed', 'milo_assert_product')


def assess(schema):
    paths = schema.get('paths', {})
    columns = schema.get('definitions', {}).get('orgs', {}).get('properties', {})
    functions = {name: '/rpc/' + name in paths for name in REQUIRED_RPCS}
    fields = {name: name in columns for name in ('id', 'name', 'created_at')}
    return {'ready': all(functions.values()) and all(fields.values()),
            'required_rpcs': functions, 'org_columns': fields}


def schema_origin(raw):
    url = urlsplit(raw)
    if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
            or url.path not in ('', '/') or url.query or url.fragment
            or (url.scheme == 'http' and url.hostname not in ('127.0.0.1', 'localhost', '::1'))):
        raise ValueError('Supabase must use a fixed HTTPS origin or loopback HTTP origin')
    return str(httpx.URL(raw)).rstrip('/')


def inspect(core, frontend):
    origin = schema_origin(core.get('SUPABASE_URL') or '')
    if origin != schema_origin(frontend.get('NEXT_PUBLIC_SUPABASE_URL') or ''):
        raise ValueError('Frontend and backend must use the same authenticated database')
    key = core.get('SUPABASE_SERVICE_KEY')
    if not key:
        raise ValueError('Server-side Supabase metadata credentials are missing')
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        response = client.get(origin + '/rest/v1/', headers={
            'apikey': key, 'Authorization': 'Bearer ' + key, 'Accept': 'application/openapi+json'})
        if response.status_code != 200:
            raise RuntimeError(f'Schema metadata unavailable ({response.status_code}); no migration was executed')
        return {'same_auth_database': True, **assess(response.json())}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-ready', action='store_true')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        report = inspect(dotenv_values(root / 'core/.env'), dotenv_values(root / 'web/.env.local'))
        print(json.dumps(report))
        raise SystemExit(int(args.require_ready and not report['ready']))
    except (ValueError, RuntimeError, httpx.HTTPError) as error:
        print(json.dumps({'ready': False, 'error_type': type(error).__name__,
                          'detail': str(error) if not isinstance(error, httpx.HTTPError) else 'Schema metadata connection failed'}))
        raise SystemExit(1)
