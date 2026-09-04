from backend.input_loader import get_source, list_sources


def test_lists_existing_prompt_generator_sources():
    sources = list_sources()
    assert sources
    assert all(source.variant_count > 0 for source in sources)


def test_loads_existing_source_with_video_prompts():
    source = get_source(list_sources()[0].id)
    assert source.variants
    assert source.variants[0].video_prompts
    prompt = source.variants[0].video_prompts[0]
    assert prompt.jimeng_prompt
    assert prompt.kling_prompt


def test_rejects_non_logical_source_id():
    try:
        get_source("../../etc/passwd")
    except KeyError:
        pass
    else:
        raise AssertionError("路径穿越 ID 应被拒绝")
