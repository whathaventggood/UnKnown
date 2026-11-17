import hashlib
import secrets
from datetime import datetime,timedelta,timezone
from typing import Annotated,Literal
from fastapi import APIRouter,Depends,Request,Response,Query,HTTPException
from sqlalchemy import select,delete,func
from app.models import *
from app.schemas import *
from app.services.catalog import topic_json,topics_json,discipline_json,state_json
from app.services.discovery import create_batch,batch_json
from app.services.insights import stats,graph
from app.ai.provider import ProviderError
from app.services.paths import paths_from,validate_path,saved_json,saved_paths_json,reliable
from app.services.challenges import challenge_for,reference_feedback,attempt_json

router=APIRouter(prefix='/api',responses={status:{'model':ErrorOut} for status in (400,403,404,409,422,429,500,502,504)})

def fail(status,code,message): raise HTTPException(status,detail={'code':code,'message':message})

async def get_db(request:Request):
    with request.app.state.Session() as db:
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback();raise

DB=Annotated[object,Depends(get_db,scope='function')]

async def get_profile(request:Request,response:Response,db:DB):
    token=request.cookies.get('unknown_session','')
    p=db.scalar(select(Profile).where(Profile.token_hash==hashlib.sha256(token.encode()).hexdigest())) if token and len(token)<200 else None
    if not p:
        token=secrets.token_urlsafe(32)
        p=Profile(token_hash=hashlib.sha256(token.encode()).hexdigest(),timezone=request.app.state.settings.default_timezone)
        db.add(p);db.flush()
        response.set_cookie('unknown_session',token,httponly=True,secure=request.app.state.settings.cookie_secure,samesite=request.app.state.settings.cookie_samesite,max_age=60*60*24*365,path='/')
    return p
P=Annotated[Profile,Depends(get_profile)]

def topic_or_404(db,topic_id):
    topic=db.get(Topic,topic_id)
    if not topic: fail(404,'TOPIC_NOT_FOUND','没有找到这个主题。')
    return topic

def profile_json(p,settings):
    return {k:getattr(p,k) for k in ('id','timezone','familiar_disciplines','depth','intensity','broad_use_history','onboarding_complete')}|{'ai':{'configured':bool(settings.llm_api_key),'model':settings.llm_model if settings.llm_api_key else None}}

@router.get('/health',response_model=HealthOut)
async def health(request:Request):
    with request.app.state.Session() as db:
        n=db.scalar(select(func.count()).select_from(Topic))
    return {'status':'ok','version':'0.1.0','topics':n,'ai_configured':bool(request.app.state.settings.llm_api_key)}

@router.get('/profile',response_model=ProfileOut)
async def profile(request:Request,p:P): return profile_json(p,request.app.state.settings)

@router.patch('/profile',response_model=ProfileOut)
async def patch_profile(body:ProfilePatch,request:Request,db:DB,p:P):
    values=body.model_dump(exclude_unset=True)
    if any(v is None for v in values.values()): fail(422,'INVALID_PROFILE','设置值不能为 null。')
    if 'familiar_disciplines' in values:
        known=set(db.scalars(select(Discipline.id)))
        if not set(values['familiar_disciplines'])<=known: fail(422,'INVALID_DISCIPLINE','请选择知识库中已有的领域。')
        values['familiar_disciplines']=sorted(set(values['familiar_disciplines']))
    for k,v in values.items(): setattr(p,k,v)
    db.flush();return profile_json(p,request.app.state.settings)

@router.post('/profile/reset',response_model=ResetOut)
async def reset_profile(body:ResetBody,request:Request,db:DB,p:P):
    request.app.state.ai.forget_profile(p.id)
    # Shared catalog and general explanations remain. Anonymous accounting rows
    # keep global usage totals but no profile identifier after reset.
    db.execute(delete(ChatMessage).where(ChatMessage.profile_id==p.id))
    for cls in (Impression,RecommendationItem):
        if cls is Impression: db.execute(delete(cls).where(cls.profile_id==p.id))
        else: db.execute(delete(cls).where(cls.batch_id.in_(select(DailyRecommendation.id).where(DailyRecommendation.profile_id==p.id))))
    for cls in (SavedPath,ChallengeAttempt,DailyRecommendation,TopicEvent,TopicState,Bookmark): db.execute(delete(cls).where(cls.profile_id==p.id))
    db.query(AIUsage).filter(AIUsage.profile_id==p.id).update({'profile_id':None})
    p.familiar_disciplines=[];p.onboarding_complete=False
    return {'cleared':True,'message':'已清除当前档案的探索、反馈、收藏、推荐、保存路径、自测、回访和私有讨论。共享知识库与公共解释已保留。'}

@router.get('/disciplines',response_model=DisciplinesOut)
async def disciplines(db:DB): return {'items':[discipline_json(d) for d in db.scalars(select(Discipline).order_by(Discipline.id))]}

@router.get('/discover/today',response_model=DailyOut)
async def discover(request:Request,db:DB,p:P,mode:Mode='unknown'):
    return batch_json(db,create_batch(db,p,mode,config={'semantic_similarity':request.app.state.settings.semantic_similarity}),p)

@router.post('/discover/refresh',response_model=DailyOut)
async def refresh(body:RefreshBody,request:Request,db:DB,p:P):
    try: return batch_json(db,create_batch(db,p,body.mode,body.idempotency_key,config={'semantic_similarity':request.app.state.settings.semantic_similarity}),p)
    except ValueError as e:
        if str(e)=='REFRESH_LIMIT': fail(429,'REFRESH_LIMIT','一小时内换组过于频繁，请稍后再试。')
        fail(409,'IDEMPOTENCY_CONFLICT','此操作标识已用于另一模式，请重新操作。')

@router.post('/discover/impressions',response_model=ImpressionOut)
async def impressions(body:ImpressionsBody,db:DB,p:P):
    batch=db.get(DailyRecommendation,body.batch_id)
    if not batch or batch.profile_id!=p.id: fail(404,'BATCH_NOT_FOUND','没有找到推荐批次。')
    allowed=set(db.scalars(select(RecommendationItem.topic_id).where(RecommendationItem.batch_id==batch.id)))
    if not set(body.topic_ids)<=allowed: fail(422,'INVALID_IMPRESSION','主题不属于这个推荐批次。')
    n=0
    for tid in set(body.topic_ids):
        if not db.get(Impression,(batch.id,tid)):
            db.add(Impression(batch_id=batch.id,topic_id=tid,profile_id=p.id));n+=1
    db.flush();return {'recorded':n}


@router.post('/discover/surprise',response_model=SurpriseOut)
async def unexpected_knowledge(body:SurpriseBody,request:Request,db:DB,p:P):
    mode=f'surprise:{body.strength}:{int(body.history_free)}'
    try:
        batch=create_batch(db,p,mode,body.idempotency_key,surprise_spec={'strength':body.strength,'history_free':body.history_free},config={'semantic_similarity':request.app.state.settings.semantic_similarity})
    except ValueError as exc:
        if str(exc)=='REFRESH_LIMIT': fail(429,'REFRESH_LIMIT','本次探索请求较多，请稍后再试。')
        fail(409,'IDEMPOTENCY_CONFLICT','此操作标识已用于不同的探索设置。')
    result=batch_json(db,batch,p)
    return {'id':batch.id,'strength':body.strength,'history_free':body.history_free,'item':result['items'][0] if result['items'] else None,'constraints':result['constraints']}


def relation_json(db,r,titles=None):
    return {k:getattr(r,k) for k in ('id','type','label','explanation','source_url','direction','source_id','target_id','property_id','evidence_status','evidence_excerpt')} | {'source_title':titles[r.source_id] if titles is not None else db.get(Topic,r.source_id).title,'target_title':titles[r.target_id] if titles is not None else db.get(Topic,r.target_id).title}

@router.get('/topics/{topic_id}',response_model=TopicOut)
async def detail(topic_id:str,db:DB,p:P):
    t=topic_or_404(db,topic_id)
    s=db.get(TopicState,(p.id,topic_id))
    if not s:
        s=TopicState(profile_id=p.id,topic_id=topic_id);db.add(s);db.flush()
    if not s.first_explored_at:
        s.first_explored_at=now()
        db.add(TopicEvent(profile_id=p.id,topic_id=topic_id,action='explore',idempotency_key='explore:'+topic_id))
    s.last_visited_at=now()
    # Visit history is separate from unique exploration.
    db.add(TopicEvent(profile_id=p.id,topic_id=topic_id,action='visit',idempotency_key=uid()))
    db.flush()
    result=topic_json(db,t,p.id)
    relations=[r for r in db.scalars(select(TopicRelation).where(((TopicRelation.source_id==topic_id)|(TopicRelation.target_id==topic_id)),TopicRelation.evidence_status.in_(('curated','source_checked'))).order_by(TopicRelation.id).limit(31)) if reliable(r)]
    endpoints={i for r in relations for i in (r.source_id,r.target_id)}
    titles=dict(db.execute(select(Topic.id,Topic.title).where(Topic.id.in_(endpoints))).all()) if endpoints else {}
    result['relations']=[relation_json(db,r,titles) for r in relations[:30]]
    result['relations_truncated']=len(relations)>30
    return result

@router.get('/topics/{topic_id}/related',response_model=RelatedOut)
async def related(topic_id:str,db:DB,p:P,limit:int=Query(12,ge=1,le=30)):
    topic_or_404(db,topic_id)
    relations=[r for r in db.scalars(select(TopicRelation).where(((TopicRelation.source_id==topic_id)|(TopicRelation.target_id==topic_id)),TopicRelation.evidence_status.in_(('curated','source_checked'))).order_by(TopicRelation.id).limit(limit)) if reliable(r)]
    ids={r.target_id if r.source_id==topic_id else r.source_id for r in relations}
    topics=list(db.scalars(select(Topic).where(Topic.id.in_(ids)))) if ids else []
    serialized={t['id']:t for t in topics_json(db,topics,p.id)}
    names=dict(db.execute(select(Topic.id,Topic.title).where(Topic.id.in_(ids|{topic_id}))).all())
    result=[{'topic':serialized[r.target_id if r.source_id==topic_id else r.source_id],'relation':relation_json(db,r,names)} for r in relations]
    return {'items':result}


@router.get('/topics/{topic_id}/paths',response_model=PathsOut)
async def exploration_paths(topic_id:str,db:DB,p:P,max_hops:int=Query(4,ge=1,le=4)):
    topic_or_404(db,topic_id)
    return paths_from(db,topic_id,max_hops=max_hops)


@router.post('/paths',response_model=SavedPathOut)
async def save_exploration_path(body:SavePathBody,db:DB,p:P):
    existing=db.scalar(select(SavedPath).where(SavedPath.profile_id==p.id,SavedPath.idempotency_key==body.idempotency_key))
    if existing:
        if existing.topic_ids!=body.topic_ids or existing.relation_ids!=body.relation_ids: fail(409,'IDEMPOTENCY_CONFLICT','操作标识已用于不同路径。')
        return saved_json(db,existing)
    try: hops=validate_path(db,body.topic_ids,body.relation_ids)
    except ValueError as exc: fail(422,'INVALID_PATH',str(exc))
    path=SavedPath(profile_id=p.id,title=hops[0]['from_title']+' → '+hops[-1]['to_title'],topic_ids=body.topic_ids,relation_ids=body.relation_ids,evidence_snapshot=hops,idempotency_key=body.idempotency_key)
    db.add(path);db.flush();return saved_json(db,path)


@router.get('/paths',response_model=SavedPathsOut)
async def saved_exploration_paths(db:DB,p:P,limit:int=Query(20,ge=1,le=50),offset:int=Query(0,ge=0,le=100000)):
    total=db.scalar(select(func.count()).select_from(SavedPath).where(SavedPath.profile_id==p.id))
    rows=db.scalars(select(SavedPath).where(SavedPath.profile_id==p.id).order_by(SavedPath.created_at.desc(),SavedPath.id).offset(offset).limit(limit))
    return {'items':saved_paths_json(db,rows),'total':total}


def own_path(db,p,path_id):
    path=db.get(SavedPath,path_id)
    if not path or path.profile_id!=p.id: fail(404,'PATH_NOT_FOUND','没有找到已保存路径。')
    return path


@router.get('/paths/{path_id}',response_model=SavedPathOut)
async def saved_path(path_id:str,db:DB,p:P): return saved_json(db,own_path(db,p,path_id))


@router.patch('/paths/{path_id}',response_model=SavedPathOut)
async def path_position(path_id:str,body:PathPositionBody,db:DB,p:P):
    path=own_path(db,p,path_id)
    if body.position>=len(path.topic_ids): fail(422,'INVALID_PATH_POSITION','路径位置超出范围。')
    event_key=f'path:{path.id}:{body.position}'
    if body.position>0 and not db.scalar(select(TopicEvent.id).where(TopicEvent.profile_id==p.id,TopicEvent.idempotency_key==event_key)):
        db.add(TopicEvent(profile_id=p.id,topic_id=path.topic_ids[body.position],action='path_continue',idempotency_key=event_key))
    path.position=body.position;db.flush();return saved_json(db,path)


@router.delete('/paths/{path_id}',response_model=DeletedOut)
async def delete_path(path_id:str,db:DB,p:P):
    path=own_path(db,p,path_id);db.delete(path);return {'deleted':True}


@router.get('/topics/{topic_id}/challenge',response_model=ChallengeOut)
async def cognitive_challenge(topic_id:str,db:DB,p:P,reveal:bool=False):
    return challenge_for(db,topic_or_404(db,topic_id),reveal=reveal)


@router.post('/topics/{topic_id}/challenge',response_model=AttemptOut)
async def answer_challenge(topic_id:str,body:ChallengeBody,db:DB,p:P):
    topic=topic_or_404(db,topic_id)
    prior=db.scalar(select(ChallengeAttempt).where(ChallengeAttempt.profile_id==p.id,ChallengeAttempt.idempotency_key==body.idempotency_key))
    if prior:
        if prior.topic_id!=topic_id or prior.answer!=body.answer or prior.challenge_id!=body.challenge_id: fail(409,'IDEMPOTENCY_CONFLICT','操作标识已用于不同作答。')
        return attempt_json(prior)
    result=challenge_for(db,topic,reveal=True)
    challenge=result['challenge']
    if not challenge: fail(422,'CHALLENGE_UNAVAILABLE',result['message'])
    if challenge['id']!=body.challenge_id: fail(409,'CHALLENGE_CHANGED','来源材料已变化，请重新打开挑战；你的输入仍可保留。')
    attempt=ChallengeAttempt(profile_id=p.id,topic_id=topic_id,challenge_id=body.challenge_id,answer=body.answer,self_assessment=body.self_assessment,feedback=reference_feedback(challenge,body.answer),idempotency_key=body.idempotency_key)
    db.add(attempt);db.flush();return attempt_json(attempt)


@router.get('/topics/{topic_id}/challenge/attempts',response_model=AttemptsOut)
async def challenge_history(topic_id:str,db:DB,p:P,limit:int=Query(10,ge=1,le=30)):
    topic_or_404(db,topic_id)
    rows=db.scalars(select(ChallengeAttempt).where(ChallengeAttempt.profile_id==p.id,ChallengeAttempt.topic_id==topic_id).order_by(ChallengeAttempt.created_at.desc(),ChallengeAttempt.id.desc()).limit(limit))
    return {'items':[attempt_json(r) for r in rows]}


@router.patch('/challenge-attempts/{attempt_id}',response_model=AttemptOut)
async def assess_attempt(attempt_id:str,body:AssessmentBody,db:DB,p:P):
    attempt=db.get(ChallengeAttempt,attempt_id)
    if not attempt or attempt.profile_id!=p.id: fail(404,'ATTEMPT_NOT_FOUND','没有找到这次作答。')
    attempt.self_assessment=body.self_assessment;db.flush();return attempt_json(attempt)


@router.get('/revisits',response_model=CollectionOut)
async def revisits(db:DB,p:P,due_only:bool=False,limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    query=select(Topic).join(TopicState,TopicState.topic_id==Topic.id).where(TopicState.profile_id==p.id,TopicState.revisit_at.is_not(None))
    if due_only: query=query.where(TopicState.revisit_at<=now())
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    rows=db.scalars(query.order_by(TopicState.revisit_at,Topic.id).offset(offset).limit(limit))
    return {'items':topics_json(db,rows,p.id),'total':total}

@router.post('/topics/{topic_id}/feedback',response_model=StateResponse)
async def feedback(topic_id:str,body:FeedbackBody,db:DB,p:P):
    topic_or_404(db,topic_id)
    prior=db.scalar(select(TopicEvent).where(TopicEvent.profile_id==p.id,TopicEvent.idempotency_key==body.idempotency_key))
    if prior:
        if prior.topic_id!=topic_id or prior.action!=body.action: fail(409,'IDEMPOTENCY_CONFLICT','操作标识已用于其他反馈。')
        return {'state':state_json(db,p.id,topic_id)}
    st=db.get(TopicState,(p.id,topic_id))
    if not st: st=TopicState(profile_id=p.id,topic_id=topic_id);db.add(st)
    if body.action in ('known','unfamiliar','name_only','concept_only','connections_unknown','forgotten'): st.familiarity=body.action
    elif body.action=='skip': st.skipped_until=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()
    elif body.action=='unskip': st.skipped_until=None
    elif body.action=='revisit': st.revisit_at=(datetime.now(timezone.utc)+timedelta(days=7)).isoformat()
    elif body.action=='cancel_revisit': st.revisit_at=None
    elif body.action in ('worthwhile','not_worthwhile'): st.worthwhile=body.action=='worthwhile'
    else: st.learning='learning' if body.action=='learning' else 'understood' if body.action=='understood' else 'none'
    db.add(TopicEvent(profile_id=p.id,topic_id=topic_id,action=body.action,idempotency_key=body.idempotency_key))
    db.flush();return {'state':state_json(db,p.id,topic_id)}

@router.post('/bookmarks',response_model=StateResponse)
async def add_bookmark(body:BookmarkBody,db:DB,p:P):
    topic_or_404(db,body.topic_id)
    if not db.get(Bookmark,(p.id,body.topic_id)): db.add(Bookmark(profile_id=p.id,topic_id=body.topic_id))
    db.flush();return {'state':state_json(db,p.id,body.topic_id)}

@router.delete('/bookmarks/{topic_id}',response_model=StateResponse)
async def remove_bookmark(topic_id:str,db:DB,p:P):
    db.execute(delete(Bookmark).where(Bookmark.profile_id==p.id,Bookmark.topic_id==topic_id))
    return {'state':state_json(db,p.id,topic_id)}

@router.get('/bookmarks',response_model=CollectionOut)
async def bookmarks(db:DB,p:P,limit:int=Query(50,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    total=db.scalar(select(func.count()).select_from(Bookmark).where(Bookmark.profile_id==p.id))
    rows=db.scalars(select(Topic).join(Bookmark,Bookmark.topic_id==Topic.id).where(Bookmark.profile_id==p.id).order_by(Bookmark.created_at.desc(),Topic.id).offset(offset).limit(limit))
    return {'items':topics_json(db,rows,p.id),'total':total}

@router.get('/learning',response_model=CollectionOut)
async def learning(db:DB,p:P,status:Literal['learning','understood']='learning',limit:int=Query(20,ge=1,le=100),offset:int=Query(0,ge=0,le=100000)):
    # Stable title/id ordering; visit timestamps do not stand in for learning updates.
    query=select(Topic).join(TopicState,TopicState.topic_id==Topic.id).where(TopicState.profile_id==p.id,TopicState.learning==status)
    total=db.scalar(select(func.count()).select_from(query.subquery()))
    topics=db.scalars(query.order_by(Topic.title,Topic.id).offset(offset).limit(limit))
    return {'items':topics_json(db,topics,p.id),'total':total}

@router.get('/stats',response_model=StatsOut)
async def statistics(db:DB,p:P): return stats(db,p)

@router.get('/map',response_model=MapOut)
async def knowledge_map(db:DB,p:P,scope:Literal['all','explored']='all',discipline:str|None=None,q:str=Query('',max_length=100),root:str|None=Query(None,max_length=200),limit:int=Query(80,ge=5,le=150),depth:int=Query(1,ge=1,le=2)):
    return graph(db,p,scope,discipline,q,root,limit,depth)

@router.post('/ai/explain',response_model=AIExplainOut)
async def explain(body:ExplainBody,request:Request,db:DB,p:P):
    topic_or_404(db,body.topic_id);db.commit()
    return await request.app.state.ai.explain(p.id,body.topic_id,body.depth,body.language)

@router.post('/ai/chat',response_model=AIChatOut)
async def chat(body:ChatBody,request:Request,db:DB,p:P):
    topic_or_404(db,body.topic_id);db.commit()
    return await request.app.state.ai.chat(p.id,body.topic_id,body.message,body.depth)

@router.get('/ai/chat',response_model=ChatHistoryOut)
async def chat_history(db:DB,p:P,topic_id:str=Query(max_length=150),limit:int=Query(40,ge=1,le=100)):
    topic_or_404(db,topic_id)
    rows=list(db.scalars(select(ChatMessage).where(ChatMessage.profile_id==p.id,ChatMessage.topic_id==topic_id).order_by(ChatMessage.created_at.desc()).limit(limit)))
    return {'items':[{k:getattr(r,k) for k in ('role','content','created_at','source_ids','evidence_refs')} for r in reversed(rows)]}
