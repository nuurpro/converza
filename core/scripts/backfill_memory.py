"""Snapshot, idempotently enqueue current factual sources, and write a diff report.

Run from core: python scripts/backfill_memory.py --org UUID [--apply]
Default is a read-only plan with local artifacts. Never classifies historical approvals.
"""
from __future__ import annotations
import argparse
import csv
import json
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
from db import get_supabase
from services.memory import MemoryStore

TABLES=('brand_passports','brand_products','brand_knowledge','memory_sources','memory_source_revisions','memory_index_jobs','memory_price_history')


def snapshot(store, org):
    result={}; count=0; size=0
    for table in TABLES:
        # Revision table has no id; page by its stable composite primary key.
        rows=[]; offset=0
        while True:
            query=store.client.table(table).select('*').eq('org_id',org)
            query=query.order('source_id').order('revision') if table=='memory_source_revisions' else query.order('id')
            page=query.range(offset,offset+999).execute().data or []
            for row in page:
                size+=len(json.dumps(row,ensure_ascii=False).encode('utf-8')); count+=1
                if count>100000 or size>100*1024*1024:
                    raise RuntimeError('Snapshot exceeds100k rows/100MB; obtain approval and create a separately managed snapshot before applying')
            rows.extend(page)
            if len(page)<1000: break
            offset+=1000
        result[table]=rows
    return result


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--org',required=True); parser.add_argument('--apply',action='store_true'); args=parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env'); store=MemoryStore(get_supabase())
    out=Path(tempfile.gettempdir())/'converza-memory-backfill'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    out.mkdir(parents=True,exist_ok=False)
    log=out/'progress.log'; start=time.monotonic()
    def report(event,covered,total):
        elapsed=time.monotonic()-start; rate=covered/elapsed if elapsed else 0
        entry={'event':event,'timestamp':datetime.now(timezone.utc).isoformat(),'percent':round(100*covered/max(total,1),2),'covered':covered,'total':total,'rate_per_second':round(rate,2),'estimated_remaining_seconds':round(max(0,total-covered)/rate,1) if rate else None}
        line=json.dumps(entry); print(line,flush=True)
        with log.open('a',encoding='utf-8') as handle: handle.write(line+'\n')
    print(f'Progress file: {log}\nPowerShell: Get-Content -LiteralPath "{log}" -Wait')
    before=snapshot(store,args.org)
    (out/'before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2),encoding='utf-8')
    total=sum(len(before[t]) for t in ('brand_passports','brand_products','brand_knowledge'))
    report('brand-memory-backfill snapshot_saved',0,total)
    if not args.apply:
        (out/'report.md').write_text(f'# Backfill plan\n\nSnapshot saved. {total} canonical rows inspected. No database writes performed.\n\nRun the same command with --apply to enqueue factual memory. Historical approvals are excluded.\n',encoding='utf-8')
        print(f'Plan: {out / "report.md"}'); return
    # Bound progress waits to30s while RPC commits its trigger-generated source revisions/jobs.
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(lambda: store.client.rpc('memory_backfill',{'p_org':args.org}).execute().data)
        while not future.done():
            try:
                from concurrent.futures import TimeoutError
                future.result(timeout=30)
            except TimeoutError:
                current=store._rows('memory_sources',args.org)
                covered=sum(row['kind']!='objection' and not row.get('deleted_at') for row in current)
                report('brand-memory-backfill sources_covered',min(covered,total),total)
        future.result()
    after=snapshot(store,args.org)
    (out/'after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2),encoding='utf-8')
    previous={r['id']:r for r in before['memory_sources']}; following={r['id']:r for r in after['memory_sources']}
    fields=['source_id','kind','before_revision','after_revision','before_content','after_content','before_status','after_status']
    changed=[]
    with (out/'before-after.csv').open('w',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields); writer.writeheader()
        for key in sorted(previous.keys()|following.keys()):
            old=previous.get(key,{}); new=following.get(key,{})
            row=dict(source_id=key,kind=new.get('kind',old.get('kind')),before_revision=old.get('revision'),after_revision=new.get('revision'),before_content=old.get('content',''),after_content=new.get('content',''),before_status=old.get('indexing_status','absent'),after_status=new.get('indexing_status','absent'))
            writer.writerow(row)
            if old!=new: changed.append(row)
    examples={r['kind']:r for r in changed}
    lines=['# Backfill report','','Verdict: backfill committed successfully. Extraction is queued separately.',f'Canonical rows inspected: {total}. Sources changed: {len(changed)}.',f'Full diff: {out / "before-after.csv"}','','| Kind | Before revision/status | After revision/status |','| --- | --- | --- |']
    for kind,row in examples.items(): lines.append(f"| {kind} | {row['before_revision']} / {row['before_status']} | {row['after_revision']} / {row['after_status']} |")
    lines+=['','Gap: queued sources need the separately running indexer. Raw facts are immediately searchable. No historical approvals were converted to objection memory.']
    (out/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    report('brand-memory-backfill complete',total,total)
    print(f'Report: {out / "report.md"}\nFull CSV: {out / "before-after.csv"}')


if __name__=='__main__': main()
