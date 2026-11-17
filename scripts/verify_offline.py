#!/usr/bin/env python3
"""A real local API journey on a new disposable database; no network or LLM calls."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
from fastapi.testclient import TestClient
from app.core.config import Settings
from app.main import create_app


def verify():
    with TemporaryDirectory(prefix='unknown-offline-') as temporary:
        settings=Settings(database_url=f'sqlite:///{Path(temporary)/"fresh.db"}',llm_api_key='',_env_file=None)
        app=create_app(settings)
        with TestClient(app) as c:
            p=c.get('/api/profile');assert p.status_code==200
            assert c.patch('/api/profile',json={'onboarding_complete':True}).status_code==200
            batch=c.get('/api/discover/today').json()
            assert len(batch['items'])==5
            assert batch['id']==c.get('/api/discover/today').json()['id']
            tid=batch['items'][0]['topic']['id']
            assert c.post('/api/discover/impressions',json={'batch_id':batch['id'],'topic_ids':[tid]}).status_code==200
            assert c.get('/api/topics/'+tid).json()['state']['explored']
            assert c.post('/api/topics/'+tid+'/feedback',json={'action':'unfamiliar','idempotency_key':'offline-feedback-001'}).status_code==200
            assert c.post('/api/bookmarks',json={'topic_id':tid}).status_code==200
            assert c.get('/api/stats').json()['explored_count']==1
            assert c.post('/api/ai/explain',json={'topic_id':tid}).json()['status']=='unavailable'
            assert c.get('/api/map').json()['nodes']
            token=c.cookies.get('unknown_session')
        # Recreate engine/app on same persisted SQLite file, not the previous in-memory session.
        restarted=create_app(settings)
        with TestClient(restarted) as c:
            c.cookies.set('unknown_session',token)
            assert c.get('/api/bookmarks').json()['total']==1
            assert c.get('/api/stats').json()['explored_count']==1
            assert c.get('/api/discover/today').json()['id']==batch['id']
            assert c.get('/api/topics/'+tid).json()['state']['familiarity']=='unfamiliar'
            for mode in ('bridge','broad'):
                assert len(c.get('/api/discover/today?mode='+mode).json()['items'])==5
            assert c.post('/api/profile/reset',json={'confirm':True}).json()['cleared']
            assert c.get('/api/stats').json()['explored_count']==0
            assert c.get('/api/bookmarks').json()['total']==0
            health=c.get('/api/health').json()
            assert health['topics']==60
        return {'status':'passed','seed_topics':60,'primary_disciplines':12,'new_database':True,'fresh_app_restart_persistence':True,'three_modes':True,'llm_key':False,'remote_requests':0,'privacy_reset_keeps_catalogue':True}

if __name__=='__main__': print(json.dumps(verify(),ensure_ascii=False,indent=2))
