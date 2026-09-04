import stat

import pytest

import backend.config as config
from backend.seedance_provider import SeedanceProvider


def test_save_key_preserves_other_env_values_and_refreshes_runtime(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("# keep this\nOTHER_VALUE=yes\nSEEDANCE_API_KEY=old\nSEEDANCE_API_KEY=duplicate\n", encoding="utf-8")
    monkeypatch.setattr(config, "_runtime_api_key", "old")

    config.save_seedance_api_key("new-secret", env_file=env_file)

    saved = env_file.read_text(encoding="utf-8")
    assert "# keep this\nOTHER_VALUE=yes\n" in saved
    assert saved.count("SEEDANCE_API_KEY=") == 1
    assert "SEEDANCE_API_KEY=new-secret" in saved
    assert config.get_seedance_api_key() == "new-secret"
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600


def test_rejects_key_format_injection(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("OTHER_VALUE=yes\n", encoding="utf-8")
    with pytest.raises(ValueError):
        config.save_seedance_api_key("bad\nINJECTED=value", env_file=env_file)
    assert env_file.read_text(encoding="utf-8") == "OTHER_VALUE=yes\n"


def test_default_provider_resolves_refreshed_runtime_key(monkeypatch):
    monkeypatch.setattr(config, "_runtime_api_key", "first")
    provider = SeedanceProvider()
    assert provider._headers()["Authorization"] == "Bearer first"
    monkeypatch.setattr(config, "_runtime_api_key", "second")
    assert provider._headers()["Authorization"] == "Bearer second"


def test_explicit_provider_key_is_not_replaced(monkeypatch):
    monkeypatch.setattr(config, "_runtime_api_key", "runtime")
    provider = SeedanceProvider(api_key="injected-test-key")
    assert provider._headers()["Authorization"] == "Bearer injected-test-key"
