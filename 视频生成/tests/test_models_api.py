from fastapi.testclient import TestClient

from backend.config import AUDIO_TEXT_TO_VIDEO_MODEL, SEEDANCE_2_FAST_MODEL
from backend.main import app


def test_models_endpoint_uses_correct_hyphenated_seedance_15_id():
    with TestClient(app) as client:
        models = client.get("/api/models").json()
    audio_model = next(model for model in models if model["id"] == AUDIO_TEXT_TO_VIDEO_MODEL)
    assert audio_model["id"] == "doubao-seedance-1-5-pro-251215"
    assert 2 not in audio_model["durations"]
    assert 4 in audio_model["durations"]
    assert audio_model["audio"] is True


def test_seedance_2_fast_catalog_and_restrictions():
    with TestClient(app) as client:
        models = client.get("/api/models").json()
    fast = next(model for model in models if model["id"] == SEEDANCE_2_FAST_MODEL)
    assert fast["label"] == "Seedance 2.0 Fast（VIP 账户可用时）"
    assert fast["modes"] == ["text"]
    assert fast["audio"] is True
    assert {-1, 4, 15}.issubset(fast["durations"])
    assert "adaptive" in fast["ratios"]
    assert fast["resolutions"] == ["480p", "720p"]


def test_old_dotted_model_id_is_rejected():
    with TestClient(app) as client:
        source = client.get("/api/sources").json()[0]
        response = client.post("/api/batches", json={
            "source_id": source["id"], "variant_index": 0,
            "segments": [{"segment_index": 0}], "mode": "text",
            "model": "doubao-seedance-1.5-pro-251215", "duration": 5,
            "ratio": "9:16", "resolution": "720p", "quantity": 1,
        })
    assert response.status_code == 422
