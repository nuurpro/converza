"""Offline swap relevance regressions for both persistence adapters."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from services.vea.store import VeaStore
from services.workflow.state import WorkflowConflict
import test_vea_storage as storage_tests


class SwapRelevanceTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = storage_tests.VeaStorageTests.asyncSetUp
    completed_default = storage_tests.VeaStorageTests.completed_default
    result = storage_tests.VeaStorageTests.result

    async def test_offline_evals_cover_scope_and_visual_relevance_in_all_languages(self):
        from services.vea.evals.run import run
        report = await run()
        cases = {case['id']: case['passed'] for case in report['cases']}
        for language in ('en', 'ru', 'uz'):
            self.assertTrue(cases.get('selected_scope_' + language, False))
            self.assertTrue(cases.get('visual_relevance_' + language, False))

    async def test_ineligible_swap_keeps_approved_export_and_all_state(self):
        row = await self.completed_default()
        draft = await self.repo.get_draft(row['draft_id'])
        await self.repo.transition_draft('org', draft['id'], 'approve', draft['revision'], 'export')
        vea = VeaStore(self.repo)
        before = deepcopy((vea.state, self.milo.state, self.repo.drafts))
        assets = [storage_tests.catalog_asset(**changes) for changes in (
            {'org_id':'foreign'}, {'rights_confirmed':False}, {'width':0}, {'permitted_uses':['internal']})]
        for asset in assets:
            with self.subTest(tags=asset['tags']), patch('services.vea.store.fetch_renderer', AsyncMock(return_value={'assets': [asset]})):
                with self.assertRaises(WorkflowConflict):
                    await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'reject')
            self.assertEqual((vea.state, self.milo.state, self.repo.drafts), before)

    async def test_normalized_und_tag_accepts_and_replays_without_catalog(self):
        row = await self.completed_default()
        vea = VeaStore(self.repo)
        catalog = AsyncMock(return_value={'assets': [
            storage_tests.catalog_asset(tags={'und':['PRODUCT!']})]})
        with patch('services.vea.store.fetch_renderer', catalog):
            new = await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'valid')
        with patch('services.vea.store.fetch_renderer', AsyncMock(side_effect=AssertionError('Replay fetched catalog'))):
            self.assertEqual(await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'valid'), new)
        self.assertEqual(new['revision'], 2)

    async def test_manual_swap_does_not_need_the_scenes_lexical_tags(self):
        row = await self.completed_default()
        vea = VeaStore(self.repo)
        self.milo.state['campaigns'][self.c['id']]['artifact']['video_script'].append(
            {'spoken_narration': 'Second scene', 'visual_broll_cues': 'Mountain landscape', 'on_screen_text': ''})
        catalog = AsyncMock(return_value={'assets': [
            storage_tests.catalog_asset(tags={'en':['Mountain']},product_ids=['other'])]})
        with patch('services.vea.store.fetch_renderer', catalog):
            replaced = await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'wrong-scene')
        self.assertEqual(replaced['revision'], 2)

    async def test_catalog_read_does_not_bypass_concurrent_revision_or_evidence_changes(self):
        row = await self.completed_default()
        vea = VeaStore(self.repo)

        async def changed_evidence(*args):
            self.repo.brand_passports['org']['revision'] = 2
            return {'assets': [storage_tests.catalog_asset()]}

        with patch('services.vea.store.fetch_renderer', changed_evidence), self.assertRaises(WorkflowConflict):
            await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'stale-evidence')
        self.assertEqual((await vea.get_variant('org', row['id']))['revision'], 1)
        self.assertEqual(vea.state['history'], {})

    async def test_sql_adapter_rejects_unlicensed_clip_before_mutation_rpc(self):
        row = await self.completed_default()
        raw = deepcopy(VeaStore(self.repo).state['variants'][row['id']])
        vea = VeaStore(SimpleNamespace(client=object()))
        vea._rpc = AsyncMock(side_effect=[None, raw, raw])
        vea.milo.get_campaign = AsyncMock(return_value=self.c)
        with patch('services.vea.store.fetch_renderer', AsyncMock(return_value={'assets': [
                storage_tests.catalog_asset(rights_confirmed=False,tags={'en':['Unrelated']})]})):
            with self.assertRaises(WorkflowConflict):
                await vea.swap('org', row['id'], 1, 'scene-0-cut-0', 'replacement', 'sql-reject')
        self.assertEqual([call.args[0] for call in vea._rpc.await_args_list], ['replay', 'get'])


class RendererRelevanceContractTests(unittest.TestCase):
    def test_core_eligibility_agrees_with_renderer_positive_match_rule(self):
        from services.vea.store import _relevant_replacement
        path = Path(__file__).resolve().parents[2] / 'Vea/services/MoneyPrinterTurbo/app/services/vea.py'
        spec = importlib.util.spec_from_file_location('consolidation_renderer', path)
        renderer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(renderer)
        cases = [
            ('en', 'STEEL hinge!', {'en': ['steel']}),
            ('en', 'Steel hinge', {'und': ['HINGE.']}),
            ('en', 'Steel hinge', {'ru': ['steel hinge']}),
            ('en', 'Steel hinge', {'en': ['steely']}),
            ('en', 'Steel hinge', {}),
            ('en', '!!!', {'und': ['!!!']}),
            ('ru', '\u0421\u0442\u0430\u043b\u044c \u0448\u043e\u0432', {'ru': ['\u0428\u041e\u0412!']}),
            ('uz', 'O\u02bbzbek chok', {'uz': ["O'zbek"]}),
            ('en', '\uff33\uff34\uff25\uff25\uff2c', {'en': ['steel']}),
        ]
        for language, cue, tags in cases:
            asset = {'id': 'clip', 'kind': 'video', 'duration_sec': 3, 'tags': tags}
            campaign = {'artifact': {'video_script': [{'visual_broll_cues': cue}]}}
            with self.subTest(language=language, cue=cue, tags=tags):
                try:
                    matching = renderer.select_matching_broll(cue, 3, [asset], language)
                    expected = bool(matching)
                except renderer.VeaError as exc:
                    self.assertEqual(exc.code, 'missing_assets')
                    expected = False
                self.assertEqual(_relevant_replacement(asset, {'scene_index': 0}, campaign, language), expected)


if __name__ == '__main__':
    unittest.main()
