#!/usr/bin/env python3
"""Read and replay one saved recommendation batch without changing the database."""
import argparse
import json
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from app.core.config import Settings
from app.core.database import make_engine,session_factory
from app.models import DailyRecommendation
from app.services.snapshots import replay_batch,load_snapshot

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('batch_id');args=parser.parse_args()
    engine=make_engine(Settings().database_url)
    with session_factory(engine)() as db:
        batch=db.get(DailyRecommendation,args.batch_id)
        if not batch: parser.error('没有找到这个批次。')
        result=replay_batch(db,batch);saved=load_snapshot(db,batch)['result']
        print(json.dumps({'batch_id':batch.id,'strategy_version':batch.strategy_version,'seed':batch.seed,'items_match':result['items']==saved['items'],'topic_ids':[i['topic_id'] for i in result['items']]},ensure_ascii=False))
    engine.dispose()
