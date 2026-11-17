#!/usr/bin/env python3
"""Build a bounded OpenAlex metadata library or import the verified snapshot.

Explicit CLI only: no account creation, no full-paper downloads, no LLM calls.
Run migrations and seed initialization first (README).
"""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from app.core.config import Settings
from app.core.database import make_engine, session_factory
from app.models import IngestionJob, now
from app.services.catalog import upsert_seed
from app.ingestion.adapters import CachedHTTP
from app.ingestion.collector import collect, taxonomy

GROUPS = [('mathematics','mathematics'),('physics','quantum'),('chemistry','chemistry'),('biology','ecology'),('earth','climate'),('astronomy','astronomy'),('computing','computer'),('cognition','cognitive'),('economics','economics'),('society','sociology'),('humanities','history'),('arts','music')]


def balanced_topics(groups: list[list[dict]], limit: int) -> list[dict]:
    selected = {}
    for pos in range(max([len(g) for g in groups] or [0])):
        for group in groups:
            if pos < len(group) and len(selected) < limit:
                selected.setdefault(group[pos]['id'], group[pos])
    return list(selected.values())


async def run(args):
    settings = Settings()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    lock_dir = ROOT/'data/ingestion'
    lock_dir.mkdir(parents=True, exist_ok=True)
    with factory() as db:
        if args.snapshot:
            payload = json.loads(Path(args.snapshot).read_text())
            if len(payload.get('topics', [])) > 300:
                raise ValueError('快照最多 300 条，超出上限。')
            job = IngestionJob(source='openalex_snapshot', status='running', params={'snapshot_sha256':hashlib.sha256(Path(args.snapshot).read_bytes()).hexdigest()})
            db.add(job)
            db.flush()
            result = upsert_seed(db, payload, data_kind='online')
            job.status,job.processed,job.updated_at='complete',result['processed'],now()
            db.commit()
            print(json.dumps({'job_id':job.id,**result,'network_requests':0},ensure_ascii=False))
            engine.dispose()
            return
        if args.resume:
            job = db.get(IngestionJob, args.resume)
            if not job or job.source != 'openalex_initialization':
                raise ValueError('找不到对应的 OpenAlex 初始化任务。')
            limit, per_query = job.params['limit'], job.params['per_query']
        else:
            limit,per_query=args.limit,args.per_query
            job=IngestionJob(source='openalex_initialization',params={'groups':GROUPS,'limit':limit,'per_query':per_query},checkpoint={'groups':{}})
            db.add(job)
            db.commit()
        job_lock = (lock_dir/f'{job.id}.lock').open('a')
        try:
            fcntl.flock(job_lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            job_lock.close()
            raise ValueError('该任务已有采集进程。') from None
        job_id,checkpoint=job.id,job.checkpoint or {'groups':{}}
        job.status,job.updated_at='running',now()
        db.commit()
    http=CachedHTTP(timeout=20,retries=1,min_interval=1.2,cache_dir=ROOT/'data/cache/ingestion',user_agent=settings.ingestion_user_agent,trust_env=args.trust_env)
    print(f'初始化任务 {job_id}；最多 12 个查询、每查询 {per_query} 条、最终最多 {limit} 个去重主题。',flush=True)
    try:
        for did,query in GROUPS:
            previous=checkpoint['groups'].get(did,{})
            if previous.get('status')=='complete':
                continue
            result=await collect('openalex',[query],per_query,discipline_id=did,http=http,api_key=settings.openalex_api_key or None,checkpoint=previous.get('checkpoint'))
            merged={t['id']:t for t in previous.get('topics',[])}
            merged.update({t['id']:t for t in result['topics']})
            checkpoint['groups'][did]={'topics':list(merged.values()),'checkpoint':result['checkpoint'],'status':result['status'],'errors':result['errors']}
            with factory() as db:
                job=db.get(IngestionJob,job_id)
                # The checkpoint includes bounded public topic metadata so an interrupted
                # run can resume without losing completed groups or repeating API work.
                job.checkpoint=json.loads(json.dumps(checkpoint))
                job.processed=sum(len(x['topics']) for x in checkpoint['groups'].values())
                job.errors=[e for x in checkpoint['groups'].values() for e in x['errors']][-200:]
                job.failed=len(job.errors)
                job.updated_at=now()
                db.commit()
            print(json.dumps({'discipline':did,'retrieved':len(merged),'status':result['status']},ensure_ascii=False),flush=True)
        topics=balanced_topics([checkpoint['groups'].get(did,{}).get('topics',[]) for did,_ in GROUPS],limit)
        payload={'version':'1','data_kind':'online','collected_at':now(),'source':'OpenAlex','source_license':'CC0 1.0 (topic metadata); cluster names/descriptions use upstream AI','disciplines':taxonomy(),'topics':topics,'relations':[],'verification_scope':'Real source metadata; not expert review. Explicit query-batch primary discipline mapping with external hierarchy preserved.'}
        output=Path(args.output) if args.output else lock_dir/f'{job_id}.json'
        output.parent.mkdir(parents=True,exist_ok=True)
        temporary=output.with_suffix('.tmp')
        temporary.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
        temporary.replace(output)
        with factory() as db:
            result=upsert_seed(db,payload,data_kind='online')
            job=db.get(IngestionJob,job_id)
            job.status='partial' if job.failed or len(topics)<limit else 'complete'
            job.updated_at=now()
            db.commit()
            print(json.dumps({'job_id':job.id,'status':job.status,'unique_topics':len(topics),**result,'output':str(output)},ensure_ascii=False))
    except BaseException:
        with factory() as db:
            job=db.get(IngestionJob,job_id)
            job.status,job.updated_at='interrupted',now()
            db.commit()
        raise
    finally:
        await http.close()
        fcntl.flock(job_lock,fcntl.LOCK_UN)
        job_lock.close()
        engine.dispose()


def main():
    p=argparse.ArgumentParser(description='有限 OpenAlex 批量初始化，默认目标 300；无需下载全量数据集')
    p.add_argument('--limit',type=int,default=300)
    p.add_argument('--per-query',type=int,default=35)
    p.add_argument('--resume',help='恢复初始化任务 ID')
    p.add_argument('--output',help='导出 JSON 路径；默认 data/ingestion/<jobid>.json')
    p.add_argument('--trust-env',action='store_true')
    p.add_argument('--snapshot',help='离线导入已核验在线快照，例如 data/online/openalex.json；不请求网络')
    args=p.parse_args()
    if not 1<=args.limit<=300 or not 1<=args.per_query<=100:
        p.error('limit 为 1..300，per-query 为 1..100。')
    try:
        asyncio.run(run(args))
    except (ValueError,OSError) as exc:
        print(f'初始化未完成：{exc}',file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('已中断，保存的任务 ID 可用于 --resume。',file=sys.stderr)
        return 130
    return 0


if __name__=='__main__':
    raise SystemExit(main())
