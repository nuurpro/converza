"""Free retrieval fixtures: budgets must never turn conditional offers into promises."""
import json
import unittest

from services.memory import rank_sources, source_claim_spans
from services.sleyz.tools import validate_citations


def row(content, **values):
    return {**dict(id='fact', org_id='org', kind='manual', title='Festival', content=content,
                   revision=1, indexed_revision=1, atoms=[]), **values}


class ClaimUnitTests(unittest.TestCase):
    def test_offline_claim_evaluations(self):
        from services.memory.evals.run import evaluate
        report = evaluate()
        self.assertEqual(report['passed'], report['total'])
        self.assertEqual(report['score'], 1.0)

    def test_decorated_english_and_uzbek_qualifications_remain_in_one_claim(self):
        for prefix in ('Only if', 'Unless', 'Faqat', 'Agar', '- Only if', '* Faqat',
                       '**Only if**', '> Agar', '1. Unless'):
            text = 'Festival entry is free.\n\n' + prefix + ' registration is approved.'
            with self.subTest(prefix=prefix):
                self.assertEqual(source_claim_spans(text), [[0, len(text)]])

    def test_oversized_qualified_claim_never_fits_by_dropping_its_tail(self):
        for prefix in ('- faqat', '**Only if**', '> Unless'):
            text = 'Festival funding is available.\n' + prefix + ' approved ' * 90 + '.'
            rows = rank_sources([row(text, summary=text)], 'Festival', org_id='org', budget_chars=550)
            for result in rows:
                self.assertEqual(result['content'], '')
                self.assertEqual(result['summary'], '')
                self.assertEqual(result['citation_spans'], [])

    def test_partial_atom_cannot_reintroduce_a_qualified_claim_under_budget(self):
        claim = 'Festival entry is free.'
        content = claim + '\nOnly if ' + 'registration approved ' * 80 + '.'
        result = rank_sources([row(content, atoms=[{'kind': 'fact', 'text': claim,
            'span': [0, len(claim)], 'source_revision': 1}])], 'Festival', org_id='org', budget_chars=800)
        self.assertTrue(result)
        self.assertNotIn(claim, json.dumps(result))
        with self.assertRaises(ValueError):
            validate_citations([{'source_id': 'fact', 'revision': 1, 'atom_index': 0}], result)

    def test_summary_cannot_reintroduce_an_unqualified_prefix(self):
        claim = 'Festival funding is available.'
        content = claim + '\nOnly if the grant committee approves the application.'
        result = rank_sources([row(content, summary=claim)], 'Festival', org_id='org')
        self.assertEqual(result[0]['summary'], '')

    def test_search_summary_stays_searchable_but_not_authoritative_when_paraphrased(self):
        result = rank_sources([row('Festival entry requires approval.', summary='Free festival tickets.')],
            'tickets', org_id='org')
        self.assertTrue(result)
        self.assertEqual(result[0]['content'], 'Festival entry requires approval.')
        self.assertEqual(result[0]['summary'], '')

    def test_omitted_source_claim_does_not_return_atom_quote_or_citation(self):
        text = 'Festival entry is free. Only if ' + 'approved ' * 65 + '.'
        result = rank_sources([row(text, atoms=[{'kind': 'fact', 'text': text,
            'span': [0, len(text)], 'source_revision': 1}])], 'Festival', org_id='org', budget_chars=800)
        for item in result:
            if not item['content']:
                self.assertFalse(item['citation_spans'])
                self.assertFalse(any(atom.get('text') for atom in item['atoms']))

    def test_later_qualified_sentence_keeps_exact_original_offsets(self):
        first = 'Festival opens Friday.'
        qualified = ' Grants are available.\n- Faqat approved applicants qualify.'
        content = first + qualified
        result = rank_sources([row(content)], 'Festival', org_id='org', budget_chars=2000)
        start = len(first) + 1
        validate_citations([{'source_id': 'fact', 'revision': 1, 'span': [start, len(content)]}], result)
        with self.assertRaises(ValueError):
            validate_citations([{'source_id': 'fact', 'revision': 1,
                'span': [start, content.index('\n')]}], result)


if __name__ == '__main__':
    unittest.main()
