"""API de configuração da OpenRouter: chave mascarada, persistência e override.

O contrato que estes testes travam:

1. a chave entra pela API e **nunca** volta em texto claro (nem em `/settings`,
   nem em `/health`, nem numa mensagem de erro);
2. o que a UI salva persiste no arquivo de settings e sobrepõe o `.env`;
3. o job disparado depois de salvar usa a chave e os modelos configurados.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import clip_mvp.server as server_mod
from clip_mvp.config import Settings
from clip_mvp.openrouter import OpenRouterError, normalize_model
from clip_mvp.server import create_app

WEB_SRC = Path(__file__).resolve().parents[1] / "web" / "src"

FAKE_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef0123456789abcdef"

#: Recorte do formato real de `GET https://openrouter.ai/api/v1/models`.
CATALOG = [
    {
        "id": "google/gemini-2.5-flash",
        "name": "Google: Gemini 2.5 Flash",
        "context_length": 1048576,
        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
        "pricing": {"prompt": "0.0000003", "completion": "0.0000025"},
    },
    {
        "id": "meta-llama/llama-3.3-70b-instruct:free",
        "name": "Meta: Llama 3.3 70B (free)",
        "context_length": 65536,
        "architecture": {"input_modalities": ["text"], "output_modalities": ["text"]},
        "pricing": {"prompt": "0", "completion": "0"},
    },
    {
        "id": "openai/gpt-4o-audio-preview",
        "name": "OpenAI: GPT-4o Audio",
        "context_length": 128000,
        "architecture": {"modality": "text+audio->text"},
        "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
    },
]


@pytest.fixture
def settings_path(tmp_path) -> Path:
    return tmp_path / "config" / "settings.json"


@pytest.fixture
def env_settings(tmp_path) -> Settings:
    """Camada `.env`: sem chave, para que a configuração venha só da UI."""
    return Settings(
        openrouter_api_key="",
        work_dir=tmp_path / "work",
        out_dir=tmp_path / "out",
        stt_model="openai/whisper-1",
        candidate_model="env/candidatos",
        score_model="env/score",
        meta_model="env/meta",
    )


@pytest.fixture
def started_jobs(monkeypatch) -> list[Settings]:
    """Captura a `Settings` com que cada job foi disparado."""
    captured: list[Settings] = []

    def fake_run_job(url, settings, options, *, reporter=None, cancel_check=None, client=None):
        captured.append(settings)
        reporter.finish({"summary": {"selected": 0, "out_dirs": [], "notes": []}}, "ok")

    monkeypatch.setattr(server_mod, "run_job", fake_run_job)
    return captured


@pytest.fixture
def client(env_settings, settings_path, started_jobs) -> TestClient:
    return TestClient(create_app(env_settings, settings_path=settings_path))


def save_key(client: TestClient, key: str = FAKE_KEY):
    return client.put("/api/settings", json={"api_key": key})


class TestReadSettings:
    def test_reports_every_ai_role_with_the_env_default(self, client):
        payload = client.get("/api/settings").json()
        assert payload["openrouter"]["configured"] is False
        assert payload["openrouter"]["masked"] is None
        by_role = {entry["role"]: entry for entry in payload["models"]}
        assert set(by_role) == {"stt", "candidates", "score", "meta", "diarization"}
        assert by_role["candidates"]["value"] == "env/candidatos"
        assert by_role["candidates"]["source"] == "env"
        assert by_role["diarization"]["optional"] is True

    def test_score_role_declares_it_needs_vision(self, client):
        by_role = {entry["role"]: entry for entry in client.get("/api/settings").json()["models"]}
        assert "image" in by_role["score"]["requires"]
        assert "audio" in by_role["stt"]["requires"]

    def test_points_at_the_settings_file(self, client, settings_path):
        assert client.get("/api/settings").json()["settings_file"] == str(settings_path)


class TestSaveKey:
    def test_key_is_persisted_and_returned_masked(self, client, settings_path):
        payload = save_key(client).json()
        assert payload["openrouter"]["configured"] is True
        assert payload["openrouter"]["source"] == "ui"
        assert payload["openrouter"]["masked"] == "sk-or-…cdef"
        assert settings_path.is_file()

    def test_no_response_ever_contains_the_raw_key(self, client):
        save_key(client)
        for path in ("/api/settings", "/api/health", "/api/config", "/api/jobs"):
            body = client.get(path).text
            assert FAKE_KEY not in body, f"{path} vazou a chave"

    def test_key_survives_a_server_restart(self, env_settings, settings_path, started_jobs):
        first = TestClient(create_app(env_settings, settings_path=settings_path))
        save_key(first)
        second = TestClient(create_app(env_settings, settings_path=settings_path))
        assert second.get("/api/settings").json()["openrouter"]["configured"] is True

    def test_saving_models_does_not_wipe_the_key(self, client):
        save_key(client)
        client.put("/api/settings", json={"models": {"score": "novo/score"}})
        assert client.get("/api/settings").json()["openrouter"]["configured"] is True

    def test_clearing_the_key_falls_back_to_the_env(self, tmp_path, settings_path, started_jobs):
        with_env_key = Settings(
            openrouter_api_key="chave-do-env",
            work_dir=tmp_path / "work",
            out_dir=tmp_path / "out",
        )
        client = TestClient(create_app(with_env_key, settings_path=settings_path))
        save_key(client)
        assert client.get("/api/settings").json()["openrouter"]["source"] == "ui"

        payload = client.put("/api/settings", json={"clear_api_key": True}).json()
        assert payload["openrouter"]["source"] == "env"
        assert payload["openrouter"]["configured"] is True

    @pytest.mark.parametrize(
        "bad_key, expected",
        [
            ("sk-or-v1", "incompleta"),
            ("sk-or-v1-abc def0123456789", "espaços"),
        ],
    )
    def test_invalid_key_is_rejected_in_pt_br(self, client, bad_key, expected):
        response = client.put("/api/settings", json={"api_key": bad_key})
        assert response.status_code == 400
        assert expected in response.json()["detail"]

    def test_rejected_key_is_not_persisted(self, client, settings_path):
        client.put("/api/settings", json={"api_key": "sk-or-v1"})
        assert not settings_path.exists()

    def test_key_file_never_lands_inside_the_repo_by_default(self, client):
        """O default é o diretório de config do usuário — nada de commitar a chave."""
        repo_root = Path(__file__).resolve().parents[1]
        client_default = TestClient(create_app(Settings(openrouter_api_key="")))
        reported = Path(client_default.get("/api/settings").json()["settings_file"])
        assert repo_root not in reported.parents


class TestSaveModels:
    def test_model_per_role_is_persisted(self, client, settings_path):
        payload = client.put(
            "/api/settings",
            json={
                "models": {
                    "stt": "openai/whisper-large-v3",
                    "candidates": "ui/candidatos",
                    "score": "qwen/qwen2.5-vl-72b-instruct",
                    "meta": "ui/meta",
                    "diarization": "ui/diarizador",
                }
            },
        ).json()
        by_role = {entry["role"]: entry for entry in payload["models"]}
        assert by_role["score"]["value"] == "qwen/qwen2.5-vl-72b-instruct"
        assert by_role["score"]["source"] == "ui"
        assert by_role["score"]["env_default"] == "env/score"

        stored = json.loads(settings_path.read_text("utf-8"))["models"]
        assert stored["diarization"] == "ui/diarizador"

    def test_any_openrouter_id_is_accepted(self, client):
        response = client.put(
            "/api/settings", json={"models": {"candidates": "autor-novo/modelo-que-saiu-hoje:free"}}
        )
        assert response.status_code == 200

    def test_empty_value_restores_the_env_default(self, client):
        client.put("/api/settings", json={"models": {"candidates": "ui/candidatos"}})
        payload = client.put("/api/settings", json={"models": {"candidates": ""}}).json()
        candidates = next(e for e in payload["models"] if e["role"] == "candidates")
        assert candidates["value"] == "env/candidatos"
        assert candidates["source"] == "env"

    def test_invalid_model_id_is_rejected_in_pt_br(self, client):
        response = client.put("/api/settings", json={"models": {"score": "modelo com espaço"}})
        assert response.status_code == 400
        detail = response.json()["detail"]
        assert "Score (vision)" in detail
        assert "autor/modelo" in detail

    def test_unknown_role_is_rejected(self, client):
        response = client.put("/api/settings", json={"models": {"inventado": "a/b"}})
        assert response.status_code == 400
        assert "inventado" in response.json()["detail"]

    def test_health_reports_the_models_the_next_job_will_use(self, client):
        client.put("/api/settings", json={"models": {"score": "ui/score", "diarization": "ui/diar"}})
        models = client.get("/api/health").json()["models"]
        assert models["score"] == "ui/score"
        assert models["candidates"] == "env/candidatos"
        assert models["diarization"] == "ui/diar"

    def test_diarization_defaults_to_the_stt_model_in_health(self, client):
        # O papel de STT só aceita Whisper: o endpoint de transcrição rejeita
        # modelo de chat, então a validação barra qualquer outro id.
        client.put("/api/settings", json={"models": {"stt": "openai/whisper-large-v3"}})
        health = client.get("/api/health").json()
        assert health["models"]["diarization"] == "openai/whisper-large-v3"


class TestJobsUseTheConfiguredSettings:
    def test_job_runs_with_the_key_and_models_from_the_ui(self, client, started_jobs):
        save_key(client)
        client.put(
            "/api/settings",
            json={"models": {"candidates": "ui/candidatos", "score": "ui/score"}},
        )
        assert client.post("/api/jobs", json={"url": "https://x/settings"}).status_code == 200

        assert started_jobs, "o job não foi disparado"
        used = started_jobs[-1]
        assert used.openrouter_api_key == FAKE_KEY
        assert used.candidate_model == "ui/candidatos"
        assert used.score_model == "ui/score"
        assert used.meta_model == "env/meta", "papel sem override mantém o .env"

    def test_settings_saved_after_boot_apply_without_restarting(self, client, started_jobs):
        client.post("/api/jobs", json={"url": "https://x/antes"})
        save_key(client)
        client.post("/api/jobs", json={"url": "https://x/depois"})

        assert started_jobs[0].openrouter_api_key == ""
        assert started_jobs[-1].openrouter_api_key == FAKE_KEY

    def test_work_and_out_dirs_stay_on_the_env_layer(self, client, started_jobs, env_settings):
        save_key(client)
        client.post("/api/jobs", json={"url": "https://x/dirs"})
        assert started_jobs[-1].work_dir == env_settings.work_dir
        assert started_jobs[-1].out_dir == env_settings.out_dir


class TestConnectionTest:
    def test_reports_success_with_the_key_label(self, client, monkeypatch):
        seen: list[str] = []

        def fake_verify(key, *, base_url, timeout=20.0):
            seen.append(key)
            return {"ok": True, "label": "clip-mvp local", "limit_remaining_usd": 4.2}

        monkeypatch.setattr(server_mod, "verify_key", fake_verify)
        save_key(client)
        payload = client.post("/api/settings/test", json={}).json()
        assert payload["ok"] is True
        assert "Conexão OK" in payload["message"]
        assert seen == [FAKE_KEY]

    def test_can_test_a_key_before_saving_it(self, client, settings_path, monkeypatch):
        monkeypatch.setattr(
            server_mod, "verify_key", lambda key, **kwargs: {"ok": True, "label": None}
        )
        payload = client.post("/api/settings/test", json={"api_key": FAKE_KEY}).json()
        assert payload["ok"] is True
        assert not settings_path.exists(), "testar não pode gravar a chave"

    def test_rejected_key_comes_back_as_a_message_not_a_500(self, client, monkeypatch):
        def fake_verify(key, **kwargs):
            raise OpenRouterError("A OpenRouter recusou a chave (401).")

        monkeypatch.setattr(server_mod, "verify_key", fake_verify)
        save_key(client)
        response = client.post("/api/settings/test", json={})
        assert response.status_code == 200
        assert response.json() == {"ok": False, "message": "A OpenRouter recusou a chave (401)."}

    def test_without_any_key_it_asks_for_one(self, client):
        response = client.post("/api/settings/test", json={})
        assert response.status_code == 400
        assert "Nenhuma chave configurada" in response.json()["detail"]

    def test_invalid_key_is_rejected_before_the_network_call(self, client, monkeypatch):
        def explode(*args, **kwargs):  # pragma: no cover - não deve ser chamado
            raise AssertionError("não deveria chamar a OpenRouter com chave inválida")

        monkeypatch.setattr(server_mod, "verify_key", explode)
        response = client.post("/api/settings/test", json={"api_key": "curta"})
        assert response.status_code == 400


class TestModelCatalog:
    @pytest.fixture
    def catalog_calls(self, monkeypatch) -> list[str]:
        calls: list[str] = []

        def fake_fetch(key, *, base_url, timeout=20.0):
            calls.append(key)
            return [normalize_model(item) for item in CATALOG]

        monkeypatch.setattr(server_mod, "fetch_models", fake_fetch)
        return calls

    def test_lists_the_catalog_with_price_and_modalities(self, client, catalog_calls):
        save_key(client)
        payload = client.get("/api/settings/models").json()
        assert payload["total"] == 3
        flash = next(m for m in payload["models"] if m["id"] == "google/gemini-2.5-flash")
        assert flash["input_modalities"] == ["image", "text"]
        assert flash["prompt_usd_per_mtok"] == pytest.approx(0.3)
        assert flash["context_length"] == 1048576

    def test_filters_by_what_the_role_needs(self, client, catalog_calls):
        save_key(client)
        vision = client.get("/api/settings/models", params={"role": "score"}).json()
        assert [m["id"] for m in vision["models"]] == ["google/gemini-2.5-flash"]

        audio = client.get("/api/settings/models", params={"role": "stt"}).json()
        assert [m["id"] for m in audio["models"]] == ["openai/gpt-4o-audio-preview"]

    def test_filters_by_the_typed_query(self, client, catalog_calls):
        save_key(client)
        payload = client.get("/api/settings/models", params={"q": "llama"}).json()
        assert [m["id"] for m in payload["models"]] == ["meta-llama/llama-3.3-70b-instruct:free"]
        assert payload["matching"] == 1
        assert payload["total"] == 3

    def test_catalog_is_cached_between_calls(self, client, catalog_calls):
        save_key(client)
        client.get("/api/settings/models")
        second = client.get("/api/settings/models").json()
        assert len(catalog_calls) == 1
        assert second["cached"] is True

    def test_refresh_bypasses_the_cache(self, client, catalog_calls):
        save_key(client)
        client.get("/api/settings/models")
        payload = client.get("/api/settings/models", params={"refresh": True}).json()
        assert len(catalog_calls) == 2
        assert payload["cached"] is False

    def test_without_a_key_it_explains_what_to_do(self, client):
        response = client.get("/api/settings/models")
        assert response.status_code == 400
        assert "Configure a chave" in response.json()["detail"]

    def test_openrouter_failure_is_a_502_with_a_pt_br_message(self, client, monkeypatch):
        def fake_fetch(key, **kwargs):
            raise OpenRouterError("A OpenRouter não respondeu no tempo esperado. Tente de novo.")

        monkeypatch.setattr(server_mod, "fetch_models", fake_fetch)
        save_key(client)
        response = client.get("/api/settings/models")
        assert response.status_code == 502
        assert "não respondeu" in response.json()["detail"]

    def test_unknown_role_filter_is_rejected(self, client, catalog_calls):
        save_key(client)
        assert client.get("/api/settings/models", params={"role": "xpto"}).status_code == 400

    def test_cache_file_never_holds_the_key(self, client, catalog_calls, env_settings):
        save_key(client)
        client.get("/api/settings/models")
        cache = Path(env_settings.work_dir) / "openrouter_models.json"
        assert cache.is_file()
        assert FAKE_KEY not in cache.read_text("utf-8")


class TestUiConsumesTheSettingsContract:
    """A tela de Configurações precisa ler os mesmos campos que a API promete."""

    @staticmethod
    def _web_source() -> str:
        return "\n".join(path.read_text("utf-8") for path in sorted(WEB_SRC.rglob("*.ts*")))

    def test_ui_reads_the_settings_payload(self):
        source = self._web_source()
        for field in ("openrouter", "masked", "env_default", "input_modalities", "settings_file"):
            assert field in source, f"a UI não consome '{field}' de /api/settings"

    def test_ui_has_a_settings_screen_with_save_and_test(self):
        source = self._web_source()
        assert "Configurações" in source
        assert "Testar conexão" in source
        assert "/settings" in source

    def test_ui_never_renders_a_raw_key_field_as_plain_text(self):
        """A chave é campo de senha: não fica legível na tela de quem passa atrás."""
        assert 'type="password"' in self._web_source()
