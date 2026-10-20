"""Evaluator boundary gates on synthetic annotations, not recorded speech."""
import unittest
from scripts.evaluate_vea_alignment import boundary_metrics


class EvaluationTests(unittest.TestCase):
    def test_exactly_95_percent_including_200ms_boundary_is_accepted(self):
        reference = [{'word': str(i), 'start_ms': i*300, 'end_ms': i*300+200} for i in range(10)]
        actual = [dict(w) for w in reference]
        actual[0]['start_ms'] += 200
        actual[1]['start_ms'] += 201
        result = boundary_metrics(actual, reference)
        self.assertEqual(result['within_200ms_fraction'], .95)
        self.assertTrue(result['passed'])
        actual[2]['start_ms'] += 201
        self.assertFalse(boundary_metrics(actual, reference)['passed'])

    def test_reference_cannot_hide_omitted_approved_tokens(self):
        with self.assertRaises(ValueError): boundary_metrics([], [{'word': 'approved', 'start_ms': 0, 'end_ms': 500}])


if __name__ == '__main__': unittest.main()
