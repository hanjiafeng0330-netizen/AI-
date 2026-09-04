import pytest

from backend.config import SEEDANCE_2_FAST_MODEL
from backend.models import VideoTask
from backend.seedance_provider import ImagePayloadNotVerifiedError, SeedanceProvider


def build_task(mode="text"):
    return VideoTask(
        job_id="job_1", batch_id="batch_1", source_id="source1", source_title="示例", variant_index=0,
        variant_title="变体", segment_index=0, role="hook", prompt_source="jimeng", prompt="测试提示词",
        mode=mode, model="doubao-seedance-1-0-pro-250528", generate_audio=True, created_at=1, updated_at=1,
    )


def test_text_payload_matches_documented_content_shape():
    provider = SeedanceProvider(api_key="secret", base_url="https://example.test", tasks_path="/tasks")
    assert provider.tasks_url == "https://example.test/tasks"
    assert provider._payload(build_task()) == {
        "model": "doubao-seedance-1-0-pro-250528",
        "content": [{"type": "text", "text": "测试提示词"}],
        "duration": 5,
        "ratio": "9:16",
        "resolution": "720p",
        "generate_audio": True,
    }


def test_seedance_2_fast_uses_standard_payload_fields():
    provider = SeedanceProvider(api_key="secret")
    task = build_task()
    task.model = SEEDANCE_2_FAST_MODEL
    task.requested_duration = -1
    task.ratio = "adaptive"
    task.resolution = "720p"
    task.generate_audio = True
    assert provider._payload(task) == {
        "model": SEEDANCE_2_FAST_MODEL,
        "content": [{"type": "text", "text": "测试提示词"}],
        "duration": -1,
        "ratio": "adaptive",
        "resolution": "720p",
        "generate_audio": True,
    }


def test_service_tier_is_omitted_or_included():
    provider = SeedanceProvider(api_key="secret")
    task = build_task()
    assert "service_tier" not in provider._payload(task)
    task.service_tier = "flex"
    assert provider._payload(task)["service_tier"] == "flex"


def test_extracts_screenshot_style_video_url_and_status():
    provider = SeedanceProvider(api_key="secret")
    snapshot = provider._snapshot({"id": "cgt_123", "status": "succeeded", "progress": 100, "content": {"video_url": "https://video.test/a.mp4"}})
    assert snapshot.task_id == "cgt_123"
    assert snapshot.status == "succeeded"
    assert snapshot.progress == 100
    assert snapshot.result_urls == ["https://video.test/a.mp4"]


def test_extracts_provider_error_fields():
    provider = SeedanceProvider(api_key="secret")
    snapshot = provider._snapshot({"id": "cgt_123", "status": "failed", "error": {"code": "BadRequest", "message": "参数不支持"}})
    assert snapshot.error_code == "BadRequest"
    assert snapshot.error_message == "参数不支持"


def test_image_payload_stays_guarded_until_api_contract_confirmed():
    provider = SeedanceProvider(api_key="secret")
    with pytest.raises(ImagePayloadNotVerifiedError):
        provider._payload(build_task("image"))


def test_snapshot_redacts_nested_secret_fields():
    provider = SeedanceProvider(api_key="secret")
    snapshot = provider._snapshot({"id": "task", "token": "hidden", "content": {"api_key": "hidden", "nested": [{"secret": "hidden"}]}})
    assert "hidden" not in str(snapshot.raw)
    assert snapshot.raw["token"] == "[REDACTED]"
    assert snapshot.raw["content"]["api_key"] == "[REDACTED]"


def test_safe_error_redacts_signed_url_and_secret_text():
    import httpx
    provider = SeedanceProvider(api_key="secret")
    response = httpx.Response(400, json={"error": {"code": "invalid_parameter", "message": "https://example.test/video.mp4?X-Tos-Signature=hidden"}})
    error = provider._safe_error(response, "提交任务")
    assert error.error_code == "invalid_parameter"
    assert "X-Tos-Signature" not in str(error)
    assert "https://example.test/video.mp4" in str(error)
