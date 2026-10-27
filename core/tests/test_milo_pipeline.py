"""Marketing grounding gates: real spans, current proof, bounded rewrites."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

from services.milo.contracts import MiloCampaignArtifact
from services.milo.pipeline import extract_objections, generate_campaign, validate_brand_compliance
from services.milo.evidence import get_top_buyer_objections, prepare_evidence


def fixture():
    return {
        'org_id': 'a', 'brand_revision': 3,
        'passport': {'target_audience': 'Outdoor commuters', 'campaign_language': 'en',
                     'negative_constraints': ['Never guarantee lifetime durability.'],
                     'banned_terms': ['indestructible'], 'competitor_names': ['Acme']},
        'sources': [{'id': 'fact', 'org_id': 'a', 'revision': 2, 'kind': 'product', 'external_id': 'p',
                     'content': 'The shell uses reinforced stitching.', 'deleted_at': None}],
        'products': [{'id': 'p', 'org_id': 'a', 'name': 'Travel bag', 'revision': 2}],
        'proof_points': [{'id': 'proof', 'source_id': 'fact', 'revision': 2,
                          'quote': 'The shell uses reinforced stitching.', 'product_id': 'p',
                          'objection_topics': ['durability'], 'confirmed_by': 'owner', 'confirmed_at': '2026-10-19T00:00:00+00:00'}],
        'objections': [{'id': 'buyer', 'org_id': 'a', 'prospect_id': 'one', 'inbound_id': 'message',
                        'product_id': 'p', 'topic': 'durability', 'buyer_text': 'Will the stitching last?',
                        'created_at': '2026-10-19T00:00:00+00:00'}],
    }


def artifact():
    return {'schema_version': 1, 'trigger_reason': 'server supplied',
            'target_persona': {'id': 'default', 'name': 'Outdoor commuters', 'description': 'Outdoor commuters'},
            'language': 'en', 'hooks': [{'framework': f, 'text': t} for f, t in
                [('A', 'Will the stitching last?'), ('B', 'The shell uses reinforced stitching.'), ('C', 'DM us for details.')]],
            'video_script': [{'spoken_narration': 'The shell uses reinforced stitching.', 'visual_broll_cues': 'Show the bag seam.', 'on_screen_text': 'Reinforced stitching'}],
            'social_captions': {'instagram': 'Ask about our bag.', 'telegram': 'DM us for details.', 'tiktok': 'Will the stitching last?'},
            'buyer_quotes': [{'source_id': 'buyer', 'text': 'Will the stitching last?'}],
            'proof_references': [{'source_id': 'fact', 'revision': 2, 'quote': 'The shell uses reinforced stitching.'}],
            'brand_revision': 3}


class EvidenceTests(unittest.TestCase):
    def test_explicit_product_without_topic_never_selects_a_busier_product(self):
        context = fixture()
        context['objections'] += [
            {**context['objections'][0], 'id': str(n), 'prospect_id': str(n), 'product_id': 'q'}
            for n in range(3)]
        self.assertEqual(prepare_evidence(context, product_id='p')['selected']['product_id'], 'p')

    def test_distinct_conversations_and_products_and_organizations(self):
        context = fixture()
        rows = context['objections']
        rows += [{**rows[0], 'id': 'repeat'}, {**rows[0], 'id': 'foreign', 'org_id': 'b'},
                 {**rows[0], 'id': 'other', 'product_id': 'q'}]
        ranked = get_top_buyer_objections(rows, org_id='a')
        self.assertEqual(len(ranked), 2)
        self.assertEqual([r['count'] for r in ranked], [1, 1])

    def test_missing_and_stale_proof_request_evidence(self):
        context = fixture()
        self.assertEqual(prepare_evidence(context)['missing_evidence'], [])
        context['sources'][0]['revision'] = 3
        self.assertTrue(prepare_evidence(context)['missing_evidence'])
        context['objections'] = []
        self.assertTrue(prepare_evidence(context)['missing_evidence'])

    def test_no_owner_confirmation_means_no_verified_fact(self):
        context = fixture()
        context['proof_points'][0].pop('confirmed_by')
        self.assertTrue(prepare_evidence(context)['missing_evidence'])

    def test_product_source_cannot_become_brandwide_by_omitting_product(self):
        context=fixture(); context['proof_points'][0]['product_id']=None
        context['objections'][0]['product_id']='different-product'
        self.assertTrue(prepare_evidence(context)['missing_evidence'])


class ComplianceTests(unittest.TestCase):
    def test_number_must_match_a_complete_evidence_token(self):
        context=fixture(); draft=artifact()
        context['objections'][0]['buyer_text']='Will it last 20 years?'
        draft['buyer_quotes'][0]['text']='Will it last 20 years?'
        draft['hooks'][1]['text']='Guaranteed for 2 years.'
        self.assertFalse(validate_brand_compliance(draft,context)['passed'])

    def test_valid_artifact_and_banned_competitor_terms(self):
        context = fixture()
        draft = artifact()
        self.assertTrue(validate_brand_compliance(draft, context)['passed'])
        draft['hooks'][1]['text'] = 'Acme cannot compete with this indestructible shell.'
        result = validate_brand_compliance(draft, context)
        self.assertFalse(result['passed'])
        self.assertGreaterEqual(len(result['violations']), 2)

    def test_fabricated_quote_stale_fact_and_unknown_persona_fail(self):
        for modify in [lambda a: a['buyer_quotes'][0].update(text='A made up concern'),
                       lambda a: a['proof_references'][0].update(revision=1),
                       lambda a: a.update(target_persona={'id':'fake','name':'Fake','description':'Fake'})]:
            draft = artifact(); modify(draft)
            self.assertFalse(validate_brand_compliance(draft, fixture())['passed'])

    def test_exact_framework_matrix_required(self):
        draft = artifact(); draft['hooks'][2]['framework'] = 'A'
        with self.assertRaises(ValueError):
            MiloCampaignArtifact.model_validate(draft)


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_selected_scope_is_server_owned_not_model_metadata(self):
        draft = artifact()
        draft.update(product_id='invented', topic='price', selected_scope={'product_id': 'invented', 'topic': 'price'})
        model = AsyncMock(side_effect=[draft, {'passed': True, 'violations': []}])
        result = await generate_campaign(fixture(), model=model)
        self.assertTrue(result['compliance']['passed'])
        self.assertEqual(result.get('selected_scope'), {'product_id': 'p', 'topic': 'durability'})
        self.assertNotIn('product_id', result['artifact'])

    async def test_explicit_provider_language_outage_is_actionable_without_fallback(self):
        from services.milo.errors import LanguageServiceUnavailable
        from services.milo.pipeline import _model
        error=RuntimeError('Do not expose arbitrary provider bodies')
        error.body={'code':'ModelArts.81013','message':'Vendor multilingual maintenance'}
        with patch('services.llm.complete_json',AsyncMock(side_effect=error)) as provider:
            with self.assertRaises(LanguageServiceUnavailable):
                await _model([],schema={},operation='creative')
            self.assertEqual(provider.await_count,1)

    async def test_extraction_preserves_unicode_and_rejects_fabrication(self):
        model = AsyncMock(return_value={'objections': [{'topic': 'price', 'product_id': None, 'buyer_text': 'Нарх қиммат'}]})
        result = await extract_objections('Нарх қиммат — can you help?', [], model=model)
        self.assertEqual(result[0]['span_start'], 0)
        self.assertEqual(result[0]['span_end'], len('Нарх қиммат'))
        model.return_value['objections'][0]['buyer_text'] = 'not in source'
        with self.assertRaises(ValueError):
            await extract_objections('Нарх қиммат', [], model=model)

    async def test_no_evidence_never_calls_creative_model(self):
        model = AsyncMock()
        context = fixture(); context['objections'] = []
        result = await generate_campaign(context, prompt='Invent a launch', model=model)
        self.assertTrue(result['missing_evidence'])
        model.assert_not_awaited()

    async def test_two_rewrites_then_block_semantic_claim(self):
        draft = artifact()
        model = AsyncMock(side_effect=[copy.deepcopy(draft), {'passed': False, 'violations': ['Unsupported lifetime guarantee']}]*3)
        result = await generate_campaign(fixture(), model=model)
        self.assertEqual(model.await_count, 6)
        self.assertFalse(result['compliance']['passed'])
        self.assertTrue(result['compliance']['semantic_checked'])

    async def test_language_override_and_metadata_cannot_be_invented(self):
        draft = artifact(); draft['language'] = 'ru'
        model = AsyncMock(side_effect=[draft, {'passed': True, 'violations': []}])
        result = await generate_campaign(fixture(), trigger='spike', language='ru', model=model)
        value = result['artifact']
        self.assertEqual(value['language'], 'ru')
        self.assertEqual(value['trigger_reason'], 'Generated from 1 recent buyer conversation about durability')
        self.assertTrue(result['compliance']['passed'])

    async def test_server_owns_verbatim_quote_and_proof_metadata(self):
        draft=artifact()
        draft['buyer_quotes']=[{'source_id':'wrong-inbound-id','text':'Translated or fabricated buyer words'}]
        draft['proof_references']=[{'source_id':'invented-proof','revision':999,'quote':'A made up fact'}]
        model=AsyncMock(side_effect=[draft,{'passed':True,'violations':[]}])
        result=await generate_campaign(fixture(),model=model)
        self.assertEqual(result['artifact']['buyer_quotes'],artifact()['buyer_quotes'])
        self.assertEqual(result['artifact']['proof_references'],artifact()['proof_references'])
        self.assertTrue(result['compliance']['passed'])

    async def test_reviewer_only_sees_campaigns_cited_proof_with_original_qualifications(self):
        context=fixture()
        context['sources'].append({'id':'other','org_id':'a','revision':1,'kind':'product','external_id':'q','content':'The other bag is waterproof.'})
        context['proof_points'].append({'id':'other','source_id':'other','revision':1,'quote':'The other bag is waterproof.',
            'product_id':'q','confirmed_by':'owner','confirmed_at':'now'})
        model=AsyncMock(side_effect=[artifact(),{'passed':True,'violations':[]}])
        await generate_campaign(context,model=model)
        review_data=model.await_args_list[1].args[0][1]['content']
        self.assertNotIn('waterproof',review_data)
        self.assertIn('source_context',review_data)

    async def test_malformed_reviewer_is_rewritten_twice_then_blocked(self):
        model=AsyncMock(side_effect=[artifact(),{'passed':'yes','violations':[]}]*3)
        result=await generate_campaign(fixture(),model=model)
        self.assertEqual(model.await_count,6)
        self.assertFalse(result['compliance']['passed'])
