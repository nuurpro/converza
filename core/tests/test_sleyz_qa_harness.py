"""The browser harness must remain local and deterministic."""
import unittest

from qa_harness import validate_qa_dsn, qa_sleyz_model
from services.sleyz.contracts import Classification, ReplySelection


class HarnessSafetyTests(unittest.TestCase):
    def test_only_named_disposable_loopback_databases_are_accepted(self):
        validate_qa_dsn('host=127.0.0.1 port=15441 user=postgres dbname=test_converza_sleyz_ui')
        for dsn in ('host=prod.example dbname=test_converza_qa', 'host=127.0.0.1 dbname=converza', 'dbname=test_converza_qa', 'host=localhost hostaddr=203.0.113.1 dbname=test_converza_qa'):
            with self.subTest(dsn=dsn), self.assertRaises(ValueError):
                validate_qa_dsn(dsn)


class HarnessInferenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixture_uses_validated_sales_contracts(self):
        classification=Classification.model_validate(await qa_sleyz_model([],schema=Classification.model_json_schema()))
        self.assertEqual(classification.product_query,'founder-course')
        self.assertEqual(classification.intent_score,.9)
        selection=ReplySelection.model_validate(await qa_sleyz_model([],schema=ReplySelection.model_json_schema()))
        self.assertEqual(selection.next_step,'buy')
        self.assertTrue(selection.include_price)
        self.assertTrue(selection.include_stock)
