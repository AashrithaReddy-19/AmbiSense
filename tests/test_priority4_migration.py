from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine,inspect,text

def test_priority4_auth_upgrade_from_priority4_schema(tmp_path,monkeypatch):
    from backend.app.config import get_settings
    original_url=get_settings().database_url;database=tmp_path/'priority4.db';url=f"sqlite:///{database.as_posix()}";engine=create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, email VARCHAR(255) NOT NULL, display_name VARCHAR(160) NOT NULL, role VARCHAR(24) NOT NULL, active BOOLEAN NOT NULL, created_at DATETIME NOT NULL)"))
    monkeypatch.setenv('DATABASE_URL',url)
    get_settings.cache_clear();config=Config('alembic.ini');command.stamp(config,'20260823_priority4');command.upgrade(config,'head')
    assert {'password_hash','token_version'}<=set(inspect(engine).get_columns('users')[index]['name'] for index in range(len(inspect(engine).get_columns('users'))))
    with engine.connect() as connection:assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()=='20260826_pipeline_jobs'
    monkeypatch.setenv('DATABASE_URL',original_url);get_settings.cache_clear();get_settings()
