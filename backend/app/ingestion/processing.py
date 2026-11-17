"""Resumable, bounded content jobs. Remote enrichment requires explicit opt-in."""
import json
import re
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select

from app.models import IngestionJob, Topic, now
from app.services.content import process_topic
from app.ai.service import AIService, EvidenceRef, evidence_bundle, SYSTEM
from app.ai.provider import ProviderError


class Intro(BaseModel):
    model_config=ConfigDict(extra='forbid')
    one_sentence:str=Field(min_length=6,max_length=300)
    explanation:str=Field(min_length=10,max_length=2000)
    entry_example:str=Field(default='',max_length=800)
    core_question:str=Field(min_length=2,max_length=300)
    value:str=Field(min_length=2,max_length=500)
    evidence_refs:list[EvidenceRef]=Field(min_length=1,max_length=12)


async def process_batch(factory,settings,*,limit=100,data_kind=None,resume=None,publish=True,force=False,enrich_ai=False,max_ai_calls=0,max_reserved_tokens=0,provider=None):
    if not 1<=limit<=300 or not 0<=max_ai_calls<=20 or not 0<=max_reserved_tokens<=100000:
        raise ValueError('批次上限 1..300；AI 调用上限 0..20；Token 预留上限 100000。')
    if enrich_ai and (not settings.llm_api_key or not max_ai_calls or not max_reserved_tokens or provider is None):
        raise ValueError('AI 加工需服务端 Key、Provider 及显式非零调用/Token 上限。')
    with factory() as db:
        if resume:
            job=db.get(IngestionJob,resume)
            if not job or job.source!='content_pipeline': raise ValueError('没有找到对应内容加工任务。')
            params=job.params
            # Resume never opts into a paid call implicitly.
            if params['enrich_ai']!=enrich_ai: raise ValueError('恢复时必须明确使用原任务的 AI 开关。')
            if job.status=='complete': return {'job_id':job.id,'status':job.status,**job.checkpoint}
            publish,force=params['publish'],params['force']
        else:
            query=select(Topic.id).order_by(Topic.id)
            if data_kind: query=query.where(Topic.data_kind==data_kind)
            ids=list(db.scalars(query.limit(limit)))
            job=IngestionJob(source='content_pipeline',params={'ids':ids,'publish':publish,'force':force,'enrich_ai':enrich_ai},checkpoint={'done':[],'results':{},'ai_calls':0,'reserved_tokens':0})
            db.add(job);db.flush()
        job.status='running';job.updated_at=now();job_id=job.id;params=job.params;checkpoint=dict(job.checkpoint)
        db.commit()
    service=AIService(settings,factory,provider) if enrich_ai else None
    for tid in params['ids']:
        if tid in checkpoint['done']: continue
        try:
            with factory() as db:
                topic=db.get(Topic,tid)
                if not topic: raise ValueError('主题已不存在')
                result=process_topic(db,topic,publish=publish,force=force)
                evidence,sources,_=evidence_bundle(db,topic,settings.llm_context_chars)
                needs_ai=topic.content_status!='PUBLISHED' and not (result['skipped'] and topic.content_intro.get('origin')=='ai_assisted')
                db.commit()
            if enrich_ai and needs_ai and evidence:
                if checkpoint['ai_calls']>=max_ai_calls: raise ProviderError('PIPELINE_CALL_LIMIT','已达到此批次 AI 调用上限，可恢复。')
                shape={k:'中文，资料不足留空且不补造' for k in ('one_sentence','explanation','entry_example','core_question','value')}
                shape['evidence_refs']=[{'source_id':sources[0]['id'],'quote':'逐字引用原文至少8字符'}]
                context=json.dumps({'topic_id':tid,'evidence':evidence,'required_json_shape':shape},ensure_ascii=False)
                reservation=(len(context.encode('utf-8'))+settings.llm_max_output_tokens+1000)*(settings.llm_retries+1)
                if checkpoint['reserved_tokens']+reservation>max_reserved_tokens: raise ProviderError('PIPELINE_TOKEN_LIMIT','此批次 Token 预留上限不足，可恢复。')
                # Count before sending; crashes cannot reset local spending limits.
                usage_id=service.reserve(None,context)
                checkpoint['ai_calls']+=1;checkpoint['reserved_tokens']+=reservation
                with factory() as db:
                    job=db.get(IngestionJob,job_id);job.checkpoint=json.loads(json.dumps(checkpoint));db.commit()
                usage=None;attempts=0
                try:
                    raw,usage,attempts=await provider.generate([{'role':'system','content':SYSTEM},{'role':'user','content':context}])
                    intro=Intro.model_validate(raw).model_dump()
                    if re.search(r'https?://|www\.',json.dumps(intro),re.I): raise ValueError('生成了来源 URL')
                    intro.update(origin='ai_assisted',evidence_status='located_not_entailment_verified')
                    with factory() as db:
                        topic=db.get(Topic,tid)
                        result=process_topic(db,topic,publish=publish,force=True,intro=intro)
                        if 'INVALID_INTRO_EVIDENCE' in result['issues']: raise ValueError('生成内容的引用无法定位')
                        db.commit()
                    service.finish_usage(usage_id,'success',usage,attempts)
                except BaseException as exc:
                    service.finish_usage(usage_id,'failed',usage or getattr(exc,'usage',None),attempts or getattr(exc,'attempts',0))
                    raise
            checkpoint['done'].append(tid);checkpoint['results'][tid]=result
        except Exception as exc:
            code=exc.code if isinstance(exc,ProviderError) else 'CONTENT_PROCESSING_FAILED'
            with factory() as db:
                topic=db.get(Topic,tid)
                if topic: topic.processing_error=code
                job=db.get(IngestionJob,job_id);job.errors=(job.errors+[{'topic_id':tid,'code':code}])[-300:];db.commit()
            if code in ('PIPELINE_CALL_LIMIT','PIPELINE_TOKEN_LIMIT','AI_BUDGET'): break
        with factory() as db:
            job=db.get(IngestionJob,job_id);job.checkpoint=json.loads(json.dumps(checkpoint));job.processed=len(checkpoint['done']);job.updated_at=now();db.commit()
    with factory() as db:
        job=db.get(IngestionJob,job_id);job.checkpoint=checkpoint;job.processed=len(checkpoint['done']);job.failed=len(params['ids'])-job.processed
        job.status='complete' if job.failed==0 else 'partial';job.updated_at=now();db.commit()
        return {'job_id':job.id,'status':job.status,**checkpoint}
