"""Content-addressed, immutable ranking catalogs; private histories stay per batch."""
import hashlib
import json
import zlib
from app.models import CatalogSnapshot

MAX_RAW_BYTES=128*1024*1024


def pack_snapshot(db,candidates,history,result):
    raw=json.dumps(sorted(candidates,key=lambda t:str(t['id'])),sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()
    if len(raw)>MAX_RAW_BYTES: raise ValueError('Candidate snapshot exceeds storage bound')
    digest=hashlib.sha256(raw).hexdigest()
    if not db.get(CatalogSnapshot,digest):
        db.add(CatalogSnapshot(id=digest,payload=zlib.compress(raw,6),topic_count=len(candidates),raw_bytes=len(raw)))
        db.flush()
    compact={k:v for k,v in result.items() if k not in ('candidate_snapshot','history_snapshot')}
    return {'format':2,'catalog_ref':digest,'history':history,'result':compact}


def load_snapshot(db,batch):
    saved=batch.snapshot
    if saved.get('format')!=2:
        # Version 1 persisted the exact full candidates/history inline.
        return saved
    row=db.get(CatalogSnapshot,saved['catalog_ref'])
    if not row or row.codec!='zlib-json-v1': raise ValueError('Snapshot catalog unavailable')
    decoder=zlib.decompressobj()
    raw=decoder.decompress(row.payload,MAX_RAW_BYTES+1)
    if len(raw)>MAX_RAW_BYTES or decoder.unconsumed_tail or not decoder.eof or decoder.unused_data or hashlib.sha256(raw).hexdigest()!=row.id:
        raise ValueError('Snapshot integrity check failed')
    candidates=json.loads(raw)
    if not isinstance(candidates,list) or len(candidates)!=row.topic_count: raise ValueError('Invalid snapshot catalog')
    return {'candidates':candidates,'history':saved['history'],'result':{**saved['result'],'candidate_snapshot':candidates,'history_snapshot':saved['history']}}


def replay_batch(db,batch):
    snapshot=load_snapshot(db,batch);prior=snapshot['result']
    if batch.strategy_version=='unknown-rerank-1.0':
        from app.recommendation.legacy_v1 import recommend
    elif batch.strategy_version=='unknown-rerank-2.0':
        from app.recommendation.engine import recommend,surprise
        if 'surprise' in prior:
            return surprise(snapshot['candidates'],snapshot['history'],seed=batch.seed,config=prior.get('config_snapshot'),**prior['surprise'])
    else: raise ValueError('Unsupported historical strategy')
    return recommend(snapshot['candidates'],snapshot['history'],mode=prior.get('mode',batch.mode),seed=batch.seed,count=prior['constraints']['requested'],config=prior.get('config_snapshot'))
