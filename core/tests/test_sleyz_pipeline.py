import asyncio
from datetime import datetime, timezone
import unittest
from unittest.mock import AsyncMock

from services.sleyz.contracts import Classification, intent_for_score
from services.sleyz.tools import SalesTools, validate_commerce_snapshot, validate_citations


def product(**values):
    return {'id':'p1','org_id':'a','name':'Founder course','description':'Two coaching sessions',
            'sku':'course/one','price':'100.00','currency':'USD','stock_count':3,'revision':2,
            'checkout_url_template':'https://shop.example/checkout?sku={sku}&quantity={quantity}', **values}


class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.tools = SalesTools('a', [product(), product(id='other',org_id='b',sku='secret')], [])

    def test_thresholds_and_invalid_scores(self):
        for value, expected in [(0,'COLD'),(.399,'COLD'),(.4,'WARM'),(.749,'WARM'),(.75,'HOT'),(1,'HOT')]:
            self.assertEqual(intent_for_score(value), expected)
        for value in (-1,1.1,float('nan'),True):
            with self.assertRaises(ValueError): intent_for_score(value)

    def test_catalog_is_scoped_and_exact_sku_wins(self):
        self.assertEqual(len(self.tools.query_product_catalog('course/one')),1)
        self.assertEqual(self.tools.query_product_catalog('secret'),[])
        self.assertEqual(self.tools.query_product_catalog('unknown'),[])

    def test_descriptor_overlap_cannot_select_an_unrelated_product(self):
        tools=SalesTools('a',[product(name='Travel Mug',sku='mug',description='Available in red')],[])
        self.assertEqual(tools.query_product_catalog('red iPhone'),[])

    def test_missing_sku_fails_with_operator_configuration_error(self):
        with self.assertRaises(ValueError):
            SalesTools('a',[product(sku=None)],[]).generate_payment_link(None,1)

    def test_link_is_deterministic_and_encodes_sku(self):
        link = self.tools.generate_payment_link('course/one',2)
        self.assertEqual(link,'https://shop.example/checkout?sku=course%2Fone&quantity=2')
        self.assertEqual(link,self.tools.generate_payment_link('course/one',2))

    def test_unknown_stock_insufficient_quantity_and_unconfigured_checkout_fail(self):
        for changes, quantity in [({'stock_count':None},1),({'stock_count':0},1),({},4),({},0),({},True),({},1.5),({'checkout_url_template':None},1),({'checkout_url_template':'http://unsafe/{sku}'},1),({'checkout_url_template':'https://shop.example/{unknown}'},1)]:
            with self.subTest(changes=changes,quantity=quantity), self.assertRaises(ValueError):
                SalesTools('a',[product(**changes)],[]).generate_payment_link('course/one',quantity)

    def test_stale_snapshot_blocks_delivery_but_unrelated_changes_do_not(self):
        artifact={'product_snapshot':[product()], 'quantity':1,'checkout_link':self.tools.generate_payment_link('course/one',1)}
        validate_commerce_snapshot(artifact,[product()])
        for changes in ({'price':'110'},{'stock_count':2},{'sku':'new'},{'revision':3},{'checkout_url_template':None}):
            with self.assertRaises(ValueError): validate_commerce_snapshot(artifact,[product(**changes)])
        with self.assertRaises(ValueError): validate_commerce_snapshot(artifact,[])

    def test_only_resolved_delivered_objections_are_winning(self):
        rows=[{'source_id':'ok','kind':'objection','revision':1,'metadata':{'status':'PUBLISHED','resolved_at':'now','delivered_at':'now'},'atoms':[{'kind':'objection','objection':'price too high','answer':'value'}]},
              {'source_id':'bad','kind':'manual','content':'price too high'}]
        self.assertEqual([r['source_id'] for r in SalesTools('a',[],rows).lookup_objection_playbook('price')],['ok'])

    def test_citations_validate_source_revision_and_quote_spans(self):
        evidence=[{'source_id':'s1','revision':3,'content':'Two coaching sessions','atoms':[{'kind':'fact','text':'Two coaching sessions'}]}]
        valid={'source_id':'s1','revision':3,'span':[0,21]}
        self.assertEqual(validate_citations([valid],evidence),[valid])
        for ref in ({**valid,'revision':2},{**valid,'source_id':'invented'},{**valid,'span':[0,100]}, {'source_id':'s1','revision':3,'atom_index':9}):
            with self.assertRaises(ValueError): validate_citations([ref],evidence)

    def test_citation_cannot_crop_a_negative_policy_into_a_positive_claim(self):
        text='Our shoes are not waterproof.'
        start=text.index('waterproof')
        evidence=[{'source_id':'s1','revision':1,'content':text,'atoms':[{'kind':'fact','text':'waterproof'}]}]
        for ref in ({'source_id':'s1','revision':1,'span':[start,start+10]}, {'source_id':'s1','revision':1,'atom_index':0}):
            with self.assertRaises(ValueError): validate_citations([ref],evidence)


class StructuredClassificationTests(unittest.TestCase):
    def test_catalog_input_has_canonical_commerce_fields_and_rejects_bad_templates(self):
        from lib.memory_routes import ProductInput
        valid={'name':'Course','price':'100','currency':'USD','sku':'course','stock_count':2,
               'checkout_url_template':'https://shop.example/{sku}?quantity={quantity}'}
        self.assertEqual(ProductInput.model_validate(valid).stock_count,2)
        for changed in ({'stock_count':-1},{'stock_count':True},{'checkout_url_template':'http://unsafe/{sku}'},
                        {'checkout_url_template':'https://{sku}.example/checkout'}):
            with self.assertRaises(ValueError): ProductInput.model_validate({**valid,**changed})

    def test_objection_must_be_an_exact_buyer_span(self):
        raw={'intent_score':.6,'product_query':'course','quantity':1,'language':'en','objections':[{'type':'price','text':'too expensive','span':[3,16]}]}
        classification=Classification.model_validate(raw)
        classification.validate_message('is too expensive')
        with self.assertRaises(ValueError): classification.validate_message('different buyer message')


class GenerationTests(unittest.IsolatedAsyncioTestCase):
    async def test_buyer_quote_offsets_are_computed_by_code(self):
        from services.sleyz.pipeline import classify_message
        raw={'intent_score':.5,'product_query':'course','language':'en','objections':[{'type':'price','text':'too expensive'}]}
        result=await classify_message({'text':'course is too expensive'},model=AsyncMock(return_value=raw))
        self.assertEqual(result.objections[0].span,(10,23))

    async def test_selected_exact_quote_gets_server_computed_citation_offsets(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.5,'product_query':'','language':'en','objections':[]},
            {'citations':[{'source_id':'s1','revision':1,'quote':'Two coaching sessions.'}],'acknowledgement':'thanks','next_step':'needs'}])
        result=await generate_artifact({'org_id':'a','platform':'telegram','customer_handle':'buyer','text':'What is included?'},
            {'identity':{},'products':[],'knowledge':[{'source_id':'s1','revision':1,'kind':'faq','content':'Two coaching sessions.'}]},model=model)
        self.assertEqual(result['cited_brand_passport_atoms'][0]['span'],[0,22])

    async def test_selection_can_honor_brand_commercial_disclosure_constraints(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.5,'product_query':'course/one','language':'en'},
            {'citations':[],'acknowledgement':'thanks','next_step':'needs','include_price':False,'include_stock':False,'include_description':False}])
        result=await generate_artifact({'org_id':'a','platform':'telegram','customer_handle':'buyer','text':'course/one?'},
            {'identity':{'exports':{'negative_constraints.md':'Never disclose prices or inventory counts.'}},'products':[product()],'knowledge':[]},model=model)
        self.assertNotIn('100.00',result['draft_reply'])
        self.assertNotIn('stock',result['draft_reply'])

    async def test_approved_formatting_rule_changes_next_reply_and_is_cited(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.5,'product_query':'course/one','language':'en'},
            {'citations':[],'acknowledgement':'thanks','next_step':'needs'}])
        rule={'source_id':'rule1','revision':2,'kind':'correction','content':'Use short paragraphs.','atoms':[]}
        result=await generate_artifact({'org_id':'a','platform':'telegram','customer_handle':'buyer','text':'course/one?'},
            {'identity':{},'products':[product()],'knowledge':[rule]},model=model)
        self.assertIn('\n\n',result['draft_reply'])
        self.assertEqual(result['cited_brand_passport_atoms'][0]['source_id'],'rule1')

    async def test_hot_reply_uses_verified_price_and_link_only(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.9,'product_query':'course/one','quantity':2,'language':'en','objections':[]},
                                    {'citations':[],'acknowledgement':'thanks','next_step':'buy'}])
        envelope={'customer_handle':'@buyer','platform':'telegram','text':'I want two course/one','org_id':'a'}
        artifact=await generate_artifact(envelope, {'identity':{'exports':{}},'knowledge':[],'products':[product()]}, model=model)
        self.assertEqual(artifact['intent'],'HOT')
        self.assertIn('100.00 USD',artifact['draft_reply'])
        self.assertIn('quantity=2',artifact['checkout_link'])
        self.assertEqual(artifact['quantity'],2)

    async def test_ambiguous_hot_inquiry_never_creates_link(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.95,'product_query':'course','quantity':1,'language':'en','objections':[]},
                                    {'citations':[],'acknowledgement':'thanks','next_step':'buy'}])
        result=await generate_artifact({'org_id':'a','platform':'instagram','customer_handle':'id:1','text':'buy course'},
            {'identity':{},'knowledge':[],'products':[product(),product(id='p2',sku='course/two',name='Second course')]},model=model)
        self.assertIsNone(result['checkout_link'])
        self.assertIn('Which product',result['draft_reply'])

    async def test_fabricated_citation_prevents_ready_artifact(self):
        from services.sleyz.pipeline import generate_artifact
        model=AsyncMock(side_effect=[{'intent_score':.2,'product_query':'','quantity':1,'language':'en','objections':[]},
                                    {'citations':[{'source_id':'fake','revision':1,'span':[0,3]}],'acknowledgement':'thanks','next_step':'needs'}])
        with self.assertRaises(ValueError):
            await generate_artifact({'org_id':'a','platform':'telegram','customer_handle':'id:1','text':'hello'}, {'identity':{},'knowledge':[],'products':[]},model=model)
