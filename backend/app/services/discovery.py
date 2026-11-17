import hashlib
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, func
from app.models import *
from app.services.catalog import topic_json, source_json
from app.recommendation import recommend


def settings_snapshot(p):
    return {k:getattr(p,k) for k in ('timezone','familiar_disciplines','depth','intensity','broad_use_history')}


def local_date(p): return datetime.now(ZoneInfo(p.timezone)).date().isoformat()


def history_snapshot(db,p):
    states=list(db.scalars(select(TopicState).where(TopicState.profile_id==p.id)))
    topics={t.id:t for t in db.scalars(select(Topic))}
    recent_cutoff=(datetime.now(timezone.utc)-timedelta(days=14)).isoformat()
    explored=[s.topic_id for s in states if s.first_explored_at]
    history={'familiar_disciplines':p.familiar_disciplines,'intensity':p.intensity,'broad_use_history':p.broad_use_history,'explored_ids':explored,'explored_disciplines':sorted({topics[i].primary_discipline_id for i in explored if i in topics}),'explored_subfields':sorted({topics[i].subfield for i in explored if i in topics}),'known_ids':[s.topic_id for s in states if s.familiarity=='known'],'unfamiliar_ids':[s.topic_id for s in states if s.familiarity=='unfamiliar'],'skipped_ids':[s.topic_id for s in states if s.skipped_until and s.skipped_until>now()],'recent_ids':list(db.scalars(select(Impression.topic_id).where(Impression.profile_id==p.id,Impression.created_at>=recent_cutoff)))}
    origins=set(explored+history['known_ids']) | {t.id for t in topics.values() if t.primary_discipline_id in p.familiar_disciplines}
    paths={}
    relations=list(db.scalars(select(TopicRelation)))
    # Bounded two-hop directed BFS; property meaning/direction is never erased.
    for origin in sorted(origins):
        frontier=[(origin,[])]
        for depth in range(2):
            nxt=[]
            for start,path in frontier:
                for r in relations:
                    if r.source_id!=start or r.target_id==origin: continue
                    hop={'from_id':r.source_id,'from_title':topics[r.source_id].title,'from_discipline_id':topics[r.source_id].primary_discipline_id,'to_id':r.target_id,'to_title':topics[r.target_id].title,'type':r.type,'label':r.label,'explanation':r.explanation,'source_url':r.source_url,'direction':r.direction}
                    new=path+[hop]
                    if r.target_id not in paths or len(new)<len(paths[r.target_id]): paths[r.target_id]=new
                    nxt.append((r.target_id,new))
            frontier=nxt[:100]
    history['recent_candidates']=[{'id':topics[i].id,'title':topics[i].title,'subfield':topics[i].subfield} for i in set(history['recent_ids']) if i in topics]
    history['bridge_paths']=paths
    return history


def latest_batch(db,p,date,mode):
    return db.scalar(select(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.date==date,DailyRecommendation.mode==mode).order_by(DailyRecommendation.batch_number.desc()).limit(1))


def create_batch(db,p,mode,key=None):
    # Serialize creation across local processes before reading current batch.
    raw=db.connection().connection.driver_connection
    if hasattr(raw,'in_transaction') and not raw.in_transaction:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
    today=local_date(p)
    latest=latest_batch(db,p,today,mode)
    if key:
        prior=db.scalar(select(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.idempotency_key==key))
        if prior:
            if prior.mode!=mode: raise ValueError('IDEMPOTENCY_CONFLICT')
            return prior
    elif latest: return latest
    if key:
        cutoff=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        used=db.scalar(select(func.count()).select_from(DailyRecommendation).where(DailyRecommendation.profile_id==p.id,DailyRecommendation.created_at>=cutoff))
        if used>=30: raise ValueError('REFRESH_LIMIT')
    number=latest.batch_number+1 if latest else 1
    seed=int(hashlib.sha256(f'{p.id}|{today}|{mode}|{number}'.encode()).hexdigest()[:8],16)
    candidates=[]
    for t in db.scalars(select(Topic).order_by(Topic.id).limit(10000)):
        candidates.append({k:getattr(t,k) for k in ('id','title','primary_discipline_id','subfield','summary','quality_score','quality_features','content_status')} | {'sources':[source_json(s) for s in db.scalars(select(TopicSource).where(TopicSource.topic_id==t.id))]})
    history=history_snapshot(db,p)
    result=recommend(candidates,history,mode=mode,count=5,seed=seed)
    batch=DailyRecommendation(profile_id=p.id,date=today,mode=mode,batch_number=number,parent_id=latest.id if latest else None,idempotency_key=key or f'initial:{today}:{mode}',strategy_version=result['strategy_version'],seed=seed,constraints_json=result['constraints'],snapshot={'candidates':candidates,'history':history,'result':result},settings_snapshot=settings_snapshot(p))
    db.add(batch); db.flush()
    for position,item in enumerate(result['items']):
        db.add(RecommendationItem(batch_id=batch.id,topic_id=item['topic_id'],position=position,reason=item['reason'],features=item['features'],score=item['score'],bridge_path=item.get('bridge_path',[])))
    db.flush()
    return batch


def named_path(db,path):
    result=[]
    for hop in path:
        item=dict(hop)
        for endpoint in ('from','to'):
            topic=db.get(Topic,hop[endpoint+'_id'])
            item[endpoint+'_title']=topic.title if topic else '主题暂不可用'
        result.append(item)
    return result


def batch_json(db,b,p):
    return {'id':b.id,'date':b.date,'mode':b.mode,'batch_number':b.batch_number,'parent_id':b.parent_id,'strategy_version':b.strategy_version,'seed':b.seed,'constraints':b.constraints_json,'settings_changed':b.settings_snapshot!=settings_snapshot(p),'items':[{'topic':topic_json(db,db.get(Topic,i.topic_id),p.id),'reason':i.reason,'features':i.features,'score':i.score,'bridge_path':named_path(db,i.bridge_path)} for i in db.scalars(select(RecommendationItem).where(RecommendationItem.batch_id==b.id).order_by(RecommendationItem.position))]}
