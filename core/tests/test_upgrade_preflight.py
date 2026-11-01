import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('upgrade_preflight',Path(__file__).resolve().parents[2]/'scripts/check_upgrade_schema.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class UpgradePreflightTests(unittest.TestCase):
    def test_every_required_function_and_base_column_is_needed(self):
        schema={'paths':{'/rpc/'+name:{} for name in module.REQUIRED_RPCS},
                'definitions':{'orgs':{'properties':{name:{} for name in ('id','name','created_at')}}}}
        self.assertTrue(module.assess(schema)['ready'])
        for name in module.REQUIRED_RPCS:
            removed=schema['paths'].pop('/rpc/'+name)
            self.assertFalse(module.assess(schema)['ready'])
            schema['paths']['/rpc/'+name]=removed
        del schema['definitions']['orgs']['properties']['name']
        self.assertFalse(module.assess(schema)['ready'])

    def test_database_mismatch_is_rejected_before_network_access(self):
        with patch.object(module.httpx,'Client') as client:
            with self.assertRaises(ValueError):
                module.inspect({'SUPABASE_URL':'https://one.supabase.co','SUPABASE_SERVICE_KEY':'private'},
                               {'NEXT_PUBLIC_SUPABASE_URL':'https://other.supabase.co'})
            client.assert_not_called()

    def test_origin_cannot_expose_credentials_to_redirect_or_path_destinations(self):
        for value in ('http://remote.invalid','https://user:password@project.supabase.co',
                      'https://project.supabase.co/path','https://project.supabase.co?next=other'):
            with self.subTest(value=value), self.assertRaises(ValueError): module.schema_origin(value)
        self.assertEqual(module.schema_origin('http://127.0.0.1:54321/'),'http://127.0.0.1:54321')
