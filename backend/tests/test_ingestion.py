import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select, func

from app.core.database import Base, make_engine, session_factory
from app.ingestion.adapters import CachedHTTP, MediaWikiAdapter, WikidataAdapter, OpenAlexAdapter, SourceError
from app.ingestion.collector import collect, normalize, resolve_raw_relations
from app.models import Topic, TopicSource, TopicRelation
from app.services.catalog import upsert_seed

ROOT = Path(__file__).resolve().parents[2]


def run(coro):
    return asyncio.run(coro)


def test_seed_has_60_traceable_topics_12_primary_disciplines_and_valid_typed_edges():
    payload = json.loads((ROOT/'data/seeds/topics.json').read_text())
    assert len(payload['topics']) == 60
    assert len({t['primary_discipline_id'] for t in payload['topics']}) == 12
    ids = {t['id'] for t in payload['topics']}
    assert len(ids) == 60
    for topic in payload['topics']:
        assert topic['summary'] and topic['original_summary']
        assert topic['quality_features']['summary_kind'] == 'ai_assisted_editorial_summary'
        assert topic['sources'][0]['url'].startswith('https://en.wikipedia.org/wiki/')
        assert len(topic['sources'][0]['excerpt'].split()) <= 25
        assert topic['sources'][0]['updated_at'] is None
    for relation in payload['relations']:
        assert relation['source_id'] in ids and relation['target_id'] in ids
        assert relation['type'] in {'fact','teaching'}
        assert relation['source_url'] and relation['direction'] == 'forward'


def test_seed_reimport_is_idempotent_and_source_topic_separate(tmp_path):
    import app.models  # register all tables
    engine = make_engine(f'sqlite:///{tmp_path}/data.db')
    Base.metadata.create_all(engine)
    payload = json.loads((ROOT/'data/seeds/topics.json').read_text())
    with session_factory(engine)() as db:
        assert upsert_seed(db, payload)['added'] == 60
        db.commit()
        assert upsert_seed(db, payload)['added'] == 0
        db.commit()
        assert db.scalar(select(func.count()).select_from(Topic)) == 60
        assert db.scalar(select(func.count()).select_from(TopicSource)) == 60
        assert db.scalar(select(func.count()).select_from(TopicRelation)) == 22
    engine.dispose()


def test_http_retry_429_cache_and_no_key_in_cache(tmp_path):
    requests = []
    def handler(req):
        requests.append(req)
        return httpx.Response(429, headers={'Retry-After':'0'}) if len(requests) == 1 else httpx.Response(200,json={'ok':True})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http = CachedHTTP(client=client,min_interval=0,cache_dir=tmp_path)
            assert await http.get('https://api.openalex.org/topics',{'search':'light','api_key':'SECRET'}) == {'ok':True}
            assert await http.get('https://api.openalex.org/topics',{'search':'light','api_key':'DIFFERENT'}) == {'ok':True}
    run(scenario())
    assert len(requests) == 2
    assert 'SECRET' not in ''.join(p.read_text() for p in tmp_path.iterdir())


def test_timeout_retry_is_bounded(monkeypatch):
    calls = []
    async def no_sleep(_): pass
    monkeypatch.setattr('app.ingestion.adapters.asyncio.sleep', no_sleep)
    def handler(req):
        calls.append(req)
        raise httpx.ReadTimeout('no response')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(SourceError) as error:
                await CachedHTTP(client=client,min_interval=0,retries=2).get('https://en.wikipedia.org/w/api.php')
            assert error.value.code == 'timeout'
    run(scenario())
    assert len(calls) == 3


@pytest.mark.parametrize('response,code',[(httpx.Response(200,text='<html>'), 'invalid_response'), (httpx.Response(200,json=[]),'invalid_response'), (httpx.Response(403),'authentication'), (httpx.Response(429),'rate_limited')])
def test_bad_external_responses_have_distinct_safe_codes(response,code):
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: response)) as client:
            with pytest.raises(SourceError) as error:
                await CachedHTTP(client=client,min_interval=0,retries=0).get('https://api.openalex.org/topics', {'api_key':'SECRET'})
            assert error.value.code == code
            assert 'SECRET' not in str(error.value)
    run(scenario())


def wiki_page(page_id=10, title='Entropy'):
    return {'pageid':page_id,'title':title,'extract':'Entropy is a thermodynamic state variable. ' * 4,'fullurl':'https://en.wikipedia.org/wiki/Entropy','pageprops':{'wikibase_item':'Q45003'},'revisions':[{'revid':40,'timestamp':'2026-01-01T00:00:00Z'}],'categories':[{'title':'Category:Thermodynamics'}],'langlinks':[{'lang':'zh','title':'熵'}]}


def test_mediawiki_metadata_revision_categories_cross_language():
    def handler(req):
        if req.url.params.get('list') == 'search':
            return httpx.Response(200,json={'query':{'search':[{'pageid':10,'title':'Entropy'}]}})
        return httpx.Response(200,json={'query':{'pages':[wiki_page()]}})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter=MediaWikiAdapter(CachedHTTP(client=client,min_interval=0), 'en')
            assert (await adapter.search('entropy'))[0]['id'] == '10'
            result=await adapter.detail('10')
            assert result['external_id']=='en:10' and result['entity_id']=='Q45003'
            assert result['version']=='40' and result['categories']==['Category:Thermodynamics']
            assert result['langlinks'][0]['lang']=='zh'
            item=normalize(result,'physics')
            assert item['id']=='entropy'  # known canonical source mapping, no fuzzy merge
            assert item['original_summary']==result['summary'].strip()
    run(scenario())


def test_wikidata_preserves_property_and_direction_excludes_deprecated():
    claim={'id':'Q10$test','mainsnak':{'datavalue':{'value':{'id':'Q20'}}},'references':[{'snaks':{}}]}
    entity={'labels':{'zh':{'value':'测试实体'}},'descriptions':{'zh':{'value':'用于测试的实体描述'}},'lastrevid':3,'claims':{'P279':[claim], 'P361':[{**claim,'rank':'deprecated'}], 'P999':[claim]}}
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,json={'entities':{'Q10':entity}}))) as client:
            result=await WikidataAdapter(CachedHTTP(client=client,min_interval=0)).detail('Q10')
            assert len(result['relations'])==1
            relation=result['relations'][0]
            assert relation['property_id']=='P279' and relation['direction']=='forward'
            assert relation['references'] and relation['type']=='fact'
            assert resolve_raw_relations(result['relations'], {'Q10':'a'})==[]
            resolved=resolve_raw_relations(result['relations'], {'Q10':'a','Q20':'b'})
            assert resolved[0]['source_id']=='a' and resolved[0]['target_id']=='b'
            with pytest.raises(ValueError):
                await WikidataAdapter(CachedHTTP(client=client)).detail('https://evil.test')
    run(scenario())


def test_openalex_work_metadata_reconstructs_abstract_not_fulltext():
    def handler(req):
        assert req.url.host == 'api.openalex.org'
        return httpx.Response(200,json={'id':'https://openalex.org/W1','display_name':'A work','doi':'https://doi.org/10.1/example','abstract_inverted_index':{'is':[1],'This':[0],'metadata':[2]},'language':'en','authorships':[{'author':{'display_name':'An author'}}]})
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            result=await OpenAlexAdapter(CachedHTTP(client=client,min_interval=0), api_key='SECRET').detail('W1')
            assert result['summary']=='This is metadata'
            assert result['original_url']=='https://doi.org/10.1/example'
            assert result['authors']==['An author']
            assert 'independent rights' in result['license']
            assert 'api_key' not in json.dumps(result)
    run(scenario())


def test_collection_partial_failure_checkpoint_and_resume():
    failed=[False]
    def handler(req):
        if req.url.params.get('list')=='search':
            return httpx.Response(200,json={'query':{'search':[{'pageid':10,'title':'Entropy'},{'pageid':11,'title':'A different topic'}]}})
        if req.url.params.get('pageids')=='11' and not failed[0]:
            failed[0]=True
            return httpx.Response(503)
        return httpx.Response(200,json={'query':{'pages':[wiki_page() if req.url.params.get('pageids')=='10' else wiki_page(11,'A different topic')]}})
    async def scenario():
        progress=[]
        async def save(state,topic,error):progress.append((state,topic,error))
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            http=CachedHTTP(client=client,min_interval=0,retries=0)
            first=await collect('wikipedia',['physics'],2,discipline_id='physics',language='en',http=http,on_progress=save)
            assert first['status']=='partial' and len(first['topics'])==1
            assert first['checkpoint']['pending']==['11']
            second=await collect('wikipedia',['physics'],2,discipline_id='physics',language='en',http=http,checkpoint=first['checkpoint'])
            assert second['status']=='complete' and second['checkpoint']['pending']==[]
            assert second['checkpoint']['done']==['10','11']
            assert any(x[2] and x[2]['code']=='upstream' for x in progress)
    run(scenario())


def test_online_source_update_preserves_curated_chinese_entry(tmp_path):
    engine = make_engine(f'sqlite:///{tmp_path}/preservation.db')
    Base.metadata.create_all(engine)
    payload = json.loads((ROOT/'data/seeds/topics.json').read_text())
    original = next(t for t in payload['topics'] if t['id']=='entropy')
    with session_factory(engine)() as db:
        upsert_seed(db,payload)
        db.commit()
        raw = {'platform':'wikipedia','external_id':'en:123','entity_id':'Q45003','title':'Entropy','summary':'New verified original English source summary.','url':'https://en.wikipedia.org/wiki/Entropy','language':'en','license':'CC BY-SA 4.0','fetched_at':'2026-11-17T00:00:00Z','version':'999','updated_at':None,'content_hash':'new-version'}
        upsert_seed(db,{'topics':[normalize(raw,'physics')]},data_kind='online')
        db.commit()
        topic = db.get(Topic,'entropy')
        assert topic.title == '熵'
        assert topic.summary == original['summary']
        assert topic.data_kind == 'seed'
        sources=list(db.scalars(select(TopicSource).where(TopicSource.topic_id=='entropy')))
        assert len(sources)==2 and any(s.version=='999' for s in sources)
    engine.dispose()


def test_upstream_openalex_ai_description_is_explicit_in_product_metadata(app,catalog):
    import copy
    item=copy.deepcopy(catalog['topics'][0])
    item['id']='synthetic-openalex-topic'
    item['sources'][0].update(id='synthetic-openalex-source',platform='openalex',external_id='T999999')
    with app.state.Session() as db:
        upsert_seed(db,{'topics':[item]},data_kind='online')
        db.commit()
        saved=db.get(Topic,item['id'])
        assert saved.quality_features['upstream_ai'] is True
        assert '上游 AI' in saved.quality_features['summary_label']
