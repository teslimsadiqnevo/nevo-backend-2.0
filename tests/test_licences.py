import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nevo.api import licences


def test_public_backend_notices_are_complete_and_exclude_dev_dependencies():
    app = FastAPI()
    app.include_router(licences.router)
    with TestClient(app) as client:
        response = client.get("/legal/third-party-licenses.json")
        assert response.status_code == 200
        payload = response.json()
        assert payload["frontendIncluded"] is False
        dependencies = payload["dependencies"]
        assert len(dependencies) >= 30
        assert all(item["notices"] for item in dependencies)
        assert "pytest" not in {item["name"].lower() for item in dependencies}
        assert any(item["name"].lower() == "dnspython" for item in dependencies)
        text = client.get("/legal/third-party-licenses.txt")
        assert text.status_code == 200
        assert "Copyright" in text.text
        page = client.get("/legal/third-party-licenses")
        assert page.status_code == 200
        assert "libvips" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]


def test_incomplete_inventory_is_not_published(monkeypatch):
    monkeypatch.setattr(
        licences,
        "inventory",
        lambda: licences.LicenceInventory(
            backendVersion="test",
            dependencies=[
                licences.DependencyNotice(name="missing", version="1", licence="MIT", notices=[])
            ],
        ),
    )
    with pytest.raises(Exception) as error:
        licences.prepared_inventory()
    assert error.value.status_code == 503


def test_licence_metadata_is_escaped(monkeypatch):
    monkeypatch.setattr(
        licences,
        "inventory",
        lambda: licences.LicenceInventory(
            backendVersion="test",
            dependencies=[
                licences.DependencyNotice(
                    name="<script>bad</script>",
                    version="1",
                    licence="MIT",
                    notices=[licences.LicenceText(name="LICENSE", text="<script>bad</script>")],
                )
            ],
        ),
    )
    assert "<script>bad</script>" not in licences.licence_page().body.decode()
    assert "&lt;script&gt;" in licences.licence_page().body.decode()
