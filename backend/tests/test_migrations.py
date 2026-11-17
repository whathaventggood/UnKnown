from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.core.config import ROOT
from app.core.database import make_engine


def test_upgrade_populated_initial_schema_preserves_topic_profile_bookmark(tmp_path):
    url=f'sqlite:///{tmp_path}/legacy.db'
    cfg=Config(str(ROOT/'backend/alembic.ini'));cfg.attributes['database_url']=url
    command.upgrade(cfg,'0001')
    engine=make_engine(url)
    with engine.begin() as c:
        c.execute(text("INSERT INTO disciplines VALUES ('legacy-d','历史领域','#123456','legacy','1')"))
        c.execute(text("INSERT INTO topics (id,title,original_title,summary,original_summary,language,primary_discipline_id,subfield,question,value,quality_score,quality_features,content_version,data_kind) VALUES ('legacy-topic','历史主题','','摘要','','zh','legacy-d','细分领域','','',0.8,'{}','1','seed')"))
        c.execute(text("INSERT INTO anonymous_profiles (id,token_hash,timezone,familiar_disciplines,depth,intensity,broad_use_history,onboarding_complete,created_at) VALUES ('legacy-profile','hashed-token','Asia/Shanghai','[]','beginner',0.7,1,1,'2026-11-17T00:00:00+00:00')"))
        c.execute(text("INSERT INTO bookmarks VALUES ('legacy-profile','legacy-topic','2026-11-17T00:00:00+00:00')"))
        c.execute(text("INSERT INTO user_topic_states (profile_id,topic_id,familiarity,learning,first_explored_at,last_visited_at,skipped_until) VALUES ('legacy-profile','legacy-topic','unfamiliar','understood','2026-11-17T00:00:00+00:00','2026-11-17T00:00:00+00:00',NULL)"))
        c.execute(text("INSERT INTO topic_sources (id,topic_id,platform,external_id,url,title,language,license,fetched_at,updated_at,version,content_hash,excerpt,metadata_json) VALUES ('legacy-source','legacy-topic','test','legacy','https://example.org/legacy','Legacy','en','test-only','2026-11-17T00:00:00+00:00',NULL,NULL,'hash','Archived source passage','{}')"))
    command.upgrade(cfg,'head')
    with engine.connect() as c:
        row=c.execute(text('SELECT t.title,s.name,t.subfield_id FROM topics t JOIN subfields s ON t.subfield_id=s.id')).one()
        assert row[0]=='历史主题' and row[1]=='细分领域' and row[2].startswith('subfield:')
        assert c.execute(text('SELECT count(*) FROM bookmarks')).scalar()==1
        assert c.execute(text('SELECT familiarity,learning,revisit_at FROM user_topic_states')).one()==('unfamiliar','understood',None)
        assert c.execute(text('SELECT excerpt FROM topic_sources')).scalar()=='Archived source passage'
        assert c.execute(text('PRAGMA foreign_key_check')).fetchall()==[]
    command.upgrade(cfg,'head')
    from alembic.migration import MigrationContext
    from alembic.autogenerate import compare_metadata
    from app.core.database import Base
    with engine.connect() as c:
        assert c.execute(text('SELECT count(*) FROM bookmarks')).scalar()==1
        assert compare_metadata(MigrationContext.configure(c),Base.metadata)==[]
    engine.dispose()
