import copy
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
import pytest

from app.models import Profile,Topic,TopicState,Impression,DailyRecommendation
from app.recommendation.engine import surprise,novelty,novelty_basis,recommend
from app.recommendation.semantic import similarity
from app.services.discovery import history_snapshot
from test_recommendation import library


def test_bilingual_semantics_distinguishes_related_and_near_duplicate():
    swarm={'title':'群体智能'};ant={'title':'蚁群如何完成集体决策'};distributed={'title':'分布式系统中的涌现行为'}
    assert similarity(swarm,ant,True)>.82>similarity(swarm,ant,False)
    assert .3<similarity(swarm,distributed,True)<.82
    assert similarity({'title':'陌生词甲'},{'title':'陌生词乙'},True)==similarity({'title':'陌生词甲'},{'title':'陌生词乙'},False)
    assert swarm=={'title':'群体智能'}


def test_name_application_connection_and_forgotten_are_distinct():
    h={'name_only_ids':['x'],'concept_only_ids':['y'],'connection_gap_ids':['z'],'forgotten_ids':['w'],'explored_ids':['v']}
    assert [novelty_basis(i,h) for i in ('x','y','z','w','v','other')]==['name_only','application_gap','connection_gap','self_forgotten','encountered_not_proven_understood','no_record_of_contact']
    candidates=library();result=recommend(candidates,{'known_ids':[c['id'] for c in candidates]})
    assert result['constraints']['achieved']['new_opportunities']==0


def test_long_term_coverage_changes_rank_without_excluding_familiar_disciplines():
    candidates=library()
    history={'coverage_windows':{'30':{'disciplines':{'d0':100},'subfields':{}}},'familiar_disciplines':['d0']}
    first=candidates[0];other={**first,'primary_discipline_id':'d5'}
    assert novelty(other,history)>novelty(first,history)
    all_familiar={'familiar_disciplines':sorted({t['primary_discipline_id'] for t in candidates})}
    assert len(recommend(candidates,all_familiar)['items'])==5


@pytest.mark.parametrize('strength',['gentle','cross','far'])
def test_surprise_never_relaxes_quality_and_reduces_recent_repeats(strength):
    candidates=library();history={'recent_ids':[candidates[0]['id']]}
    candidates[0]['quality_score']=.05
    for seed in range(6):
        result=surprise(candidates,history,strength=strength,seed=seed)
        assert len(result['items'])==1 and result['items'][0]['topic_id']!=candidates[0]['id']
        assert result['items'][0]['features']['quality']>=.4
    assert surprise(candidates,history,strength=strength,seed=7)==surprise(candidates,history,strength=strength,seed=7)


def test_surprise_strength_changes_actual_weights_and_history_free_is_invariant():
    candidates=library();a=surprise(candidates,{},strength='gentle');b=surprise(candidates,{},strength='far')
    assert a['items'][0]['feature_evidence']['weights']!=b['items'][0]['feature_evidence']['weights']
    hidden={'explored_ids':[t['id'] for t in candidates],'recent_ids':[t['id'] for t in candidates],'skipped_ids':[t['id'] for t in candidates]}
    first=surprise(candidates,hidden,history_free=True,seed=17)
    assert first==surprise(candidates,{},history_free=True,seed=17)
    assert first['history_snapshot']=={} and first['constraints']['achieved']['new_opportunities'] is None


def test_surprise_api_idempotency_no_implicit_exploration_and_source_gate(client,app):
    body={'strength':'far','history_free':False,'idempotency_key':'surprise-idempotent-001'}
    a=client.post('/api/discover/surprise',json=body);assert a.status_code==200
    item=a.json()['item'];assert item['topic']['content_status']=='PUBLISHED' and item['topic']['sources']
    assert a.json()['id']==client.post('/api/discover/surprise',json=body).json()['id']
    assert client.get('/api/stats').json()['explored_count']==0
    with app.state.Session() as db:
        assert list(db.scalars(select(Impression)))==[]
    assert client.post('/api/discover/surprise',json={**body,'strength':'gentle'}).status_code==409


def test_explicit_feedback_and_7_30_90_windows_are_persisted(client,app):
    pid=client.get('/api/profile').json()['id'];client.get('/api/topics/t0')
    for i,action in enumerate(('name_only','concept_only','connections_unknown','forgotten','revisit','worthwhile')):
        assert client.post('/api/topics/t0/feedback',json={'action':action,'idempotency_key':f'context-change-{i:03}'}).status_code==200
    state=client.get('/api/topics/t0').json()['state']
    assert state['familiarity']=='forgotten' and state['learning']=='none' and state['worthwhile'] is True and state['revisit_at']
    with app.state.Session() as db:
        stored=db.get(TopicState,(pid,'t0'));stored.first_explored_at=(datetime.now(timezone.utc)-timedelta(days=20)).isoformat();db.commit()
        h=history_snapshot(db,db.get(Profile,pid))
        assert h['coverage_windows']['7']['first_explorations']==0
        assert h['coverage_windows']['30']['first_explorations']==h['coverage_windows']['90']['first_explorations']==1
        assert h['forgotten_ids']==['t0']
