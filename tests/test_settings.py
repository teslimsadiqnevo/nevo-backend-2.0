from nevo.core.config import Settings


def test_plain_postgresql_url_uses_async_driver() -> None:
    settings = Settings(database_url="postgresql://postgres:postgres@localhost:5432/nevo")

    assert settings.database_url.startswith("postgresql+asyncpg://")


def test_explicit_async_driver_is_preserved() -> None:
    database_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/nevo"

    assert Settings(database_url=database_url).database_url == database_url
