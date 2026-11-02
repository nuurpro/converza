import unittest
from unittest.mock import AsyncMock
from services.milo.director.storyboard import decompose, interpret_edit
from services.milo.evals.fixtures import context, campaign


class StoryboardTests(unittest.IsolatedAsyncioTestCase):
    async def test_frozen_provider_is_actionable_and_has_no_fallback(self):
        from services.milo.director.storyboard import DirectorInferenceUnavailable
        error=RuntimeError('private request content');error.body={'code':'ModelArts.81006'}
        model=AsyncMock(side_effect=error)
        with self.assertRaisesRegex(DirectorInferenceUnavailable,'resource is frozen'):
            await decompose(campaign(),context(),model=model)
        self.assertEqual(model.await_count,1)
    async def test_decompose_preserves_exact_approved_text_and_authoritative_constraints(self):
        artifact=campaign(); ctx=context()
        ctx['passport']['hex_colors']=['#123456']; ctx['products'][0]['sku']='field'
        model=AsyncMock(return_value={'directions':[{'prompt':'Bag','subject_action':'Hold','camera_movement':'Static','lighting_style':'Daylight','target_duration_sec':12.0}]})
        value=await decompose(artifact,ctx,product_id='bag',model=model)
        self.assertEqual(value['scenes'][0]['narration_chunk'],artifact['video_script'][0]['spoken_narration'])
        self.assertEqual(value['scenes'][0]['asset_constraints']['required_sku_tags'],['field'])

    async def test_selective_edit_preserves_other_scene_and_flags_narration_change(self):
        from test_milo_director_contracts import scene
        board={'revision':2,'narration_approved':True,'scenes':[scene(1,2),scene(2,2)]}
        model=AsyncMock(return_value={'patches':[{'scene_index':1,'narration_chunk':'Faster hook.'}],'unresolved_instructions':[]})
        value=await interpret_edit(board,'Make hook faster',model=model)
        self.assertEqual(value['changed_scene_indices'],[1]);self.assertEqual(value['reusable_scene_indices'],[2])
        self.assertTrue(value['narration_changed']);self.assertEqual(value['scenes'][1],board['scenes'][1])

    async def test_unapproved_constraint_edit_rejected(self):
        from test_milo_director_contracts import scene
        model=AsyncMock(return_value={'patches':[{'scene_index':1,'asset_constraints':{}}],'unresolved_instructions':[]})
        with self.assertRaises(ValueError): await interpret_edit({'revision':1,'scenes':[scene()]},'remove constraints',model=model)
