import copy
import json
import pytest
from sqlalchemy import select,func

from app.core.config import ROOT
from app.models import Topic,TopicSource,TopicState,IngestionJob
from app.services.catalog import upsert_seed
from app.services.content import process_topic,chinese
from app.ingestion.processing import process_batch
from app.recommendation import recommend


def test_import_publishes_only_locally_qualified_content_and_rechecks_sources(app):
    with app.state.Session() as db:
        t=db.get(Topic,'t0')
        assert t.content_status=='PUBLISHED'
        assert t.content_checks['expert_reviewed'] is False
        assert t.content_checks['facts_verified'] is False
        attempts=t.processing_attempts
        assert process_topic(db,t)['skipped']
        assert t.processing_attempts==attempts
        db.get(TopicSource,'s0').excerpt=''
        db.flush()
        result=process_topic(db,t)
        assert not result['skipped'] and result['status']=='RAW'
        assert 'NO_SOURCE_EXCERPT' in result['issues']


def test_english_prefix_does_not_pass_chinese_material_check():
    assert not chinese('英文原始资料（未自动翻译）：'+'Research cluster metadata '*30)
    assert chinese('图论用节点表示对象，用边表示关系。')


def test_reviewed_can_be_published_idempotently_without_another_generation(app):
    with app.state.Session() as db:
        topic=db.get(Topic,'t0')
        assert process_topic(db,topic,publish=False,force=True)['status']=='REVIEWED'
        assert process_topic(db,topic,publish=True)['status']=='PUBLISHED'
        assert process_topic(db,topic)['skipped']


def test_ai_cannot_publish_metadata_only_even_after_translation(app):
    with app.state.Session() as db:
        t=db.get(Topic,'t0');s=db.get(TopicSource,'s0')
        s.platform='openalex';s.external_id='T10482';db.flush()
        result=process_topic(db,t,force=True)
        assert result['status']=='ENRICHED'
        assert 'METADATA_ONLY' in result['issues']


def test_generic_text_is_blocked_not_replaced_with_invented_copy(app):
    with app.state.Session() as db:
        t=db.get(Topic,'t0');t.value='探索这个领域的无限可能'
        result=process_topic(db,t)
        assert result['status']!='PUBLISHED' and 'GENERIC_COPY' in result['issues']


def test_unpublished_cannot_fill_recommendation_slots(client,app):
    with app.state.Session() as db:
        for t in db.scalars(select(Topic)): t.content_status='EXTRACTED'
        db.commit()
    result=client.get('/api/discover/today').json()
    assert result['items']==[]
    assert 'requested_count' in result['constraints']['relaxed']


def test_source_refresh_reprocesses_without_deleting_learning(client,app,catalog):
    client.get('/api/topics/t0')
    client.post('/api/topics/t0/feedback',json={'action':'understood','idempotency_key':'content-learning-001'})
    updated=copy.deepcopy(catalog);updated['topics'][0]['sources'][0]['excerpt']=''
    with app.state.Session() as db:
        upsert_seed(db,updated);db.commit()
        assert db.get(Topic,'t0').content_status=='RAW'
        assert db.scalar(select(TopicState).where(TopicState.topic_id=='t0')).learning=='understood'


@pytest.mark.asyncio
async def test_bounded_jobs_are_persistent_idempotent_and_resumable(app):
    result=await process_batch(app.state.Session,app.state.settings,limit=3)
    assert result['status']=='complete' and len(result['done'])==3 and result['ai_calls']==0
    resumed=await process_batch(app.state.Session,app.state.settings,resume=result['job_id'])
    assert resumed['done']==result['done']
    next_batch=await process_batch(app.state.Session,app.state.settings,limit=3,after_id=result['last_topic_id'])
    assert not set(next_batch['done'])&set(result['done'])
    with app.state.Session() as db:
        job=db.get(IngestionJob,result['job_id']);job.status='partial';job.checkpoint={**job.checkpoint,'done':job.checkpoint['done'][:-1]};db.commit()
    recovered=await process_batch(app.state.Session,app.state.settings,resume=result['job_id'])
    assert recovered['status']=='complete' and recovered['done']==result['done']
    with pytest.raises(ValueError): await process_batch(app.state.Session,app.state.settings,limit=301)
    with pytest.raises(ValueError): await process_batch(app.state.Session,app.state.settings,enrich_ai=True,max_ai_calls=1,max_reserved_tokens=1000)


@pytest.mark.asyncio
async def test_invalid_generation_fails_safely_and_can_recover(app):
    class Broken:
        async def generate(self,messages): return {'one_sentence':'伪造内容'},None,1
    settings=app.state.settings.model_copy(update={'llm_api_key':'dummy','llm_retries':0,'llm_max_output_tokens':200,'llm_context_chars':1000})
    with app.state.Session() as db:
        t=db.get(Topic,'t0');t.question='';db.commit()
    failed=await process_batch(app.state.Session,settings,limit=1,enrich_ai=True,max_ai_calls=1,max_reserved_tokens=20000,provider=Broken())
    assert failed['status']=='partial' and failed['ai_calls']==1
    with app.state.Session() as db:
        assert db.get(Topic,'t0').processing_error=='CONTENT_PROCESSING_FAILED'
        db.get(Topic,'t0').question='如何理解这个测试概念？';db.commit()
    recovered=await process_batch(app.state.Session,settings,resume=failed['job_id'],enrich_ai=True,max_ai_calls=1,max_reserved_tokens=20000,provider=Broken())
    assert recovered['status']=='complete' and recovered['ai_calls']==1


@pytest.mark.asyncio
async def test_valid_enrichment_is_readable_and_resume_preserves_call_spending(app,client):
    class Good:
        calls=0
        async def generate(self,messages):
            self.calls+=1;context=json.loads(messages[-1]['content']);piece=context['evidence'][0]
            return {'one_sentence':'这是用于测试内容加工的合成概念。','explanation':'这是用于测试内容加工的合成概念，其内容仅用于验证中文阅读入口。','entry_example':'','core_question':'如何核查合成资料？','value':'练习核对引用片段。','evidence_refs':[{'source_id':piece['source_id'],'quote':piece['excerpt']}]},None,1
    provider=Good();settings=app.state.settings.model_copy(update={'llm_api_key':'dummy','llm_retries':0,'llm_max_output_tokens':200,'llm_context_chars':1000})
    with app.state.Session() as db:
        for tid in ('t0','t1'):
            t=db.get(Topic,tid);t.summary=t.question=t.value='';process_topic(db,t)
        db.commit()
    first=await process_batch(app.state.Session,settings,limit=2,enrich_ai=True,max_ai_calls=1,max_reserved_tokens=20000,provider=provider)
    # Topic sorting is deterministic: t0, t1 before t10.
    assert first['status']=='partial' and first['ai_calls']==1 and provider.calls==1
    resumed=await process_batch(app.state.Session,settings,resume=first['job_id'],enrich_ai=True,max_ai_calls=2,max_reserved_tokens=20000,provider=provider)
    assert resumed['status']=='complete' and resumed['ai_calls']==2 and provider.calls==2
    detail=client.get('/api/topics/t0').json()
    assert detail['summary'].startswith('这是用于测试内容加工') and detail['question']=='如何核查合成资料？'
    assert detail['content_status']=='PUBLISHED' and 'AI 辅助' in detail['quality_features']['summary_label']


def test_real_archived_300_are_processed_and_quarantined_without_invented_chinese(app):
    seed=json.loads((ROOT/'data/seeds/topics.json').read_text())
    online=json.loads((ROOT/'data/online/openalex.json').read_text())
    with app.state.Session() as db:
        upsert_seed(db,seed)
        upsert_seed(db,online,data_kind='online')
        db.commit()
        rows=list(db.scalars(select(Topic).where(Topic.data_kind=='online')))
        assert len(rows)==300
        assert all(t.content_status=='EXTRACTED' for t in rows)
        assert all('METADATA_ONLY' in t.content_checks['issues'] for t in rows)
        assert all('NO_CHINESE_INTRO' in t.content_checks['issues'] for t in rows)
        assert all(not t.content_checks['facts_verified'] for t in rows)
        assert db.scalar(select(func.count()).select_from(Topic).where(Topic.data_kind=='seed',Topic.content_status=='PUBLISHED'))==78
        assert upsert_seed(db,online,data_kind='online')['added']==0
