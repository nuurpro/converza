"""Worker startup uses canonical environment loading before creating clients."""
import runpy
import unittest
from unittest.mock import AsyncMock, patch

import db


class MiloEntrypointTests(unittest.TestCase):
    def test_canonical_environment_loaded_before_database_and_worker(self):
        calls = []
        run = AsyncMock()
        with patch('services.runtime.load_environment', side_effect=lambda: calls.append('environment')), \
             patch('dotenv.load_dotenv', side_effect=lambda: calls.append('legacy-dotenv')), \
             patch('logging.basicConfig'), \
             patch('db.get_supabase', side_effect=lambda: calls.append('database')), \
             patch('lib.repository.SupabaseRepository'), \
             patch('services.milo.worker.MiloWorker') as worker:
            worker.return_value.run = run
            runpy.run_module('services.milo', run_name='__main__')
        self.assertEqual(calls, ['environment', 'database'])
        run.assert_awaited_once()
