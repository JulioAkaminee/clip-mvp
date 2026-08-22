import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "../lib/api";
import type {
  AppSettings,
  ConnectionTestResult,
  Health,
  ModelRoleKey,
  ModelRoleState,
  OpenRouterModel,
} from "../lib/types";
import { formatUsd } from "../lib/format";
import {
  Button,
  Callout,
  Card,
  CopyButton,
  Disclosure,
  Field,
  Skeleton,
  TextInput,
  cx,
} from "./ui";

/**
 * Configurações em duas camadas: a chave, que todo mundo precisa, aberta; a
 * escolha de modelo por papel, que quase ninguém precisa, atrás de "Avançado"
 * com um botão de voltar ao padrão sempre à vista.
 */
export function Settings({
  health,
  onChanged,
}: {
  health: Health | null;
  onChanged: () => void;
}) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [key, setKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [test, setTest] = useState<ConnectionTestResult | null>(null);
  const [message, setMessage] = useState<{ tone: "good" | "bad"; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setSettings(await api.settings());
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof ApiError ? err.message : String(err) });
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const trimmed = key.trim();

  const saveKey = async () => {
    if (!trimmed) return;
    setSaving(true);
    setMessage(null);
    try {
      setSettings(await api.updateSettings({ api_key: trimmed }));
      setKey("");
      setMessage({ tone: "good", text: "Chave salva." });
      onChanged();
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    setTest(null);
    try {
      setTest(await api.testConnection(trimmed || undefined));
    } catch (err) {
      setTest({ ok: false, message: err instanceof ApiError ? err.message : String(err) });
    } finally {
      setTesting(false);
    }
  };

  const saveModel = async (role: ModelRoleKey, value: string) => {
    setMessage(null);
    try {
      setSettings(await api.updateSettings({ models: { [role]: value } }));
      onChanged();
    } catch (err) {
      setMessage({ tone: "bad", text: err instanceof ApiError ? err.message : String(err) });
      await load();
    }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <header className="space-y-1 pt-2">
        <h1 className="text-2xl font-semibold text-white">Configurações</h1>
        <p className="text-[0.88rem] text-mist-300">
          A chave da OpenRouter é a única coisa obrigatória.
        </p>
      </header>

      {message && (
        <Callout tone={message.tone} title={message.tone === "good" ? "Pronto" : "Não deu certo"}>
          <p>{message.text}</p>
        </Callout>
      )}

      <Card className="space-y-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-[0.95rem] font-semibold text-mist-200">Chave da OpenRouter</h2>
            <p className="mt-0.5 text-[0.78rem] text-mist-400">
              {settings?.openrouter.configured
                ? `Configurada (${settings.openrouter.masked}) — vinda ${settings.openrouter.source === "ui" ? "desta tela" : "do arquivo .env"}.`
                : "Ainda não configurada."}
            </p>
          </div>
          {settings?.openrouter.configured && (
            <span className="shrink-0 rounded-full border border-lime-300/30 bg-lime-300/10 px-2.5 py-0.5 text-[0.7rem] text-lime-300">
              ativa
            </span>
          )}
        </div>

        <Field
          label={settings?.openrouter.configured ? "Trocar a chave" : "Colar a chave"}
          htmlFor="api-key"
        >
          <div className="flex flex-col gap-2 sm:flex-row">
            <TextInput
              id="api-key"
              type="password"
              value={key}
              autoComplete="off"
              spellCheck={false}
              placeholder="sk-or-v1-..."
              onChange={(event) => setKey(event.target.value)}
              className="font-mono text-[0.8rem]"
            />
            <Button variant="outline" onClick={() => void runTest()} loading={testing} className="shrink-0">
              Testar conexão
            </Button>
            <Button
              variant="primary"
              onClick={() => void saveKey()}
              loading={saving}
              disabled={!trimmed}
              className="shrink-0"
            >
              Salvar
            </Button>
          </div>
        </Field>

        {test && (
          <Callout
            tone={test.ok ? "good" : "bad"}
            title={test.ok ? "Conexão funcionando" : "A OpenRouter recusou"}
          >
            <p>{test.message}</p>
            {test.ok && test.limit_remaining_usd != null && (
              <p className="mt-1">Crédito disponível: {formatUsd(test.limit_remaining_usd)}.</p>
            )}
          </Callout>
        )}

        {settings && (
          <p className="border-t border-white/8 pt-3 text-[0.72rem] text-mist-400">
            Guardada apenas neste computador, em{" "}
            <code className="text-mist-300">{settings.settings_file}</code>, com permissão de
            leitura só para você. Nunca aparece inteira nesta tela.
          </p>
        )}
      </Card>

      <Card className="space-y-3">
        <h2 className="text-[0.95rem] font-semibold text-mist-200">Este computador</h2>
        <div className="grid gap-2 sm:grid-cols-2">
          <ToolStatus ok={health?.ffmpeg} name="ffmpeg" need="cortar e montar os vídeos" />
          <ToolStatus ok={health?.yt_dlp} name="yt-dlp" need="baixar do YouTube" />
          <ToolStatus
            ok={health?.mediapipe}
            name="detecção de rosto"
            need="o zoom que segue quem fala"
            optional
          />
          <ToolStatus ok={health?.ffprobe} name="ffprobe" need="ler a duração dos vídeos" />
        </div>
        {health && (
          <p className="border-t border-white/8 pt-3 text-[0.72rem] text-mist-400">
            Os vídeos prontos ficam em <code className="text-mist-300">{health.out_dir}/</code> e os
            arquivos de trabalho em <code className="text-mist-300">{health.work_dir}/</code>.
          </p>
        )}
      </Card>

      <Disclosure
        summary="Avançado: qual IA usar em cada etapa"
        hint="Os padrões funcionam bem — só mexa se souber o que quer"
      >
        {settings ? (
          settings.models.map((role) => (
            <ModelRow key={role.role} role={role} onSave={saveModel} />
          ))
        ) : (
          <>
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </>
        )}
      </Disclosure>
    </div>
  );
}

function ToolStatus({
  ok,
  name,
  need,
  optional = false,
}: {
  ok: boolean | undefined;
  name: string;
  need: string;
  optional?: boolean;
}) {
  const tone = ok ? "good" : optional ? "warn" : "bad";
  const tones = {
    good: "border-lime-300/25 bg-lime-300/8",
    warn: "border-amber-300/25 bg-amber-300/8",
    bad: "border-red-400/25 bg-red-500/8",
  };
  return (
    <div className={cx("flex items-center gap-2.5 rounded-xl border px-3 py-2.5", tones[tone])}>
      <span
        className={cx(
          "size-2 shrink-0 rounded-full",
          ok ? "bg-lime-300" : optional ? "bg-amber-300" : "bg-red-400",
        )}
        aria-hidden
      />
      <div className="min-w-0">
        <p className="text-[0.82rem] font-medium text-mist-200">{name}</p>
        <p className="truncate text-[0.7rem] text-mist-400">
          {ok ? `usado para ${need}` : optional ? `sem isso, não há ${need}` : `falta para ${need}`}
        </p>
      </div>
    </div>
  );
}

/** Uma linha por papel de IA: campo livre + busca no catálogo + voltar ao padrão. */
function ModelRow({
  role,
  onSave,
}: {
  role: ModelRoleState;
  onSave: (role: ModelRoleKey, value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(role.value || role.effective);
  const [browsing, setBrowsing] = useState(false);
  const [query, setQuery] = useState("");
  const [models, setModels] = useState<OpenRouterModel[] | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setValue(role.value || role.effective);
  }, [role.value, role.effective]);

  useEffect(() => {
    if (!browsing) return;
    let cancelled = false;
    setLoading(true);
    const timer = window.setTimeout(() => {
      void api
        .models({ role: role.role, q: query || undefined })
        .then((data) => {
          if (!cancelled) setModels(data.models.slice(0, 40));
        })
        .catch(() => {
          if (!cancelled) setModels([]);
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 300);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [browsing, query, role.role]);

  const dirty = value.trim() !== (role.value || role.effective);
  const isDefault = !role.value || role.value === role.env_default;

  return (
    <div className="space-y-2 rounded-xl border border-white/8 bg-white/3 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[0.82rem] font-medium text-mist-200">{role.label}</span>
        {!isDefault && (
          <button
            type="button"
            onClick={() => void onSave(role.role, role.env_default)}
            className="text-[0.7rem] text-brand-400 underline-offset-2 hover:underline"
          >
            voltar ao padrão
          </button>
        )}
      </div>
      <p className="text-[0.72rem] leading-relaxed text-mist-400">{role.description}</p>

      <div className="flex flex-col gap-2 sm:flex-row">
        <TextInput
          value={value}
          spellCheck={false}
          onChange={(event) => setValue(event.target.value)}
          className="font-mono text-[0.75rem]"
          aria-label={`Modelo para ${role.label}`}
        />
        <div className="flex shrink-0 gap-2">
          <Button size="sm" variant="ghost" onClick={() => setBrowsing((open) => !open)}>
            {browsing ? "Fechar" : "Procurar"}
          </Button>
          <Button
            size="sm"
            variant={dirty ? "primary" : "outline"}
            disabled={!dirty}
            onClick={() => void onSave(role.role, value.trim())}
          >
            Salvar
          </Button>
        </div>
      </div>

      {browsing && (
        <div className="space-y-2 rounded-lg border border-white/8 bg-black/25 p-2">
          <TextInput
            value={query}
            placeholder="Buscar no catálogo da OpenRouter…"
            onChange={(event) => setQuery(event.target.value)}
            className="text-[0.78rem]"
            aria-label="Buscar modelo"
          />
          {loading && <Skeleton className="h-8 w-full" />}
          {!loading && models?.length === 0 && (
            <p className="px-1 py-2 text-[0.75rem] text-mist-400">
              Nada encontrado. Salve a chave primeiro para o catálogo carregar.
            </p>
          )}
          <ul className="max-h-56 space-y-0.5 overflow-y-auto">
            {models?.map((model) => (
              <li key={model.id}>
                <button
                  type="button"
                  onClick={() => {
                    setValue(model.id);
                    setBrowsing(false);
                  }}
                  className="flex w-full items-baseline justify-between gap-2 rounded-md px-2 py-1.5 text-left hover:bg-white/8"
                >
                  <span className="min-w-0">
                    <span className="block truncate text-[0.78rem] text-mist-200">
                      {model.name}
                    </span>
                    <span className="block truncate font-mono text-[0.66rem] text-mist-400">
                      {model.id}
                    </span>
                  </span>
                  <span className="shrink-0 text-[0.68rem] text-mist-400">
                    {model.free
                      ? "grátis"
                      : model.prompt_usd_per_mtok != null
                        ? `$${model.prompt_usd_per_mtok}/M`
                        : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex items-center gap-2">
        <span className="text-[0.68rem] text-mist-400">Em uso: {role.effective}</span>
        <CopyButton value={role.effective} label="copiar" />
      </div>
    </div>
  );
}
