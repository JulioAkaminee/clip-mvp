"""Arquivo de settings da UI: mascaramento, persistência, validação e precedência.

Regra que estes testes protegem: a chave da OpenRouter entra pelo arquivo e sai
apenas mascarada. Nenhum payload, log ou mensagem de erro pode carregar o valor
completo.
"""

from __future__ import annotations

import json
import os
import stat

import pytest

from clip_mvp.config import Settings
from clip_mvp.settings_store import (
    MODEL_ROLES,
    SettingsValidationError,
    StoredSettings,
    apply_stored,
    describe,
    load_stored,
    mask_key,
    save_stored,
    settings_file,
    validate_api_key,
    validate_model_id,
)

#: Formato real de uma chave da OpenRouter, para os testes de vazamento.
FAKE_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef"


@pytest.fixture
def store_path(tmp_path):
    return tmp_path / "config" / "settings.json"


class TestMask:
    def test_never_returns_the_full_key(self):
        masked = mask_key(FAKE_KEY)
        assert masked is not None
        assert FAKE_KEY not in masked
        assert len(masked) < len(FAKE_KEY)

    def test_keeps_enough_to_identify_the_key(self):
        assert mask_key(FAKE_KEY) == "sk-or-…cdef"

    def test_short_value_is_fully_hidden(self):
        assert mask_key("abc123") == "••••••"

    def test_empty_key_has_no_mask(self):
        assert mask_key("") is None
        assert mask_key(None) is None


class TestValidation:
    def test_accepts_a_plausible_key(self):
        assert validate_api_key(f"  {FAKE_KEY}  ") == FAKE_KEY

    def test_rejects_empty_key_in_pt_br(self):
        with pytest.raises(SettingsValidationError) as exc:
            validate_api_key("   ")
        assert "Cole a chave" in str(exc.value)

    def test_rejects_key_with_whitespace(self):
        with pytest.raises(SettingsValidationError) as exc:
            validate_api_key("sk-or-v1-abc def0123456789")
        assert "espaços" in str(exc.value)

    def test_rejects_truncated_key(self):
        with pytest.raises(SettingsValidationError) as exc:
            validate_api_key("sk-or-v1")
        assert "incompleta" in str(exc.value)

    def test_error_message_never_echoes_the_key(self):
        with pytest.raises(SettingsValidationError) as exc:
            validate_api_key(f"{FAKE_KEY} colado com espaço")
        assert FAKE_KEY not in str(exc.value)

    @pytest.mark.parametrize(
        "model_id",
        [
            "openai/whisper-1",
            "google/gemini-2.5-flash",
            "meta-llama/llama-3.3-70b-instruct:free",
            "anthropic/claude-sonnet-4.5",
            "qwen/qwen2.5-vl-72b-instruct",
            "modelo-sem-autor",
        ],
    )
    def test_accepts_any_openrouter_slug(self, model_id):
        assert validate_model_id(model_id) == model_id

    @pytest.mark.parametrize("model_id", ["", "   ", "google/gemini 2.5", "modelo\nquebrado", "/leading"])
    def test_rejects_impossible_slugs(self, model_id):
        with pytest.raises(SettingsValidationError):
            validate_model_id(model_id)

    def test_error_names_the_role_in_pt_br(self):
        role = next(role for role in MODEL_ROLES if role.key == "score")
        with pytest.raises(SettingsValidationError) as exc:
            validate_model_id("modelo com espaço", role=role)
        assert role.label in str(exc.value)
        assert "OpenRouter" in str(exc.value)


class TestPersistence:
    def test_round_trip(self, store_path):
        save_stored(
            StoredSettings(openrouter_api_key=FAKE_KEY, models={"score": "google/gemini-2.5-pro"}),
            store_path,
        )
        loaded = load_stored(store_path)
        assert loaded.openrouter_api_key == FAKE_KEY
        assert loaded.model_for("score") == "google/gemini-2.5-pro"
        assert loaded.updated_at is not None

    def test_file_is_only_readable_by_the_owner(self, store_path):
        save_stored(StoredSettings(openrouter_api_key=FAKE_KEY), store_path)
        mode = stat.S_IMODE(store_path.stat().st_mode)
        assert mode == 0o600, f"chave gravada com permissão {oct(mode)}"

    def test_missing_file_is_an_empty_config(self, tmp_path):
        stored = load_stored(tmp_path / "nao-existe.json")
        assert stored.openrouter_api_key == ""
        assert stored.models == {}

    def test_corrupt_file_does_not_break_the_server(self, store_path):
        store_path.parent.mkdir(parents=True)
        store_path.write_text("{ isso não é json", "utf-8")
        assert load_stored(store_path).openrouter_api_key == ""

    def test_unknown_roles_are_dropped_on_read(self, store_path):
        store_path.parent.mkdir(parents=True)
        store_path.write_text(json.dumps({"models": {"score": "a/b", "inventado": "c/d"}}), "utf-8")
        stored = load_stored(store_path)
        assert stored.models == {"score": "a/b"}

    def test_empty_model_is_not_persisted(self, store_path):
        save_stored(StoredSettings(models={"score": "a/b", "meta": ""}), store_path)
        assert json.loads(store_path.read_text("utf-8"))["models"] == {"score": "a/b"}

    def test_file_path_follows_the_env_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLIP_SETTINGS_FILE", str(tmp_path / "meu-settings.json"))
        assert settings_file() == tmp_path / "meu-settings.json"

    def test_file_path_falls_back_to_the_user_config_dir(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLIP_SETTINGS_FILE", raising=False)
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        assert settings_file() == tmp_path / "clip-mvp" / "settings.json"

    def test_settings_file_is_not_inside_the_repo(self, monkeypatch):
        """Ninguém commita a chave por acidente: o default mora fora do projeto."""
        monkeypatch.delenv("CLIP_SETTINGS_FILE", raising=False)
        monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        assert not str(settings_file()).startswith(repo_root)


class TestPrecedence:
    """`default do código  <  .env  <  arquivo de settings (UI)`."""

    def test_ui_key_overrides_the_env(self):
        base = Settings(openrouter_api_key="chave-do-env")
        resolved = apply_stored(base, StoredSettings(openrouter_api_key=FAKE_KEY))
        assert resolved.openrouter_api_key == FAKE_KEY

    def test_ui_models_override_the_env_per_role(self):
        base = Settings(openrouter_api_key="x", candidate_model="env/candidatos")
        resolved = apply_stored(
            base, StoredSettings(models={"candidates": "ui/candidatos", "score": "ui/score"})
        )
        assert resolved.candidate_model == "ui/candidatos"
        assert resolved.score_model == "ui/score"

    def test_roles_without_ui_value_keep_the_env(self):
        base = Settings(openrouter_api_key="x", meta_model="env/meta")
        resolved = apply_stored(base, StoredSettings(models={"score": "ui/score"}))
        assert resolved.meta_model == "env/meta"

    def test_empty_store_changes_nothing(self):
        base = Settings(openrouter_api_key="chave-do-env")
        assert apply_stored(base, StoredSettings()) is base

    def test_diarization_falls_back_to_the_stt_model(self):
        base = Settings(openrouter_api_key="x", stt_model="openai/whisper-1")
        assert base.diarization_model == ""
        assert base.model_for_diarization() == "openai/whisper-1"

        resolved = apply_stored(base, StoredSettings(models={"diarization": "ui/diarizador"}))
        assert resolved.model_for_diarization() == "ui/diarizador"


class TestDescribe:
    def test_payload_masks_the_key(self):
        stored = StoredSettings(openrouter_api_key=FAKE_KEY)
        payload = describe(apply_stored(Settings(), stored), stored)
        assert payload["openrouter"]["configured"] is True
        assert payload["openrouter"]["source"] == "ui"
        assert FAKE_KEY not in json.dumps(payload)

    def test_payload_reports_the_env_as_the_source(self):
        settings = Settings(openrouter_api_key="chave-do-env")
        payload = describe(settings, StoredSettings())
        assert payload["openrouter"]["source"] == "env"

    def test_payload_has_no_key_when_nothing_is_configured(self):
        payload = describe(Settings(openrouter_api_key=""), StoredSettings())
        assert payload["openrouter"] == {
            "configured": False,
            "masked": None,
            "source": None,
            "base_url": "https://openrouter.ai/api/v1",
        }

    def test_every_ai_role_is_described(self):
        payload = describe(Settings(openrouter_api_key="x"), StoredSettings())
        roles = {entry["role"] for entry in payload["models"]}
        assert roles == {"stt", "candidates", "score", "meta", "diarization"}
        for entry in payload["models"]:
            assert entry["label"] and entry["description"]
            assert entry["requires"]

    def test_role_carries_the_project_default_for_the_reset_button(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_SCORE_MODEL", "env/score")
        stored = StoredSettings(models={"score": "ui/score"})
        payload = describe(apply_stored(Settings(), stored), stored)
        score = next(entry for entry in payload["models"] if entry["role"] == "score")
        assert score["value"] == "ui/score"
        assert score["env_default"] == "env/score"
        assert score["source"] == "ui"
