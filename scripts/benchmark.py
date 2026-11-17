#!/usr/bin/env python3
"""Isolated SQLite benchmarks. Synthetic records NEVER enter the product DB."""
import argparse
import gc
import json
import resource
import sys
import tempfile
import time
from pathlib import Path
from sqlalchemy import event,insert,select,text

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import Settings
from app.main import migrate
from app.core.database import make_engine,session_factory
from app.models import Topic,TopicSource,Discipline,Profile,DailyRecommendation
from app.services.catalog import upsert_seed
from app.services.discovery import create_batch
from app.services.insights import graph


def rss_mb():
    value=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return value/(1024*1024 if sys.platform=='darwin' else 1024)


def size(engine,path):
    with engine.connect() as c: c.exec_driver_sql('PRAGMA wal_checkpoint(TRUNCATE)')
    return sum(p.stat().st_size for p in (path,Path(str(path)+'-wal')) if p.exists())


def measure(n):
    with tempfile.TemporaryDirectory(prefix='unknown-bench-') as directory:
        path=Path(directory)/'isolated.db'
        settings=Settings(database_url=f'sqlite:///{path}',_env_file=None,llm_api_key='')
        migrate(settings);engine=make_engine(settings.database_url);factory=session_factory(engine)
        with factory() as db:
            payload=json.loads((ROOT/'data/seeds/topics.json').read_text())
            if n in (60,360):
                upsert_seed(db,payload)
                if n==360: upsert_seed(db,json.loads((ROOT/'data/online/openalex.json').read_text()),data_kind='online')
            else:
                db.execute(insert(Discipline),payload['disciplines'])
                dids=[d['id'] for d in payload['disciplines']]
                topics=[];sources=[]
                for i in range(n):
                    topics.append({'id':f'synthetic-{i:05}','title':f'隔离性能模拟主题 {i}','summary':'这是隔离基准的合成中文入门材料，不得进入正式知识库。','primary_discipline_id':dids[i%12],'subfield':f'模拟细分{i%120}','question':'模拟内容如何工作？','value':'仅供性能测量。','quality_score':.8,'quality_features':{'has_example':True},'data_kind':'synthetic_benchmark','content_status':'PUBLISHED'})
                    sources.append({'id':f'synthetic-source-{i:05}','topic_id':f'synthetic-{i:05}','platform':'synthetic_benchmark','external_id':str(i),'url':f'https://example.org/synthetic-only/{i}','title':'Synthetic benchmark only','language':'en','license':'synthetic-test-only','excerpt':'Synthetic benchmark passage; never product knowledge.'})
                db.execute(insert(Topic),topics);db.execute(insert(TopicSource),sources)
            p=Profile(token_hash='isolated-benchmark-profile');db.add(p);db.commit();pid=p.id
        initial=size(engine,path)
        counter=[0]
        def count(*_): counter[0]+=1
        event.listen(engine,'before_cursor_execute',count)
        batches=[]
        rss_before=rss_mb()
        for i in range(2):
            counter[0]=0;start=time.perf_counter()
            with factory() as db:
                batch=create_batch(db,db.get(Profile,pid),'unknown',f'benchmark-{i:03}')
                bid=batch.id;actual=db.scalar(select(text('count(*)')).select_from(Topic).where(Topic.content_status=='PUBLISHED'))
                db.commit()
            elapsed=time.perf_counter()-start;queries=counter[0]
            after=size(engine,path)
            batches.append({'seconds':round(elapsed,4),'sql_statements':queries,'storage_bytes':after-initial})
        counter[0]=0;start=time.perf_counter()
        with factory() as db: g=graph(db,db.get(Profile,pid))
        graph_seconds=time.perf_counter()-start;graph_queries=counter[0]
        event.remove(engine,'before_cursor_execute',count)
        with factory() as db:
            snapshots=sum(len(json.dumps(b.snapshot,ensure_ascii=False).encode()) for b in db.scalars(select(DailyRecommendation)))
        engine.dispose()
        return {'topics':n,'data_kind':'real_archived_catalog' if n in (60,360) else 'isolated_synthetic', 'published_candidates':actual,'batches':batches,'snapshot_json_bytes':snapshots,'graph_seconds':round(graph_seconds,4),'graph_sql_statements':graph_queries,'graph_nodes':len(g['nodes']),'rss_peak_mb':round(rss_mb(),2),'rss_peak_increase_mb':round(max(0,rss_mb()-rss_before),2),'notes':'SQL includes identity read and publication count (one extra SELECT). RSS is cumulative process high-water, not allocation size or steady-state memory.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output');p.add_argument('--sizes',nargs='+',type=int,default=[60,360,1000,10000]);args=p.parse_args()
    results=[]
    for n in args.sizes:
        result=measure(n);results.append(result);print(json.dumps(result,ensure_ascii=False),flush=True);gc.collect()
    if args.output: Path(args.output).write_text(json.dumps({'scope':'isolated local SQLite; no network or paid AI; no real learning-effect evidence','results':results},ensure_ascii=False,indent=2)+'\n')
