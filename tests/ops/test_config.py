from nevo.ops.config import OpsSettings


def test_self_ping_url_falls_back_to_render_external_url(
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPS_SELF_PING_URL", raising=False)
    monkeypatch.setenv(
        "RENDER_EXTERNAL_URL",
        "https://nevo-backend.onrender.com",
    )

    settings = OpsSettings(_env_file=None)

    assert settings.self_ping_url == "https://nevo-backend.onrender.com"


def test_explicit_self_ping_url_overrides_render_external_url(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://from-render.example")
    monkeypatch.setenv("OPS_SELF_PING_URL", "https://explicit.example")

    settings = OpsSettings(_env_file=None)

    assert settings.self_ping_url == "https://explicit.example"


def test_self_ping_url_defaults_to_none_when_unset(monkeypatch) -> None:
    monkeypatch.delenv("OPS_SELF_PING_URL", raising=False)
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)

    settings = OpsSettings(_env_file=None)

    assert settings.self_ping_url is None
