import importlib.util
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor


class DurableStateTests(unittest.TestCase):
    def state_class(self):
        path=Path(__file__).parents[2]/'app/services/sqlite_state.py'
        spec=importlib.util.spec_from_file_location('milo_sqlite_state',path)
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        return module.SQLiteState

    def test_restart_preserves_completed_video_binding_and_fails_interrupted_tasks(self):
        State=self.state_class()
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'tasks.sqlite3'
            first=State(filename)
            first.start_runtime()
            binding={'job_id':'j','provider_attempt':1}
            first.update_task('complete',state=4,milo_binding=binding)
            first.update_task('complete',state=1,videos=['final-1.mp4'])
            first.update_task('interrupted',state=4,progress=50,milo_binding=binding)
            second=State(filename)
            self.assertEqual(second.get_task('interrupted')['state'],4)
            with self.assertRaises(RuntimeError):second.start_runtime()
            first.stop_runtime();second.start_runtime()
            self.assertEqual(second.get_task('complete')['state'],1)
            self.assertEqual(second.get_task('complete')['videos'],['final-1.mp4'])
            self.assertEqual(second.get_task('complete')['milo_binding'],binding)
            self.assertEqual(second.get_task('interrupted')['state'],-1)
            self.assertEqual(second.get_task('interrupted')['error_code'],'renderer_restarted')
            self.assertEqual(second.get_task('interrupted')['milo_binding'],binding)
            second.stop_runtime()

    def test_atomic_updates_preserve_binding_and_lists_are_isolated(self):
        State=self.state_class()
        with tempfile.TemporaryDirectory() as folder:
            state=State(Path(folder)/'state.sqlite3')
            state.update_task('t',state=4,milo_binding={'job_id':'j'})
            state.update_task('t',state=4,progress=70)
            with self.assertRaises(ValueError):state.update_task('t',state=1,milo_binding={'job_id':'other'})
            rows,count=state.get_all_tasks(1,10)
            self.assertEqual(count,1);rows[0]['milo_binding']['job_id']='modified'
            self.assertEqual(state.get_task('t')['milo_binding'],{'job_id':'j'})
            state.delete_task('t');self.assertIsNone(state.get_task('t'))

    def test_concurrent_clients_merge_partial_receipt_updates_without_losses(self):
        State=self.state_class()
        with tempfile.TemporaryDirectory() as folder:
            filename=Path(folder)/'state.sqlite3'
            first,second=State(filename),State(filename)
            first.update_task('t',milo_binding={'job_id':'j'})
            def update(index):
                (first if index%2 else second).update_task('t',**{'field_'+str(index):index})
            with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(update,range(20)))
            final=first.get_task('t')
            self.assertTrue(all(final['field_'+str(i)]==i for i in range(20)))
            self.assertEqual(final['milo_binding'],{'job_id':'j'})
