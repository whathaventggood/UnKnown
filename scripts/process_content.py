#!/usr/bin/env python3
"""Explicit offline content checks, or bounded opt-in source-based enrichment."""
import argparse
import asyncio
import fcntl
import hashlib
import json
import sys
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import Settings
from app.core.database import make_engine,session_factory
from app.main import migrate
from app.ai.provider import CompatibleProvider
from app.ingestion.processing import process_batch
from app.models import IngestionJob


async def main(args):
    settings=Settings();migrate(settings)
    engine=make_engine(settings.database_url);factory=session_factory(engine)
    if args.status:
        with factory() as db:
            job=db.get(IngestionJob,args.status)
            if not job or job.source!='content_pipeline': raise ValueError('没有找到对应内容加工任务。')
            print(json.dumps({'job_id':job.id,'status':job.status,'processed':job.processed,'failed':job.failed,'errors':job.errors,'checkpoint':job.checkpoint},ensure_ascii=False))
        engine.dispose();return
    lock_path=Path('/tmp')/('unknown-content-'+hashlib.sha256(settings.database_url.encode()).hexdigest()[:20]+'.lock')
    with lock_path.open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds,trust_env=settings.llm_trust_env,follow_redirects=False) as http:
            result=await process_batch(factory,settings,limit=args.limit,data_kind=args.kind,after_id=args.after_id,resume=args.resume,publish=not args.review_only,force=args.force,enrich_ai=args.enrich_ai,max_ai_calls=args.max_ai_calls,max_reserved_tokens=args.max_reserved_tokens,provider=CompatibleProvider(settings,http) if args.enrich_ai else None)
    counts={}
    for item in result.get('results',{}).values(): counts[item['status']]=counts.get(item['status'],0)+1
    print(json.dumps({'job_id':result['job_id'],'status':result['status'],'processed':len(result.get('done',[])),'states':counts,'ai_calls':result.get('ai_calls',0),'reserved_tokens':result.get('reserved_tokens',0),'last_topic_id':result.get('last_topic_id')},ensure_ascii=False))
    engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=100)
    parser.add_argument('--kind',choices=['seed','online'])
    parser.add_argument('--after-id',help='下一批从上批输出的 last_topic_id 之后开始')
    parser.add_argument('--resume')
    parser.add_argument('--status',help='查看指定内容任务的状态、缺失项、失败原因与累计预算')
    parser.add_argument('--force',action='store_true')
    parser.add_argument('--review-only',action='store_true')
    parser.add_argument('--enrich-ai',action='store_true')
    parser.add_argument('--max-ai-calls',type=int,default=0)
    parser.add_argument('--max-reserved-tokens',type=int,default=0)
    asyncio.run(main(parser.parse_args()))
