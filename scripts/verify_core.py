"""Run the free core suite and retain exact skipped-gate/test evidence."""
import io
import ipaddress
import json
import os
from pathlib import Path
import sys
import socket
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def main():
    dsn = os.getenv('CONVERZA_WORKFLOW_TEST_DSN')
    memory_dsn = os.getenv('MEMORY_TEST_DSN')
    for value in (dsn, memory_dsn, os.getenv('CONVERZA_FEED_TEST_DSN'), os.getenv('CONVERZA_JOURNEY_TEST_DSN')):
        if not value:
            continue
        from psycopg2.extensions import parse_dsn
        settings = parse_dsn(value)
        if (settings.get('host') not in ('localhost', '127.0.0.1', '::1')
                or settings.get('hostaddr', settings.get('host')) not in ('localhost', '127.0.0.1', '::1')
                or not settings.get('dbname', '').startswith('test_') or settings.get('service')):
            raise SystemExit('SQL verification requires a disposable loopback test_* database')
    os.chdir(ROOT/'core')
    sys.path.insert(0, str(ROOT/'core'))
    # This lane must not inherit usable provider/channel credentials from .env.
    os.environ.update(SALES_BOT_TOKEN='', MANAGER_BOT_TOKEN='', ELEVENLABS_API_KEY='',
                      HUAWEI_MAAS_API_KEY='offline-fixture-not-a-provider-key',
                      SUPABASE_URL='http://127.0.0.1:1', SUPABASE_SERVICE_KEY='offline-fixture')
    connect = socket.socket.connect
    def offline_connect(instance, address):
        if isinstance(address, tuple):
            host = address[0]
            if host != 'localhost' and not ipaddress.ip_address(host).is_loopback:
                raise PermissionError('Offline verification refuses external network connections')
        return connect(instance, address)
    suite = unittest.defaultTestLoader.discover('tests')
    log = io.StringIO()
    with patch.object(socket.socket, 'connect', offline_connect):
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    output = ROOT/'reports/local'
    output.mkdir(parents=True, exist_ok=True)
    (output/'core-tests.log').write_text(log.getvalue(), encoding='utf-8')
    report = {'discovered': result.testsRun, 'passed': result.testsRun-len(result.skipped)-len(result.failures)-len(result.errors),
              'failures': len(result.failures), 'errors': len(result.errors),
              'skipped': [{'test': test.id(), 'reason': reason} for test, reason in result.skipped],
              'sql_lane_enabled': bool(dsn), 'memory_sql_lane_enabled': bool(memory_dsn), 'successful': result.wasSuccessful()}
    (output/'core-tests.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
