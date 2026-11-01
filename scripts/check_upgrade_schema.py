"""Read-only deployment preflight. Does not execute SQL or query customer rows."""
import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx

REQUIRED_RPCS = (
    'workspace_save_passport', 'pending_approval_feed', 'milo_assert_product',
    'workflow_transition', 'workflow_snapshot', 'workflow_read_events',
    'milo_store', 'vea_store', 'memory_claim_jobs', 'memory_complete_job',
    'memory_fail_job', 'memory_retry_job', 'memory_forget', 'memory_forget_source',
    'sleyz_accept_inbound', 'sleyz_claim_jobs', 'sleyz_ready_job', 'sleyz_fail_job',
    'sleyz_claim_learning', 'sleyz_complete_learning', 'sleyz_fail_learning',
    'sleyz_retry_learning', 'sleyz_retry_generation', 'sleyz_telemetry', 'sleyz_refresh',
)

# This is a deployment compatibility check, not proof of function semantics or
# ownership integrity. SQL migrations/tests and the ownership audit remain gates.
REQUIRED_TABLES = {
    'orgs': {'id': 'uuid', 'name': None, 'created_at': None},
    'brand_passports': {'id': 'uuid', 'org_id': 'uuid', 'owner_user_id': 'uuid',
                        'onboarding_answers': None, 'voice_rules': None, 'negative_constraints': None},
    'drafts': {'id': 'uuid', 'org_id': 'uuid', 'revision': None, 'generation_status': None,
               'delivery_status': None, 'sleyz_artifact': None, 'vea_artifact': None,
               'superseded_by': 'uuid'},
    'prospects': {'id': 'uuid', 'org_id': 'uuid', 'platform': None, 'external_id': None},
    'messages': {'id': 'uuid', 'org_id': 'uuid', 'prospect_id': 'uuid', 'content': None},
    'tg_connections': {'org_id': 'uuid', 'business_connection_id': None},
    'agent_runs': {'id': 'uuid', 'org_id': 'uuid'},
    'agent_run_steps': {'id': 'uuid', 'org_id': 'uuid'},
    'squad_messages': {'id': 'uuid', 'org_id': 'uuid'},
    'agent_memory': {'id': 'uuid', 'org_id': 'uuid'},
    'brand_products': {'id': 'uuid', 'org_id': 'uuid', 'sku': None, 'stock_count': None},
    'brand_knowledge': {'id': 'uuid', 'org_id': 'uuid'},
    'memory_sources': {'id': 'uuid', 'org_id': 'uuid', 'atoms': None},
    'memory_source_revisions': {'source_id': 'uuid', 'org_id': 'uuid'},
    'memory_index_jobs': {'id': 'uuid', 'org_id': 'uuid'},
    'memory_price_history': {'id': 'uuid', 'org_id': 'uuid'},
    'workflow_event_cursors': {'org_id': 'uuid'},
    'workflow_events': {'org_id': 'uuid', 'id': None},
    'workflow_idempotency': {'org_id': 'uuid'},
    'sleyz_inbound': {'id': 'uuid', 'org_id': 'uuid'},
    'sleyz_learning_jobs': {'id': 'uuid', 'org_id': 'uuid'},
    'objection_telemetry': {'id': 'uuid', 'org_id': 'uuid'},
    'milo_settings': {'org_id': 'uuid'},
    'milo_campaigns': {'id': 'uuid', 'org_id': 'uuid', 'product_id': None, 'revision': None},
    'milo_jobs': {'id': 'uuid', 'org_id': 'uuid'},
    'milo_objections': {'id': 'uuid', 'org_id': 'uuid'},
    'milo_decisions': {'org_id': 'uuid'},
    'vea_variants': {'id': 'uuid', 'org_id': 'uuid', 'clip_overrides': None},
    'vea_variant_revisions': {'variant_id': 'uuid'},
    'vea_decisions': {'org_id': 'uuid'},
}


def assess(schema):
    paths = schema.get('paths', {})
    definitions = schema.get('definitions', {})
    functions = {name: '/rpc/' + name in paths for name in REQUIRED_RPCS}
    tables = {}
    for table, required in REQUIRED_TABLES.items():
        columns = definitions.get(table, {}).get('properties', {})
        tables[table] = {name: name in columns and (expected is None or
                         columns[name].get('format') == expected)
                         for name, expected in required.items()}
    return {'ready': all(functions.values()) and all(all(fields.values()) for fields in tables.values()),
            'required_rpcs': functions, 'org_columns': tables['orgs'], 'required_tables': tables}


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
