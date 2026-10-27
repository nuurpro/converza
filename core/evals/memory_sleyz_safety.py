"""Offline safety matrix: python evals/memory_sleyz_safety.py. No DB or live inference."""
import asyncio
import copy
import itertools
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.memory import MemoryStore, rank_sources, redact_stale_prices
from services.sleyz.contracts import Classification
from services.sleyz.learning import analyze_edit
from services.sleyz.pipeline import generate_artifact
from services.sleyz.tools import citation_text, validate_citations


def row(content, **values):
    return {'id': 'source', 'org_id': 'eval', 'kind': 'manual', 'title': 'Coat',
            'revision': 1, 'indexed_revision': 1, 'content': content, 'atoms': [], **values}


async def evaluate():
    counts = {'cutoff_budget_provenance': 0, 'price_identity': 0,
              'redaction_provenance': 0, 'correction_reporting': 0, 'learning': 0}
    for qualifier in (', except when ', ', unless ', '. However, ', ',\nexcept when ',
                      ' meets U.S. standards, unless ', '. Biroq, ',
                      '. \u041e\u0434\u043d\u0430\u043a\u043e, '):
        first = 'Coat is washable.'
        qualified = 'Coat is waterproof' + qualifier + 'submerged ' * 80 + '.'
        original = first + ' ' + qualified
        fixture = row(original, metadata={'final_content': 'PRIVATE $100 ' * 1000,
                                          'snapshot': {'reply': 'PRIVATE'}})
        before = copy.deepcopy(fixture)
        for budget in range(200, 1801, 37):
            result = rank_sources([fixture], 'Coat', org_id='eval', budget_chars=budget)
            rendered = json.dumps(result, ensure_ascii=False, default=str)
            assert len(rendered) <= budget
            assert 'PRIVATE' not in rendered and '$100' not in rendered
            assert fixture == before
            for retrieved in result:
                assert retrieved['content'] in ('', first, original)
                for _, _, start, end in retrieved['citation_spans']:
                    ref = {'source_id': 'source', 'revision': 1, 'span': [start, end]}
                    validate_citations([ref], result)
                    assert citation_text(ref, result) == original[start:end]
                    assert original[start:end] in (first, qualified)
            counts['cutoff_budget_provenance'] += 1

    for current_id, amount, currency in itertools.product(('coat', 'hat'), (100, 120), ('USD', 'EUR')):
        history = [{'product_id': 'coat', 'price': 100, 'currency': 'USD'}]
        products = [{'id': current_id, 'price': amount, 'currency': currency}]
        projected = redact_stale_prices('Coat costs $100.', history, products)
        unchanged = current_id == 'coat' and amount == 100 and currency == 'USD'
        assert ('$100' in projected) == unchanged
        counts['price_identity'] += 1

    for retired in (1, 100, 1000):
        original = f'Coat costs ${retired}. Coat is washable.'
        class Store(MemoryStore):
            def __init__(self): pass
            def products(self, org): return [{'id': 'coat', 'price': 120, 'currency': 'USD'}]
            def _rows(self, table, org):
                return ([{'product_id': 'coat', 'price': retired, 'currency': 'USD'}]
                        if table == 'memory_price_history' else [row(original)])
        result = Store().search('eval', 'Coat')
        start = original.index('Coat is washable.')
        ref = {'source_id': 'source', 'revision': 1, 'span': [start, len(original)]}
        validate_citations([ref], result)
        assert citation_text(ref, result) == original[start:]
        assert f'${retired}' not in json.dumps(result)
        counts['redaction_provenance'] += 1

    envelope = {'org_id': 'eval', 'platform': 'telegram', 'customer_handle': 'eval', 'text': 'Coat?'}
    rules = ('Keep replies concise.', 'Use short paragraphs.', 'Use bullet points for multiple benefits.')
    for ordered in itertools.permutations(rules):
        for long_count in (0, 1, 2):
            quotes = ['Coat is soft.', 'Coat is washable.']
            for index in range(long_count):
                quotes[index] = 'Coat ' + 'stays soft ' * 18 + 'unless treated.'
            knowledge = [{'source_id': rule, 'revision': 1, 'kind': 'correction', 'content': rule}
                         for rule in ordered]
            knowledge += [{'source_id': str(index), 'revision': 1, 'kind': 'manual', 'content': quote}
                          for index, quote in enumerate(quotes)]
            async def model(*args, **kwargs):
                return {'acknowledgement': 'none', 'citations': [
                    {'source_id': str(index), 'revision': 1, 'quote': quote}
                    for index, quote in enumerate(quotes)]}
            artifact = await generate_artifact(envelope, {'knowledge': knowledge, 'products': []},
                                               model=model, classification=Classification(intent_score=.5))
            expected = {str(index) for index in range(long_count, 2)}
            if long_count:
                expected.add('Keep replies concise.')
            if long_count < 2:
                expected.add('Use short paragraphs.')
            if not long_count:
                expected.add('Use bullet points for multiple benefits.')
            assert {ref['source_id'] for ref in artifact['cited_brand_passport_atoms']} == expected
            for index, quote in enumerate(quotes):
                assert (quote in artifact['draft_reply']) == (index >= long_count)
            counts['correction_reporting'] += 1

    for promise in ('Complimentary freight included.', 'We offer a discount.', 'Price is $100.'):
        async def forbidden_model(*args, **kwargs):
            raise AssertionError('Commercial edits must be rejected before inference')
        assert await analyze_edit({'draft_id': 'eval', 'original': promise, 'final': 'Thanks.'},
                                  model=forbidden_model) is None
        counts['learning'] += 1
    assert await analyze_edit({'draft_id': 'eval', 'original': 'We do not offer free shipping. Hello.',
                               'final': 'We offer free shipping. Thanks.'}, model=forbidden_model) is None
    counts['learning'] += 1
    return {'lane': 'offline', 'passed': sum(counts.values()), 'cases': counts,
            'threshold': 1.0, 'score': 1.0}


if __name__ == '__main__':
    print(json.dumps(asyncio.run(evaluate())))
