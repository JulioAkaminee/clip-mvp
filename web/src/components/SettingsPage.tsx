import { useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import type {
  AppSettings,
  ConnectionTestResult,
  Health,
  ModelRoleKey,
  OpenRouterModel,
  SettingsUpdate,
} from "../lib/types";
import { ModelPicker } from "./ModelPicker";
import { Badge, Button, Card, Field, TextInput } from "./ui";

function sourceHint(source: AppSettings["openrouter"]["source"]): string {
  if (source === "ui") return "salva no arquivo local de configurações";
  if (source === "env") return "vinda do .env (a interface pode sobrepor)";
  return "ainda não configurada";
}

function draftFrom(settings: AppSettings): Record<ModelRoleKey, string> {
  return Object.fromEntries(settings.models.map((role) => [role.role, role.value])) as Record<
    ModelRoleKey,
    string
  >;
}

export function SettingsPage({
  health,
  onChanged,
}: {
  health: Health | null;
  onChanged: () => void;
}) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [draft, setDraft] = useState<Record<ModelRoleKey, string> | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [catalog, setCatalog] = useState<OpenRouterModel[]>([]);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingCatalog, setLoadingCatalog] = useState(false);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ConnectionTestResult | null>(null);

  const applyPayload = (payload: AppSettings) => {
    setSettings(payload);
    setDraft(draftFrom(payload));
  };

  const reload = async () => {
    const payload = await api.settings();
    applyPayload(payload);
    return payload;
  };

  useEffect(() => {
    void (async () => {
      try {
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const loadCatalog = async (refresh = false) => {
    setLoadingCatalog(true);
    setCatalogError(null);
    try {
      const payload = await api.models({ refresh });
      setCatalog(payload.models);
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      setCatalogError(message);
      setCatalog([]);
    } finally {
      setLoadingCatalog(false);
    }
  };

  useEffect(() => {
    if (settings?.openrouter.configured || health?.openrouter_key) {
      void loadCatalog();
    }
  }, [settings?.openrouter.configured, health?.openrouter_key]);

  const modelsChanged = useMemo(() => {
    if (!settings || !draft) return false;
    return settings.models.some((role) => draft[role.role] !== role.value);
  }, [settings, draft]);

  const keyTyped = apiKey.trim().length > 0;
  const dirty = keyTyped || modelsChanged;

  const save = async (extra?: SettingsUpdate) => {
    if (!settings || !draft) return;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const models: SettingsUpdate["models"] = { ...extra?.models };
      for (const role of settings.models) {
        const next = extra?.models?.[role.role] ?? draft[role.role];
        if (next === role.value) continue;
        // Vazio ou igual ao default do .env: tira o override da UI.
        models[role.role] = next.trim() === (role.env_default || "") ? "" : next.trim();
      }
      const payload: SettingsUpdate = { ...extra };
      if (keyTyped) payload.api_key = apiKey.trim();
      if (Object.keys(models).length > 0) payload.models = models;
      const next = await api.updateSettings(payload);
      applyPayload(next);
      setApiKey("");
      setNotice("Configurações salvas. O próximo job já usa esta chave e estes modelos.");
      onChanged();
      if (next.openrouter.configured && catalog.length === 0) void loadCatalog();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const testConnection = async () => {
    setTesting(true);
    setError(null);
    setTestResult(null);
    try {
      const result = await api.testConnection(keyTyped ? apiKey.trim() : undefined);
      setTestResult(result);
      if (result.ok && keyTyped) {
        setNotice("Chave aceita. Clique em Salvar para gravá-la neste computador.");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setTesting(false);
    }
  };

  const clearKey = async () => {
    setApiKey("");
    await save({ clear_api_key: true });
  };

  if (loading) {
    return (
      <Card className="mx-auto max-w-3xl">
        <p className="text-sm text-mist-400">Carregando configurações…</p>
      </Card>
    );
  }

  if (!settings || !draft) {
    return (
      <Card className="mx-auto max-w-3xl border-red-400/25 bg-red-500/8">
        <h2 className="text-sm font-semibold text-red-200">Não deu para ler as configurações</h2>
        <p className="mt-1 text-[0.8rem] text-red-100/80">{error ?? "resposta vazia da API"}</p>
      </Card>
    );
  }

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5 fade-up">
      <header className="space-y-2 pt-2">
        <Badge tone="brand">Configurações</Badge>
        <h2 className="text-2xl font-semibold tracking-tight text-white">
          Chave e modelos da OpenRouter
        </h2>
        <p className="max-w-xl text-[0.86rem] leading-relaxed text-mist-400">
          Cole a chave aqui — não precisa editar o <code className="text-mist-300">.env</code>. Ela
          fica neste computador, mascarada na API, e vale para a interface e para a CLI. Qualquer
          id de modelo da OpenRouter é aceito; com a chave salva, a lista abaixo vira busca.
        </p>
      </header>

      <Card className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
            Chave da API
          </h3>
          <Badge tone={settings.openrouter.configured ? "good" : "warn"}>
            {settings.openrouter.configured
              ? settings.openrouter.masked ?? "configurada"
              : "ausente"}
          </Badge>
        </div>
        <p className="text-[0.78rem] text-mist-400">
          {settings.openrouter.configured
            ? `Em uso: ${settings.openrouter.masked} — ${sourceHint(settings.openrouter.source)}.`
            : "Sem chave o job para no primeiro passo de IA (transcrição)."}
        </p>
        <Field
          label="OPENROUTER_API_KEY"
          hint="a chave nunca volta completa nas respostas"
          htmlFor="openrouter-key"
        >
          <TextInput
            id="openrouter-key"
            type="password"
            value={apiKey}
            onChange={(event) => {
              setApiKey(event.target.value);
              setTestResult(null);
            }}
            placeholder={
              settings.openrouter.masked
                ? `configurada (${settings.openrouter.masked}) — cole outra para trocar`
                : "sk-or-v1-…"
            }
            autoComplete="off"
            spellCheck={false}
          />
        </Field>
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => void testConnection()} loading={testing}>
            Testar conexão
          </Button>
          {settings.openrouter.source === "ui" && (
            <Button variant="ghost" onClick={() => void clearKey()} disabled={saving}>
              Remover chave da interface
            </Button>
          )}
        </div>
        {testResult && (
          <p
            className={
              testResult.ok
                ? "rounded-xl border border-lime-300/25 bg-lime-300/8 px-3.5 py-2.5 text-[0.8rem] text-lime-100"
                : "rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200"
            }
          >
            {testResult.message}
            {testResult.ok && testResult.limit_remaining_usd != null && (
              <span className="mt-1 block text-[0.72rem] text-mist-300">
                Crédito restante: US$ {testResult.limit_remaining_usd.toFixed(2)}
              </span>
            )}
          </p>
        )}
      </Card>

      <Card className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h3 className="text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
              Modelos por papel
            </h3>
            <p className="mt-1 max-w-lg text-[0.75rem] text-mist-400">
              STT e diarização precisam de áudio; o score precisa de visão. Digite qualquer slug
              (`autor/modelo`) — a lista é só um atalho, não um limite.
            </p>
          </div>
          <Button
            size="sm"
            disabled={!settings.openrouter.configured}
            loading={loadingCatalog}
            onClick={() => void loadCatalog(true)}
          >
            Atualizar catálogo
          </Button>
        </div>
        {catalogError && (
          <p className="rounded-xl border border-amber-300/25 bg-amber-300/8 px-3.5 py-2.5 text-[0.78rem] text-amber-100">
            {catalogError} — você ainda pode colar o id do modelo na mão.
          </p>
        )}
        {settings.models.map((role) => (
          <ModelPicker
            key={role.role}
            role={role}
            value={draft[role.role]}
            catalog={catalog}
            catalogError={catalogError}
            loadingCatalog={loadingCatalog}
            onChange={(value) => setDraft((current) => (current ? { ...current, [role.role]: value } : current))}
            onRestore={() =>
              setDraft((current) =>
                current ? { ...current, [role.role]: role.env_default } : current,
              )
            }
          />
        ))}
      </Card>

      <Card className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
            Salvar
          </Button>
          <p className="text-[0.75rem] text-mist-400">
            Arquivo: <code className="break-all text-mist-300">{settings.settings_file}</code>
          </p>
        </div>
        {error && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {error}
          </p>
        )}
        {notice && (
          <p className="rounded-xl border border-brand-400/30 bg-brand-500/10 px-3.5 py-2.5 text-[0.8rem] text-brand-400">
            {notice}
          </p>
        )}
      </Card>
    </div>
  );
}
