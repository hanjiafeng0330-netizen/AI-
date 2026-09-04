from fastapi.testclient import TestClient

from backend.main import app


def test_sources_and_static_page_are_available():
    with TestClient(app) as client:
        sources = client.get("/api/sources")
        assert sources.status_code == 200
        assert sources.json()
        assert client.get("/").status_code == 200


def test_settings_status_and_save_do_not_return_api_key(monkeypatch, tmp_path):
    import backend.config as config

    env_file = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_FILE", env_file)
    monkeypatch.setattr(config, "_runtime_api_key", "")
    submitted = "test-private-api-key"
    with TestClient(app) as client:
        initial = client.get("/api/settings/seedance")
        assert initial.json() == {"configured": False}
        saved = client.put("/api/settings/seedance", json={"api_key": submitted})
        assert saved.json() == {"configured": True}
        assert submitted not in saved.text
        assert submitted not in client.get("/api/settings/seedance").text
    assert submitted in env_file.read_text(encoding="utf-8")


def test_rejects_unknown_source():
    with TestClient(app) as client:
        response = client.get("/api/sources/doesnotexist")
        assert response.status_code == 404


def test_generation_page_exposes_parameter_controls():
    with TestClient(app) as client:
        page = client.get("/").text
        for control in ('id="duration"', 'id="ratio"', 'id="resolution"', 'id="quantity"', 'id="model"'):
            assert control in page


def test_rejects_invalid_model_before_submit():
    with TestClient(app) as client:
        source = client.get("/api/sources").json()[0]
        response = client.post("/api/batches", json={
            "source_id": source["id"], "variant_index": 0,
            "segments": [{"segment_index": 0}], "model": "unknown-model",
        })
        assert response.status_code == 422
