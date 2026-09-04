import pytest

from backend.config import AUDIO_TEXT_TO_VIDEO_MODEL, SEEDANCE_2_FAST_MODEL, TEXT_TO_VIDEO_MODEL
from backend.models import CreateBatchRequest, SegmentSubmission
from backend.jobs import JobService


def request(**overrides):
    values = {
        "source_id": "source1",
        "variant_index": 0,
        "segments": [SegmentSubmission(segment_index=0)],
        "mode": "text",
        "model": TEXT_TO_VIDEO_MODEL,
        "generate_audio": False,
        "duration": 5,
        "ratio": "9:16",
        "resolution": "720p",
        "quantity": 1,
    }
    values.update(overrides)
    return CreateBatchRequest(**values)


def test_rejects_audio_on_non_audio_model():
    with pytest.raises(ValueError, match="不支持原生音频"):
        JobService.validate_request(request(generate_audio=True), TEXT_TO_VIDEO_MODEL)


def test_accepts_audio_on_seedance_15_pro():
    JobService.validate_request(request(model=AUDIO_TEXT_TO_VIDEO_MODEL, generate_audio=True), AUDIO_TEXT_TO_VIDEO_MODEL)


def test_rejects_mode_mismatch_and_invalid_parameters():
    with pytest.raises(ValueError, match="不支持当前生成类型"):
        JobService.validate_request(request(mode="image"), TEXT_TO_VIDEO_MODEL)
    with pytest.raises(ValueError, match="不支持当前画面比例"):
        JobService.validate_request(request(ratio="2:1"), TEXT_TO_VIDEO_MODEL)


def test_seedance_2_fast_validates_its_own_capabilities():
    JobService.validate_request(request(model=SEEDANCE_2_FAST_MODEL, generate_audio=True, duration=-1, ratio="adaptive", resolution="720p"), SEEDANCE_2_FAST_MODEL)
    with pytest.raises(ValueError, match="不支持当前清晰度"):
        JobService.validate_request(request(model=SEEDANCE_2_FAST_MODEL, resolution="1080p"), SEEDANCE_2_FAST_MODEL)
    with pytest.raises(ValueError, match="不支持当前时长"):
        JobService.validate_request(request(model=SEEDANCE_2_FAST_MODEL, duration=3), SEEDANCE_2_FAST_MODEL)
    with pytest.raises(ValueError, match="不支持当前生成类型"):
        JobService.validate_request(request(model=SEEDANCE_2_FAST_MODEL, mode="image"), SEEDANCE_2_FAST_MODEL)
    with pytest.raises(ValueError, match="不支持当前时长"):
        JobService.validate_request(request(duration=-1), TEXT_TO_VIDEO_MODEL)


def test_stage_progress_is_user_visible():
    service = JobService()
    data = service._id("job")
    # Verify the mapping itself, without creating a provider task.
    from backend.models import VideoTask
    task = VideoTask(
        job_id=data, batch_id="batch", source_id="source", source_title="title", variant_index=0, variant_title="variant",
        segment_index=0, role="hook", prompt_source="jimeng", prompt="prompt", mode="text", model=TEXT_TO_VIDEO_MODEL,
        generate_audio=False, created_at=1, updated_at=1,
    )
    service._set_stage(task, "running", 62)
    assert task.progress == 62
    assert task.progress_label == "正在生成视频"
    service._set_stage(task, "completed")
    assert task.progress == 100
