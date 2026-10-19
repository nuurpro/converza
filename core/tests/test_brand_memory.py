import unittest
from datetime import datetime, timedelta, timezone
from services.memory import render_identity, rank_sources, redact_stale_prices


class BrandMemoryTests(unittest.TestCase):
    def test_identity_rejects_oversized_rules_and_retains_palette(self):
        with self.assertRaisesRegex(ValueError, 'negative_constraints.md exceeds'):
            render_identity({'negative_constraints': 'Never fabricate. ' * 300 + 'FINAL SAFETY RULE'})
        documents=render_identity({'hex_colors':['#112233','#ffffff'],'negative_constraints':'Final rule must remain.'})
        self.assertIn('#112233',documents['brand_passport.md'])
        self.assertIn('Final rule must remain.',documents['negative_constraints.md'])

    def test_identity_exports_deterministic_and_catalog_excluded(self):
        passport = {'brand_name': 'Nova', 'tone': 'Warm', 'target_audience': 'Founders', 'price': 100, 'voice_rules': ['Be direct'], 'negative_constraints': ['No fake promises']}
        docs = render_identity(passport)
        self.assertEqual(set(docs), {'brand_passport.md', 'voice_rules.md', 'negative_constraints.md'})
        self.assertEqual(docs, render_identity(dict(reversed(list(passport.items())))))
        self.assertNotIn('100', ''.join(docs.values()))
        self.assertIn('No fake promises', docs['negative_constraints.md'])

    def test_unicode_small_corpus_no_zero_or_negative_relevance(self):
        now = datetime.now(timezone.utc)
        rows = [{'id': 'a', 'org_id': 'one', 'kind': 'faq', 'title': 'CAFÉ', 'content': 'Café returns', 'updated_at': now.isoformat(), 'revision': 1}]
        result = rank_sources(rows, 'cafe\u0301', org_id='one', now=now)
        self.assertEqual(result[0]['source_id'], 'a')
        self.assertGreater(result[0]['score'], 0)
        self.assertEqual(rank_sources(rows, 'missing', org_id='one'), [])
        self.assertEqual(rank_sources(rows, 'café', org_id='two'), [])

    def test_recency_uses_source_timestamp_and_excludes_deleted_obsolete(self):
        now = datetime.now(timezone.utc)
        def row(i, age, **kw):
            return {'id': i, 'org_id': 'a', 'kind': 'faq', 'title': 'delivery', 'content': 'delivery details', 'updated_at': (now-timedelta(days=age)).isoformat(), 'revision': 2, **kw}
        rows = [row('old', 30), row('new', 0), row('gone', 0, deleted_at=now.isoformat()), row('pending', 0, summary='obsolete wording', indexed_revision=1)]
        result = rank_sources(rows, 'delivery', org_id='a', now=now)
        self.assertNotIn('gone', [r['source_id'] for r in result])
        scores = {r['source_id']: r['score'] for r in result}
        self.assertAlmostEqual(scores['old']/scores['new'], .625)
        self.assertEqual(next(r for r in result if r['source_id']=='pending')['summary'], '')

    def test_stale_pricing_is_redacted_while_live_price_remains(self):
        rows = [{'price': '100.00', 'currency': 'USD'}]
        current = [{'price': '120.00', 'currency': 'USD'}]
        self.assertEqual(redact_stale_prices('Costs $100 or 100 USD; now $120.', rows, current), 'Costs [superseded price] or [superseded price]; now $120.')

    def test_top_eight_and_context_budget(self):
        rows = [{'id': str(i), 'org_id': 'a', 'kind': 'manual', 'title': 'delivery', 'content': 'delivery '*100, 'revision': 1} for i in range(12)]
        results = rank_sources(rows, 'delivery', org_id='a', budget_chars=500)
        self.assertLessEqual(len(results), 8)
        self.assertLessEqual(sum(len(x['content'])+len(x['summary'])+len(str(x['atoms'])) for x in results), 500)



class MemoryStoreContractTests(unittest.TestCase):
    def test_large_catalog_is_retrieved_instead_of_dumped_into_every_prompt(self):
        from services.memory import MemoryStore
        class Store(MemoryStore):
            def __init__(self): pass
            def identity(self,org): return {'passport':{},'exports':{}}
            def search(self,org,query): return []
            def products(self,org): return [{'id':str(i),'name':f'Course{i}','description':'x'*10000,'price':i,'currency':'USD'} for i in range(1000)]
        context=Store().context('a','Course42')
        self.assertEqual([row['name'] for row in context['products']],['Course42'])
        self.assertNotIn('description',context['products'][0])

    def test_all_pages_collected_and_tenant_filter_applied_every_page(self):
        from services.memory import MemoryStore
        calls=[]
        class Query:
            def select(self,*a): return self
            def eq(self,key,value): calls.append((key,value)); return self
            def order(self,*a): return self
            def range(self,start,end): self.start=start; return self
            def execute(self):
                class Response: pass
                response=Response(); response.data=[{'id':str(i)} for i in range(self.start,min(self.start+1000,1003))]; return response
        class Client:
            def table(self,name): return Query()
        rows=MemoryStore(Client())._rows('memory_sources','tenant')
        self.assertEqual(len(rows),1003)
        self.assertEqual(calls,[('org_id','tenant'),('org_id','tenant')])

    def test_pending_raw_facts_searchable_and_changed_revision_immediately_invalidates_summary(self):
        from services.memory import MemoryStore
        class Store(MemoryStore):
            def __init__(self): self.rows=[{'id':'s','kind':'manual','org_id':'a','revision':1,'indexed_revision':1,'content':'Shipping next day','summary':'priority dispatch','atoms':[]}]
            def _rows(self,table,org): return [dict(r) for r in self.rows] if table=='memory_sources' else []
            def products(self,org): return []
        store=Store()
        self.assertEqual(len(store.search('a','priority')),1)
        store.rows[0].update(revision=2,content='Shipping two days')
        self.assertEqual(store.search('a','priority'),[])
        self.assertIn('two days',store.search('a','shipping')[0]['content'])
        store.rows[0]['deleted_at']='2026-01-01'
        self.assertEqual(store.search('a','shipping'),[])

    def test_redaction_never_changes_atom_revision_or_spans(self):
        from services.memory import MemoryStore
        class Store(MemoryStore):
            def __init__(self): pass
            def products(self,org): return [{'id':'p','price':120,'currency':'USD'}]
            def _rows(self,table,org):
                if table=='memory_price_history': return [{'price':100,'currency':'USD'}]
                return [{'id':'s','org_id':'a','kind':'objection','revision':100,'indexed_revision':100,'content':'Costs $100','summary':'Costs $100','atoms':[{'kind':'objection','source_revision':100,'answer':'Costs $100','answer_span':[0,100]}]}]
        result=Store().search('a','costs')[0]
        self.assertEqual(result['atoms'][0]['source_revision'],100)
        self.assertEqual(result['atoms'][0]['answer_span'],[0,100])
        self.assertEqual(result['atoms'][0]['answer'],'Costs [superseded price]')

class CurrentCatalogTests(unittest.TestCase):
    def test_live_catalog_replaces_product_text_even_during_source_read_race(self):
        from services.memory import MemoryStore
        class Store(MemoryStore):
            def __init__(self): pass
            def products(self,org): return [{'id':'p','name':'Course','description':'Training','price':120,'currency':'USD'}]
            def _rows(self,table,org):
                if table=='memory_price_history': return [{'price':100,'currency':'USD'},{'price':120,'currency':'USD'}]
                return [{'id':'s','external_id':'p','org_id':'a','kind':'product','revision':1,'content':'Course $100','indexed_revision':1,'summary':'Course $100','atoms':[]}]
        result=Store().search('a','Course')[0]
        self.assertIn('120 USD',result['content'])
        self.assertNotIn('100',str(result))

class ProductValidationTests(unittest.TestCase):
    def test_rejects_invalid_negative_nan_or_infinite_price(self):
        from services.memory import MemoryStore
        for price in ('free',-1,'NaN','Infinity'):
            with self.assertRaises(ValueError): MemoryStore._validate_product({'price':price})
        for price in (0,'120.50',None): MemoryStore._validate_product({'price':price})
        with self.assertRaises(ValueError): MemoryStore._validate_product({'currency':'usd'})


if __name__ == '__main__': unittest.main()

class LegacyPassportTests(unittest.TestCase):
    def test_legacy_pricing_current_context_and_search_replaces_stale_source(self):
        from services.memory import MemoryStore
        class Store(MemoryStore):
            def __init__(self): pass
            def products(self,org): return []
            def identity(self,org): return {'passport':{'id':'p','pricing':[{'tier':'Starter','price':'$120/mo','features':['Coaching']}],'faq':[]},'exports':{}}
            def _rows(self,table,org):
                if table=='memory_price_history': return [{'price':100,'currency':'LEGACY'},{'price':120,'currency':'LEGACY'}]
                return [{'id':'s','external_id':'passport:p:pricing','org_id':'a','kind':'manual','revision':2,'indexed_revision':2,'content':'pricing\n[{"tier":"Starter","price":"$100/mo"}]','summary':'Old100 price','atoms':[],'metadata':{'origin':'passport','passport_id':'p','source_field':'pricing'}}]
        store=Store(); result=store.search('a','Starter')[0]
        self.assertIn('$120/mo',result['content']); self.assertNotIn('100',str(result))
        self.assertEqual(store.context('a','Starter')['products'][0]['price'],'$120/mo')
