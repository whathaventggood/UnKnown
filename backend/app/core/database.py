from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

class Base(DeclarativeBase):
    pass

def make_engine(url):
    engine = create_engine(url, hide_parameters=True, connect_args={'check_same_thread': False, 'timeout': 20} if url.startswith('sqlite') else {})
    if url.startswith('sqlite'):
        @event.listens_for(engine, 'connect')
        def pragmas(conn, _):
            cursor = conn.cursor()
            cursor.execute('PRAGMA foreign_keys=ON')
            cursor.execute('PRAGMA journal_mode=WAL')
            cursor.execute('PRAGMA busy_timeout=20000')
            cursor.close()
    return engine

def session_factory(engine):
    return sessionmaker(engine, expire_on_commit=False)
