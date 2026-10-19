import unittest
from unittest.mock import AsyncMock

from services.memory import rank_sources


class CorrectionRankingTests(unittest.TestCase):
    def test_correction_has_two_times_base_score_and_cannot_cross_org(self):
        from datetime import datetime, timezone
        now=datetime.now(timezone.utc)
        base={'org_id':'a','kind':'manual','title':'price concern','content':'acknowledge price concern',
              'updated_at':now.isoformat(),'revision':1,'indexed_revision':1,'atoms':[]}
        result=rank_sources([{**base,'id':'normal'},{**base,'id':'correction','kind':'correction','metadata':{'priority':2}},
                             {**base,'id':'other','org_id':'b','kind':'correction'}], 'price',org_id='a',now=now)
        self.assertEqual([r['source_id'] for r in result],['correction','normal'])
        self.assertAlmostEqual(result[0]['score'],2*result[1]['score'])


class LearningTests(unittest.IsolatedAsyncioTestCase):
    def job(self):
        return {'draft_id':'d1','approved_revision':4,'approved_at':'2026-10-19T00:00:00Z',
                'original':'Buy now.','final':'I understand your concern. What is your main goal?'}

    async def test_general_rule_requires_changed_exact_support(self):
        from services.sleyz.learning import analyze_edit
        model=AsyncMock(return_value={'rule':'Acknowledge buyer concerns before asking a question.', 'rule_type':'objection_handling',
            'scope':'general','supporting_spans':[{'text':'I understand your concern.','start':0,'end':26}]})
        result=await analyze_edit(self.job(),model=model)
        self.assertEqual(result['draft_id'],'d1')
        self.assertEqual(result['approved_revision'],4)

    async def test_support_offsets_are_computed_from_exact_approved_quote(self):
        from services.sleyz.learning import analyze_edit
        model=AsyncMock(return_value={'rule':'Acknowledge buyer concerns before asking a question.', 'rule_type':'objection_handling',
            'scope':'general','supporting_spans':[{'text':'I understand your concern.'}]})
        result=await analyze_edit(self.job(),model=model)
        self.assertEqual(result['supporting_spans'][0]['start'],0)
        self.assertEqual(result['supporting_spans'][0]['end'],26)

    async def test_customer_exception_and_commercial_promise_are_not_learned(self):
        from services.sleyz.learning import analyze_edit
        for rule,scope in [('Give a 50% discount.','general'),('Promise guaranteed results.','general'),('Mention buyer name Alex.','customer_specific')]:
            model=AsyncMock(return_value={'rule':rule,'rule_type':'style','scope':scope,
                'supporting_spans':[{'text':'I understand your concern.','start':0,'end':26}]})
            self.assertIsNone(await analyze_edit(self.job(),model=model))

    async def test_commercial_synonyms_cannot_become_style_rules(self):
        from services.sleyz.learning import analyze_edit
        final='We include complimentary freight.'
        model=AsyncMock(return_value={'rule':'Always offer complimentary freight.','rule_type':'style','scope':'general',
            'supporting_spans':[{'text':final,'start':0,'end':len(final)}]})
        self.assertIsNone(await analyze_edit({**self.job(),'final':final},model=model))

    async def test_commercial_edit_cannot_be_relabelled_as_a_safe_behavior(self):
        from services.sleyz.learning import analyze_edit
        final='We include complimentary freight for Alex.'
        model=AsyncMock(return_value={'rule':'Use a warm and direct tone.','rule_type':'style','scope':'general',
            'supporting_spans':[{'text':final}]})
        self.assertIsNone(await analyze_edit({**self.job(),'final':final},model=model))

    async def test_unchanged_approval_does_not_call_model(self):
        from services.sleyz.learning import analyze_edit
        job={**self.job(),'original':'Same','final':'Same'}
        model=AsyncMock()
        self.assertIsNone(await analyze_edit(job,model=model))
        model.assert_not_awaited()

    async def test_fabricated_support_is_rejected(self):
        from services.sleyz.learning import analyze_edit
        model=AsyncMock(return_value={'rule':'Ask one question.','rule_type':'style','scope':'general',
            'supporting_spans':[{'text':'made up','start':0,'end':7}]})
        with self.assertRaises(ValueError): await analyze_edit(self.job(),model=model)
