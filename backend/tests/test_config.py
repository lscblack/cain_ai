from app.core import config as config_module


def test_settings_reads_env_and_parses_cors(monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@localhost:5432/kai")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")

    # fresh instance (not the cached singleton)
    settings = config_module.Settings()

    assert settings.app_secret_key == "test-secret"
    assert settings.access_token_expire_minutes == 60
    assert settings.cors_origins == ["http://a.test", "http://b.test"]
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_get_settings_is_cached():
    # NOTE: do not importlib.reload(config_module): that rebinds get_settings to a new
    # lru_cache, so modules that imported the old function keep a different Settings
    # singleton than later tests monkeypatch (order-dependent failures).
    a = config_module.get_settings()
    b = config_module.get_settings()
    assert a is b
