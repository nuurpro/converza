import unittest
from pydantic import ValidationError
from services.milo.director.contracts import ScenePromptPayload, Storyboard, MasterAssemblyManifest


def scene(index=1, total=1):
    return dict(scene_index=index,total_scenes=total,target_duration_sec=3.0,
        narration_chunk='Exact approved narration.',
        visual_directive=dict(prompt='Show bag',subject_action='Hold bag',camera_movement='Static',lighting_style='Daylight'),
        asset_constraints=dict(required_sku_tags=['bag'],brand_hex_palette=['#112233'],negative_visual_constraints=['No competitors']),
        overlay_text=dict(text='Exact overlay',font_family='DejaVuSans',font_size=54,color='#FFFFFF',position='center',animation='none',start_sec=0.0,end_sec=3.0))


class ContractsTests(unittest.TestCase):
    def test_exact_text_and_no_extra_fields(self):
        value=scene(); value['narration_chunk']=' Uzbek oʻ  Русский\n'
        self.assertEqual(ScenePromptPayload.model_validate(value).narration_chunk,value['narration_chunk'])
        with self.assertRaises(ValidationError): ScenePromptPayload.model_validate({**value,'approved':True})

    def test_bounds_and_strict_indices(self):
        for patch in ({'scene_index':True},{'scene_index':2},{'target_duration_sec':float('nan')}):
            with self.assertRaises(ValidationError): ScenePromptPayload.model_validate({**scene(),**patch})
        value=scene(); value['overlay_text']['end_sec']=4
        with self.assertRaises(ValidationError): ScenePromptPayload.model_validate(value)

    def test_storyboard_order_and_master_requires_complete_tokens(self):
        with self.assertRaises(ValidationError): Storyboard.model_validate({'revision':1,'scenes':[scene(2,2),scene(1,2)]})
        with self.assertRaises(ValidationError): MasterAssemblyManifest.model_validate({'scenes':[]})
