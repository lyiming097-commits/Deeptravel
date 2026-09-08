from backend.app.config import Settings


def test_render_postgres_url_uses_asyncpg() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql://render_user:secret@example.com/deeptravel",
    )

    assert settings.database_url == (
        "postgresql+asyncpg://render_user:secret@example.com/deeptravel"
    )


def test_existing_async_database_driver_is_preserved() -> None:
    url = "postgresql+asyncpg://local_user@127.0.0.1/deeptravel"
    settings = Settings(_env_file=None, database_url=url)

    assert settings.database_url == url
