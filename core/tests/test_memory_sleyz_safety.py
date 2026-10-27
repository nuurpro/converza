"""Offline regressions for the retrieval-to-reply safety boundary."""
import copy
import json
import unittest
from unittest.mock import AsyncMock

from services.memory import MemoryStore, rank_sources, redact_stale_prices
from services.sleyz.contracts import Classification
from services.sleyz.pipeline import generate_artifact
from services.sleyz.tools import citation_text, validate_citations


def source(content, **values):
    return {'id': 's', 'org_id': 'a', 'kind': 'manual', 'title': 'Coat',
            'content': content, 'revision': 1, 'indexed_revision': 1,
            'atoms': [], **values}


class RetrievalSafetyTests(unittest.TestCase):
    def test_price_redaction_accepts_sentence_punctuation_not_decimal_prefixes(self):
        history = [{'product_id': 'coat', 'price': '100.00', 'currency': 'USD'}]
        current = [{'id': 'coat', 'price': 120, 'currency': 'USD'}]
        for quote in ('$100.', '100.00 USD.', '$100,', '100 USD!'):
            with self.subTest(quote=quote):
                self.assertNotIn('100', redact_stale_prices(quote, history, current))
        for quote in ('$100.25', '$1100', '$1000'):
            self.assertEqual(redact_stale_prices(quote, history, current), quote)

    def test_qualifier_after_newline_or_sentence_is_atomic(self):
        for join in (', except ', '\nexcept ', '. However, ', ',\n',
                     '. Biroq, ', '. \u041e\u0434\u043d\u0430\u043a\u043e, '):
            text = 'Coat is waterproof' + join + 'submerged ' * 100 + '.'
            with self.subTest(join=join):
                rows = rank_sources([source(text)], 'Coat', org_id='a', budget_chars=500)
                self.assertTrue(all(not row['content'] for row in rows))

    def test_abbreviation_cannot_make_its_qualified_tail_optional(self):
        for prefix in ('Coat works in the U.S. Except when ',
                       'Coat meets U.S. standards, unless ',
                       'Coat meets U.S. Standards Organization rules, unless '):
            text = prefix + 'submerged ' * 100 + '.'
            with self.subTest(prefix=prefix):
                rows = rank_sources([source(text)], 'Coat', org_id='a', budget_chars=500)
                self.assertTrue(all(not row['content'] for row in rows))

    def test_cutoff_cannot_turn_qualified_claim_into_complete_evidence(self):
        claim = 'Coat is waterproof, except when ' + 'submerged ' * 90 + '.'
        rows = rank_sources([source(claim)], 'Coat', org_id='a', budget_chars=500)
        for row in rows:
            self.assertIn(row['content'], ('', claim))
            if row['content'] != claim:
                with self.assertRaises(ValueError):
                    validate_citations([{'source_id': 's', 'revision': 1,
                                         'span': [0, len(row['content'])]}], [row])

    def test_complete_earlier_sentence_keeps_original_span(self):
        claim = 'Coat is washable.'
        original = claim + ' Another claim, unless ' + 'qualified ' * 100 + '.'
        rows = rank_sources([source(original)], 'Coat', org_id='a', budget_chars=500)
        self.assertEqual(rows[0]['content'], claim)
        ref = {'source_id': 's', 'revision': 1, 'span': [0, len(claim)]}
        validate_citations([ref], rows)
        self.assertEqual(citation_text(ref, rows), original[:len(claim)])

    def test_entire_serialized_projection_obeys_budget(self):
        row = source('Coat is washable.', metadata={
            'final_content': 'Costs $100. ' * 4000,
            'original_content': 'PRIVATE BUYER TEXT ' * 4000,
            'nested': {'raw_reply': 'secret'}, 'status': 'PUBLISHED',
            'resolved_at': '2026-10-19T00:00:00Z',
            'delivered_at': '2026-10-19T00:00:00Z'},
            atoms=[{'kind': 'fact', 'text': 'Coat is washable.',
                    'span': [0, 17], 'raw_reply': 'PRIVATE ATOM'}])
        original = copy.deepcopy(row)
        result = rank_sources([row], 'Coat', org_id='a', budget_chars=900)
        self.assertTrue(result)
        rendered = json.dumps(result, ensure_ascii=False, default=str)
        self.assertLessEqual(len(rendered), 900)
        for forbidden in ('final_content', 'original_content', 'raw_reply', 'PRIVATE', '$100'):
            self.assertNotIn(forbidden, rendered)
        self.assertEqual(row, original)

    def test_current_price_on_another_product_cannot_resurrect_old_price(self):
        history = [{'product_id': 'coat', 'price': 100, 'currency': 'USD'}]
        products = [{'id': 'coat', 'price': 120, 'currency': 'USD'},
                    {'id': 'hat', 'price': 100, 'currency': 'USD'}]
        self.assertNotIn('100', redact_stale_prices('Coat costs $100.', history, products))
        self.assertEqual(redact_stale_prices('Coat costs $100.', history,
                                           [{'id': 'coat', 'price': 100, 'currency': 'USD'}]),
                         'Coat costs $100.')

    def test_redacted_sentence_is_not_citeable_and_later_span_is_original(self):
        original = 'Coat costs $100. Coat is washable.'
        class Store(MemoryStore):
            def __init__(self):
                self.rows = [source(original, atoms=[{'kind': 'fact', 'text': original[:16],
                                                     'span': [0, 16], 'source_revision': 1}])]
            def products(self, org):
                return [{'id': 'coat', 'price': 120, 'currency': 'USD'}]
            def _rows(self, table, org):
                if table == 'memory_price_history':
                    return [{'product_id': 'coat', 'price': 100, 'currency': 'USD'}]
                return self.rows
        store = Store()
        before = copy.deepcopy(store.rows)
        rows = store.search('a', 'Coat')
        start = original.index('Coat is washable.')
        ref = {'source_id': 's', 'revision': 1, 'span': [start, len(original)]}
        validate_citations([ref], rows)
        self.assertEqual(citation_text(ref, rows), original[start:])
        with self.assertRaises(ValueError):
            validate_citations([{'source_id': 's', 'revision': 1, 'atom_index': 0}], rows)
        self.assertEqual(store.rows, before)

    def test_identical_text_at_partial_span_does_not_borrow_other_sentence_boundary(self):
        text = 'Washable. Not Washable.'
        row = {'source_id': 's', 'revision': 1, 'content': text}
        start = text.rindex('Washable.')
        with self.assertRaises(ValueError):
            validate_citations([{'source_id': 's', 'revision': 1,
                                 'span': [start, len(text)]}], [row])

    def test_atom_with_wrong_original_span_or_redaction_flag_is_rejected(self):
        text = 'Coat is washable.'
        for atom in ({'text': text, 'span': [1, len(text)]},
                     {'text': text, 'span': [0, len(text)], 'quote_redacted': True},
                     {'text': text, 'span': [0, len(text)], 'source_revision': 2}):
            row = {'source_id': 's', 'revision': 1, 'content': text, 'atoms': [atom]}
            with self.subTest(atom=atom), self.assertRaises(ValueError):
                validate_citations([{'source_id': 's', 'revision': 1, 'atom_index': 0}], [row])


class CorrectionReportingTests(unittest.IsolatedAsyncioTestCase):
    async def test_quote_selection_cannot_rewrite_a_wrong_revision_into_current_revision(self):
        model = AsyncMock(return_value={'citations': [{'source_id': 's', 'revision': 2,
                                                      'quote': 'Coat is washable.'}]})
        with self.assertRaisesRegex(ValueError, 'revision'):
            await generate_artifact(
                {'org_id': 'a', 'platform': 'telegram', 'customer_handle': 'buyer', 'text': 'coat'},
                {'products': [], 'knowledge': [{'source_id': 's', 'kind': 'manual', 'revision': 1,
                                               'content': 'Coat is washable.'}]}, model=model,
                classification=Classification(intent_score=.5))

    async def render(self, rules, quotes=(), **selection):
        knowledge = [{'source_id': f'r{i}', 'kind': 'correction', 'revision': 1,
                      'content': rule} for i, rule in enumerate(rules)]
        knowledge += [{'source_id': f'q{i}', 'kind': 'manual', 'revision': 1,
                       'content': text} for i, text in enumerate(quotes)]
        model = AsyncMock(return_value={
            'citations': [{'source_id': f'q{i}', 'revision': 1, 'quote': text}
                          for i, text in enumerate(quotes)],
            'acknowledgement': 'none', **selection})
        return await generate_artifact(
            {'org_id': 'a', 'platform': 'telegram', 'customer_handle': 'buyer', 'text': 'coat'},
            {'products': [], 'knowledge': knowledge}, model=model,
            classification=Classification(intent_score=.5, language='en'))

    async def test_noop_and_unimplemented_rules_are_not_claimed_as_applied(self):
        for rule in ('Keep replies concise.', 'Use bullet points for multiple benefits.',
                     'Avoid pressuring the buyer.', 'Reply in the customer\u2019s language.'):
            with self.subTest(rule=rule):
                result = await self.render([rule])
                self.assertEqual(result['cited_brand_passport_atoms'], [])

    async def test_concision_removes_citation_for_omitted_optional_quote(self):
        long_quote = 'Coat ' + 'stays washable ' * 16 + 'unless treated with solvents.'
        short_quote = 'Coat is soft.'
        result = await self.render(['Keep replies concise.'], [long_quote, short_quote])
        self.assertNotIn(long_quote, result['draft_reply'])
        self.assertIn(short_quote, result['draft_reply'])
        self.assertEqual({r['source_id'] for r in result['cited_brand_passport_atoms']},
                         {'r0', 'q1'})

    async def test_bullet_rule_not_applied_after_all_benefits_are_omitted(self):
        quotes = ['Coat ' + word * 35 + 'unless treated.' for word in ('soft ', 'warm ')]
        result = await self.render(['Keep replies concise.', 'Use bullet points for multiple benefits.'], quotes)
        self.assertEqual([r['source_id'] for r in result['cited_brand_passport_atoms']], ['r0'])

    async def test_paragraph_rule_is_not_cited_when_concision_leaves_one_part(self):
        quotes = ['Coat ' + 'soft ' * 35 + 'unless treated.']
        result = await self.render(['Use short paragraphs.', 'Keep replies concise.'], quotes)
        self.assertEqual([r['source_id'] for r in result['cited_brand_passport_atoms']], ['r1'])

    async def test_quote_selection_uses_original_offsets_after_price_redaction(self):
        original = 'Coat costs $100. Coat is washable.'
        class Store(MemoryStore):
            def __init__(self): pass
            def products(self, org): return [{'id': 'coat', 'price': 120, 'currency': 'USD'}]
            def _rows(self, table, org):
                return ([{'product_id': 'coat', 'price': 100, 'currency': 'USD'}]
                        if table == 'memory_price_history' else [source(original)])
        rows = Store().search('a', 'Coat')
        model = AsyncMock(return_value={'citations': [{'source_id': 's', 'revision': 1,
                                                      'quote': 'Coat is washable.'}]})
        result = await generate_artifact(
            {'org_id': 'a', 'platform': 'telegram', 'customer_handle': 'buyer', 'text': 'coat'},
            {'products': [], 'knowledge': rows}, model=model,
            classification=Classification(intent_score=.5))
        ref = result['cited_brand_passport_atoms'][0]
        self.assertEqual(ref['span'], [original.index('Coat is washable.'), len(original)])
        self.assertEqual(original[slice(*ref['span'])], 'Coat is washable.')

    async def test_concision_never_omits_required_commerce_or_checkout_parts(self):
        name = 'Coat ' + 'special ' * 32
        product = {'id': 'coat', 'org_id': 'a', 'name': name, 'sku': 'coat',
                   'price': '120', 'currency': 'USD', 'stock_count': 2,
                   'checkout_url_template': 'https://shop.example/{sku}?quantity={quantity}'}
        rule = {'source_id': 'r0', 'kind': 'correction', 'revision': 1,
                'content': 'Keep replies concise.'}
        result = await generate_artifact(
            {'org_id': 'a', 'platform': 'telegram', 'customer_handle': 'buyer', 'text': 'buy coat'},
            {'products': [product], 'knowledge': [rule]},
            model=AsyncMock(return_value={'citations': []}),
            classification=Classification(intent_score=.9, product_query='coat'))
        self.assertIn(name + ': 120 USD.', result['draft_reply'])
        self.assertIn(result['checkout_link'], result['draft_reply'])
        self.assertEqual(result['cited_brand_passport_atoms'], [])


class LearningSafetyTests(unittest.IsolatedAsyncioTestCase):
    async def test_commercial_qualifier_change_cannot_hide_behind_separate_style_support(self):
        from services.sleyz.learning import analyze_edit
        model = AsyncMock(return_value={'rule': 'Use a warm and direct tone.', 'rule_type': 'style',
                                       'scope': 'general', 'supporting_spans': [{'text': 'Thanks.'}]})
        result = await analyze_edit({'draft_id': 'd', 'original': 'We do not offer free shipping. Hello.',
                                     'final': 'We offer free shipping. Thanks.'}, model=model)
        self.assertIsNone(result)
        model.assert_not_awaited()

    async def test_removal_of_commercial_promise_is_not_a_general_style_lesson(self):
        from services.sleyz.learning import analyze_edit
        final = 'Thanks for asking.'
        model = AsyncMock(return_value={'rule': 'Keep replies concise.', 'rule_type': 'style',
                                       'scope': 'general', 'supporting_spans': [{'text': final}]})
        result = await analyze_edit({'draft_id': 'd', 'original': 'Complimentary freight included.',
                                     'final': final}, model=model)
        self.assertIsNone(result)
        model.assert_not_awaited()

    async def test_repeated_support_selects_changed_occurrence_not_unchanged_prefix(self):
        from services.sleyz.learning import analyze_edit
        final = 'Thanks. Thanks.'
        model = AsyncMock(return_value={'rule': 'Use a warm and direct tone.', 'rule_type': 'style',
                                       'scope': 'general', 'supporting_spans': [{'text': 'Thanks.'}]})
        result = await analyze_edit({'draft_id': 'd', 'original': 'Thanks. Go now.', 'final': final}, model=model)
        self.assertEqual(result['supporting_spans'], [{'text': 'Thanks.', 'start': 8, 'end': 15}])


if __name__ == '__main__':
    unittest.main()
