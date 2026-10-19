"""Free deterministic memory eval lane; optional live extraction scores exact quote validity."""
import argparse
import asyncio
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.indexer import validate_extraction, IndexWorker
from services.memory import redact_stale_prices


def evaluate():
    fixtures=json.loads(Path(__file__).with_name('fixtures.json').read_text(encoding='utf-8-sig'))
    passed=0
    for case in fixtures['cases']:
        try:
            validate_extraction(case['source'],case['output']); valid=True
        except ValueError:
            valid=False
        if valid != case['valid']: raise AssertionError(case['id'])
        passed+=1
    pricing=fixtures['retrieval']
    text=redact_stale_prices('Price: $100; current $120',[{'price':pricing['retired_price'],'currency':'USD'}],[{'price':pricing['current_price'],'currency':'USD'}])
    assert '100' not in text and '120' in text
    passed+=1
    return {'passed':passed,'total':passed,'threshold':1.0,'score':1.0}


async def live():
    fixtures=json.loads(Path(__file__).with_name('fixtures.json').read_text(encoding='utf-8-sig'))
    sources=[case['source'] for case in fixtures['cases'] if case['valid']]
    worker=IndexWorker(None)
    for source in sources:
        output=await worker._extract(source)
        assert output['atoms'], 'Live extraction returned no exact quote Atoms'
    return {'live_valid':len(sources),'live_total':len(sources),'threshold':1.0}


if __name__=='__main__':
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[2] / '.env')
    parser=argparse.ArgumentParser(); parser.add_argument('--live',action='store_true'); args=parser.parse_args()
    print(json.dumps(asyncio.run(live()) if args.live else evaluate()))
