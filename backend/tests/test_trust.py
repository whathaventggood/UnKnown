"""Security regressions and real archived source passages; no paid/network calls."""
import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.ai.provider import ProviderError
from app.ai.service import evidence_bundle, validate_output
from app.core.config import ROOT, Settings
from app.models import Topic, TopicSource, TopicEvent
from test_ai import explanation


def test_summary_never_becomes_independent_source_evidence(app):
    with app.state.Session() as db:
        topic=db.get(Topic,'t0')
        source=db.get(TopicSource,'s0')
        source.excerpt=''
        db.add(TopicSource(id='empty-second',topic_id='t0',platform='test',external_id='second',title='Empty',url='https://example.org/empty',excerpt=''))
        db.flush()
        assert topic.summary and topic.original_summary
        evidence,sources,_=evidence_bundle(db,topic,1000)
        assert evidence==sources==[]
        # A missing first excerpt must not hide a later usable excerpt.
        db.get(TopicSource,'empty-second').excerpt='Actual independently stored passage.'
        evidence,sources,_=evidence_bundle(db,topic,1000)
        assert [e['source_id'] for e in evidence]==['empty-second']
        assert topic.summary not in json.dumps(evidence,ensure_ascii=False)


@pytest.fixture
def real_passages():
    topics=json.loads((ROOT/'data/seeds/topics.json').read_text())['topics']
    return [{'source_id':t['sources'][0]['id'],'excerpt':t['sources'][0]['excerpt'],'evidence_type':'external_excerpt'} for t in topics[:2]]


def located_output(piece,kind='fact',text='图由顶点和边构成。'):
    raw=explanation(piece['source_id'])
    raw['claims']=[{'text':text,'kind':kind,'source_ids':[piece['source_id']],'evidence_refs':[{'source_id':piece['source_id'],'quote':piece['excerpt']}]}]
    return raw


def test_real_graph_passage_is_located_without_claiming_verification(real_passages):
    raw=located_output(real_passages[1])
    result=validate_output(raw,{p['source_id'] for p in real_passages},evidence=real_passages)
    assert result['claims'][0]['support_status']=='located_not_verified'
    assert result['claims'][0]['evidence_refs'][0]['quote']=='A graph consists of vertices connected by edges.'


def test_valid_source_id_cannot_carry_quote_from_unrelated_source(real_passages):
    raw=located_output(real_passages[0])
    raw['claims'][0]['evidence_refs'][0]['quote']=real_passages[1]['excerpt']
    with pytest.raises(ProviderError):
        validate_output(raw,{p['source_id'] for p in real_passages},evidence=real_passages)


def test_irrelevant_fact_even_with_located_quote_is_not_marked_verified(real_passages):
    raw=located_output(real_passages[1],text='月球由奶酪构成。')
    result=validate_output(raw,{p['source_id'] for p in real_passages},evidence=real_passages)
    assert result['claims'][0]['support_status']=='located_not_verified'
    # Deliberately exposes the limit of structural checks; NOT an entailment test.


def test_uncertain_and_analogy_remain_distinct(real_passages):
    raw=located_output(real_passages[0],kind='uncertain',text='仅作为待核查的解释。')
    raw['claims'].append({'text':'用路口和道路帮助理解图。','kind':'analogy','source_ids':[]})
    result=validate_output(raw,{p['source_id'] for p in real_passages},evidence=real_passages)
    assert [c['kind'] for c in result['claims']]==['uncertain','analogy']
    assert result['claims'][1]['support_status']=='teaching_analogy'


def test_conflicting_claims_do_not_gain_a_verified_label(real_passages):
    # Controlled contradictory claims over archived real passages, not fabricated
    # source quotations. The server retains uncertainty instead of choosing truth.
    raw=located_output(real_passages[0],kind='uncertain',text='条件概率可以反向推断。')
    other=located_output(real_passages[1],kind='uncertain',text='条件概率不能反向推断。')['claims'][0]
    raw['claims'].append(other)
    result=validate_output(raw,{p['source_id'] for p in real_passages},evidence=real_passages)
    assert all(c['support_status']=='located_not_verified' for c in result['claims'])


@pytest.mark.parametrize('path,method', [('/api/bookmarks','post'),('/api/profile','patch'),('/api/profile/reset','post'),('/api/topics/t0','get'),('/api/discover/today','get')])
def test_absent_origin_and_custom_header_fails_closed(app,path,method):
    with TestClient(app) as browser:
        response=getattr(browser,method)(path)
        assert response.status_code==403
        assert response.json()['error']['code']=='CSRF_HEADER_REQUIRED'


@pytest.mark.parametrize('headers', [
    {'Origin':'null'}, {'Origin':'https://evil.example'},
    {'Referer':'https://evil.example/form'}, {'Sec-Fetch-Site':'cross-site'},
    {'Origin':'https://good.example.evil.example'},
    {'Origin':'https://evil.example','X-Forwarded-Host':'evil.example','X-Forwarded-Proto':'https'},
])
def test_foreign_sources_cannot_bypass_with_custom_header(client,headers):
    response=client.post('/api/bookmarks',json={'topic_id':'t0'},headers=headers)
    assert response.status_code==403


def test_json_and_cors_boundary(client):
    assert client.post('/api/bookmarks',content='topic_id=t0',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==415
    for origin,expected in [('http://127.0.0.1:5173',200),('https://evil.example',400)]:
        r=client.options('/api/bookmarks',headers={'Origin':origin,'Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'X-Unknown-Request,Content-Type'})
        assert r.status_code==expected
        if expected==200: assert r.headers['access-control-allow-origin']==origin
    assert client.get('/api/profile').headers['cache-control']=='no-store'


def test_secure_cookie_and_exact_origins_required():
    for values in ({'cookie_samesite':'none'}, {'cors_origins':['*']}, {'cors_origins':['https://example.org/path']}, {'public_origin':'null'}):
        with pytest.raises(ValidationError): Settings(_env_file=None,**values)
    assert Settings(cookie_secure=True,cookie_samesite='none',_env_file=None).cookie_secure


def test_explicit_public_origin_behind_proxy(app,client):
    app.state.settings.public_origin='https://unknown.example'
    assert client.post('/api/bookmarks',json={'topic_id':'t0'},headers={'Origin':'https://unknown.example'}).status_code==200
    assert client.post('/api/bookmarks',json={'topic_id':'t0'},headers={'Origin':'http://testserver','X-Forwarded-Proto':'https'}).status_code==403
