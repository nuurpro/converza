"""Operator overrides relax relevance, never media eligibility or tenant scope."""
from copy import deepcopy
import json
import os
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from app.services import vea


def asset(**changes):
    return dict(id='clip', org_id='org', product_ids=['initiative'], kind='video',
                duration_sec=8, width=1920, height=1080, sha256='a'*64,
                rights_confirmed=True, permitted_uses=['advertising'],
                tags={'en': ['product']}, **changes)


class OverridePolicyTests(unittest.TestCase):
    def compose(self, assets, overrides=None, reuse=None, product='initiative'):
        scene = dict(spoken_narration='Good product', visual_broll_cues='product', on_screen_text='')
        timing = vea.align_words('Good product', [
            dict(word='Good', start_ms=0, end_ms=300), dict(word='product', start_ms=300, end_ms=1000)], 1000)
        return vea.compile_composition([scene], [timing], [1], assets,
            vea.load_preset('high_velocity_d2c'), {'revision':1, 'hex_colors':[]}, 'en',
            overrides, reuse, product_id=product)

    def test_automatic_selected_initiative_cannot_use_unassigned_or_other_footage(self):
        for products in ([], ['other']):
            clip=asset(); clip['product_ids']=products
            with self.subTest(products=products), self.assertRaises(vea.VeaError):
                self.compose([clip])

    def test_manual_off_tag_cross_initiative_crop_is_allowed_and_recorded(self):
        clip=asset(); clip.update(tags={}, product_ids=['other'])
        result=self.compose([clip], [{'segment_id':'scene-1-clip-1','asset_id':'clip'}])
        self.assertEqual(result['segments'][0]['selection_mode'], 'manual')
        self.assertEqual(result['segments'][0]['asset_id'], 'clip')
        self.assertEqual(result['segments'][0]['crop']['mode'], 'center_crop_no_stretch')

    def test_reused_manual_choice_requires_persisted_override_not_manifest_flag(self):
        clip=asset(); original=self.compose([clip])
        clip.update(tags={}, product_ids=['other'])
        original['segments'][0]['selection_mode']='manual'
        with self.assertRaises(vea.VeaError): self.compose([clip], reuse=original)
        overrides=[{'segment_id':'scene-1-clip-1','asset_id':'clip'}]
        result=self.compose([clip], overrides, original)
        self.assertEqual(result['segments'][0]['asset_id'],'clip')

    def test_automatic_remains_semantically_matched(self):
        clip=asset(); clip['tags']={'en':['mountain']}
        with self.assertRaises(vea.VeaError): self.compose([clip])

    def test_manual_invalid_dimensions_and_short_clips_rejected(self):
        for change in ({'width':0},{'height':True},{'width':float('nan')},
                       {'width':1,'height':16384},{'duration_sec':.5}):
            clip=asset(); clip.update(change)
            with self.subTest(change=change), self.assertRaises(vea.VeaError):
                self.compose([clip],[{'segment_id':'scene-1-clip-1','asset_id':'clip'}])

    def test_catalog_manual_mode_filters_tenant_rights_but_not_initiative(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'clip.mp4').write_bytes(b'fixture')
            clip=asset(); clip.update(path='clip.mp4',sha256=vea.file_hash(root/'clip.mp4'))
            entries=[clip, {**clip,'id':'unassigned','product_ids':[]},
                     {**clip,'id':'cross','product_ids':['other']},
                     {**clip,'id':'foreign','org_id':'other'},
                     {**clip,'id':'unlicensed','rights_confirmed':False},
                     {**clip,'id':'negated','permitted_uses':'not advertising'},
                     {**clip,'id':'malformed','permitted_uses':{'advertising':False}}]
            (root/'catalog.json').write_text(json.dumps({'schema_version':1,'assets':entries}))
            with patch.dict(os.environ,{'VEA_ASSET_ROOT':folder}):
                auto=vea.load_assets('org','initiative',verify_media=False)
                self.assertEqual([a['id'] for a in auto],['clip'])
                manual=vea.load_assets('org','initiative',verify_media=False,selection='manual')
                self.assertEqual([a['id'] for a in manual],['clip','cross','unassigned'])


if __name__=='__main__': unittest.main()
