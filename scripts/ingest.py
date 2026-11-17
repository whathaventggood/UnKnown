#!/usr/bin/env python3
"""Explicit finite ingestion command. No service worker or paid LLM calls."""
from __future__ import annotations

import argparse
import fcntl
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.core.config import Settings
from app.core.database import make_engine, session_factory
from app.models import IngestionJob, TopicSource, now
from sqlalchemy import select
from app.ingestion.adapters import CachedHTTP
from app.ingestion.collector import collect, resolve_raw_relations
from app.services.catalog import upsert_seed


def parser():
    p = argparse.ArgumentParser(description='有限、可恢复的来源元数据采集（先运行数据库迁移）')
    p.add_argument('--source', choices=['wikipedia', 'wikidata', 'openalex'])
    p.add_argument('--query', action='append', default=[])
    p.add_argument('--discipline', help='内部主学科 ID；由操作者明确提供，映射依据存档')
    p.add_argument('--language', choices=['zh', 'en'], default='zh')
    p.add_argument('--limit', type=int, default=20)
    p.add_argument('--trust-env', action='store_true', help='显式使用操作系统代理配置；默认忽略代理以避免失效配置')
    p.add_argument('--resume', help='恢复已有 ingestion job ID')
    p.add_argument('--status', help='查询已有 ingestion job ID；不发送网络请求')
    return p


async def run(args):
    settings = Settings()
    engine = make_engine(settings.database_url)
    factory = session_factory(engine)
    with factory() as db:
        if args.status:
            job = db.get(IngestionJob, args.status)
            if not job:
                raise ValueError('找不到采集任务。')
            print(json.dumps({k: getattr(job, k) for k in ['id','status','source','processed','failed','errors','checkpoint','updated_at']}, ensure_ascii=False, indent=2))
            return
        if args.resume:
            job = db.get(IngestionJob, args.resume)
            if not job:
                raise ValueError('找不到采集任务。')
            params = job.params
        else:
            if not args.source or not args.query or not args.discipline:
                raise ValueError('新任务需要 --source、--query 和 --discipline。')
            if not 1 <= args.limit <= 300:
                raise ValueError('--limit 必须为 1..300。')
            params = {'queries': args.query, 'limit': args.limit, 'discipline_id': args.discipline, 'language': args.language}
            job = IngestionJob(source=args.source, params=params)
            db.add(job)
            db.commit()
        lock_dir = ROOT / 'data/ingestion'
        lock_dir.mkdir(parents=True, exist_ok=True)
        job_lock = (lock_dir / f'{job.id}.lock').open('a')
        try:
            fcntl.flock(job_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            job_lock.close()
            raise ValueError('同一采集任务已有进程运行，稍后再试。') from None
        job.status, job.updated_at = 'running', now()
        db.commit()
        job_id, source, checkpoint = job.id, job.source, job.checkpoint
    print(f'采集任务 {job_id} 已开始；最多 {params["limit"]} 个来源条目。', flush=True)

    async def save(checkpoint, topic, error):
        with factory() as db:
            job = db.get(IngestionJob, job_id)
            if topic:
                upsert_seed(db, {'topics': [topic], 'disciplines': []}, data_kind='online')
                job.processed += 1
            if error:
                job.errors = [*job.errors[-199:], error]
                job.failed += 1
            job.checkpoint, job.updated_at = checkpoint, now()
            db.commit()

    http = CachedHTTP(cache_dir=ROOT / 'data/cache/ingestion', user_agent=settings.ingestion_user_agent, trust_env=args.trust_env)
    try:
        result = await collect(source, params['queries'], params['limit'], discipline_id=params['discipline_id'], language=params['language'], http=http, api_key=settings.openalex_api_key or None, checkpoint=checkpoint, on_progress=save)
        with factory() as db:
            identity_map = {}
            for source_record in db.scalars(select(TopicSource)):
                entity_id = source_record.metadata_json.get('entity_id')
                if entity_id:
                    identity_map[entity_id] = source_record.topic_id
            relations = resolve_raw_relations(result['raw_relations'], identity_map)
            upsert_seed(db, {'relations': relations}, data_kind='online')
            job = db.get(IngestionJob, job_id)
            job.status, job.updated_at = result['status'], now()
            db.commit()
            print(json.dumps({'job_id': job.id, 'status': job.status, 'processed': job.processed, 'failed_attempts': job.failed, 'pending': len(job.checkpoint.get('pending', []))}, ensure_ascii=False))
    except BaseException:
        with factory() as db:
            job = db.get(IngestionJob, job_id)
            job.status, job.updated_at = 'interrupted', now()
            db.commit()
        raise
    finally:
        await http.close()
        engine.dispose()
        fcntl.flock(job_lock, fcntl.LOCK_UN)
        job_lock.close()


def main():
    args = parser().parse_args()
    try:
        asyncio.run(run(args))
    except (ValueError, OSError) as exc:
        print(f'采集未执行：{exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('采集已中断，已保存断点；可使用 --resume 恢复。', file=sys.stderr)
        return 130
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
