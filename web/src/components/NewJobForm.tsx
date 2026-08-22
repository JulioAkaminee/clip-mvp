import { useState } from "react";
import { api } from "../lib/api";
import { CAPTION_LABELS, FORMAT_OPTION_LABELS } from "../lib/format";
import type {
  AppConfig,
  CaptionMode,
  FormatKey,
  Health,
  JobRequest,
  Mode,
  Platform,
} from "../lib/types";
import {
  Badge,
  Button,
  Card,
  CheckPill,
  Field,
  Segmented,
  TextInput,
  Toggle,
  cx,
} from "./ui";

const ALL_FORMATS: FormatKey[] = ["face", "9x16", "16x9"];

interface FormState {
  url: string;
  mode: Mode;
  count: number;
  minScore: number;
  formats: FormatKey[];
  captions: CaptionMode;
  platforms: Platform[];
  budget: string;
  useBudget: boolean;
}

const INITIAL: FormState = {
  url: "",
  mode: "auto",
  count: 8,
  minScore: 60,
  formats: ALL_FORMATS,
  captions: "both",
  platforms: ["yt", "tiktok"],
  budget: "2.00",
  useBudget: false,
};

function toRequest(form: FormState, dryRun: boolean): JobRequest {
  return {
    url: form.url.trim(),
    more: form.mode === "more",
    count: form.mode === "count" ? form.count : null,
    min_score: form.minScore,
    max_score_only: null,
    formats: form.formats,
    captions: form.captions,
    platforms: form.platforms,
    dry_run: dryRun,
    budget: form.useBudget ? Number(form.budget) || null : null,
  };
}

export function NewJobForm({
  config,
  health,
  onCreated,
}: {
  config: AppConfig | null;
  health: Health | null;
  onCreated: (jobId: string) => void;
}) {
  const [form, setForm] = useState<FormState>({
    ...INITIAL,
    minScore: config?.default_min_score ?? INITIAL.minScore,
  });
  const [busy, setBusy] = useState<"none" | "dry" | "create">("none");
  const [error, setError] = useState<string | null>(null);

  const patch = (changes: Partial<FormState>) => setForm((current) => ({ ...current, ...changes }));

  const submit = async (dryRun: boolean) => {
    if (!form.url.trim()) {
      setError("Cole a URL do vídeo (YouTube, Twitch, …).");
      return;
    }
    if (form.useBudget && !(Number(form.budget) > 0)) {
      setError("O orçamento precisa ser um valor em dólar maior que zero (ex: 2.00).");
      return;
    }
    if (form.formats.length === 0) {
      setError("Escolha pelo menos um formato de export.");
      return;
    }
    setError(null);
    setBusy(dryRun ? "dry" : "create");
    try {
      const { job_id } = await api.createJob(toRequest(form, dryRun));
      onCreated(job_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("none");
    }
  };

  const verticalMax = config?.vertical_max_s ?? 90;
  const pad = config?.pad_ms ?? [200, 400];

  return (
    <div className="mx-auto w-full max-w-3xl space-y-5 fade-up">
      <header className="space-y-2 pt-2">
        <Badge tone="brand">novo job</Badge>
        <h2 className="text-2xl font-semibold tracking-tight text-white">
          Cole o link e deixe a IA escolher os cortes
        </h2>
        <p className="max-w-xl text-[0.86rem] leading-relaxed text-mist-400">
          A IA decide <strong className="text-mist-200">quais</strong> e{" "}
          <strong className="text-mist-200">quantos</strong> momentos valem corte, sempre fechando o
          contexto da conversa. O 9:16 nunca passa de {verticalMax}s; o 16:9 tem a duração que o arco
          pedir. Fronteira por palavra com folga de {pad[0]}–{pad[1]}ms.
        </p>
      </header>

      <Card className="space-y-5">
        <Field label="Link do vídeo" hint="YouTube, Twitch e o que o yt-dlp suportar" htmlFor="job-url">
          <div className="flex flex-col gap-2 sm:flex-row">
            <TextInput
              id="job-url"
              value={form.url}
              onChange={(event) => patch({ url: event.target.value })}
              onKeyDown={(event) => {
                if (event.key === "Enter") void submit(false);
              }}
              placeholder="https://youtube.com/watch?v=..."
              autoFocus
              spellCheck={false}
            />
            <Button
              variant="primary"
              onClick={() => void submit(false)}
              loading={busy === "create"}
              className="sm:w-44"
            >
              Gerar cortes
            </Button>
          </div>
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Quantidade de cortes" hint={form.mode === "auto" ? "a IA decide" : undefined}>
            <Segmented<Mode>
              value={form.mode}
              onChange={(mode) => patch({ mode })}
              options={[
                { value: "auto", label: "Auto", hint: "A IA escolhe N pela densidade do vídeo" },
                { value: "more", label: "+50%", hint: "--more: pede ~50% mais cortes" },
                { value: "count", label: "Fixo", hint: "--count N (só os que passarem do limiar)" },
              ]}
            />
            {form.mode === "count" && (
              <div className="flex items-center gap-3 pt-2">
                <input
                  type="range"
                  min={1}
                  max={20}
                  value={form.count}
                  onChange={(event) => patch({ count: Number(event.target.value) })}
                  className="flex-1 accent-brand-500"
                  aria-label="quantidade de cortes"
                />
                <span className="w-14 rounded-lg bg-white/6 py-1 text-center font-mono text-[0.8rem] text-mist-200">
                  {form.count}
                </span>
              </div>
            )}
          </Field>

          <Field label="Limiar de score" hint={`mínimo ${form.minScore}/100`}>
            <div className="flex items-center gap-3 pt-1.5">
              <input
                type="range"
                min={0}
                max={95}
                step={5}
                value={form.minScore}
                onChange={(event) => patch({ minScore: Number(event.target.value) })}
                className="flex-1 accent-brand-500"
                aria-label="limiar de score"
              />
              <span className="w-14 rounded-lg bg-white/6 py-1 text-center font-mono text-[0.8rem] text-mist-200">
                {form.minScore}
              </span>
            </div>
            <p className="pt-1 text-[0.7rem] text-mist-400">
              Cortes abaixo do limiar são descartados — nunca inventados.
            </p>
          </Field>
        </div>

        <Field label="Formatos de export">
          <div className="flex flex-wrap gap-2">
            {ALL_FORMATS.map((format) => (
              <CheckPill
                key={format}
                checked={form.formats.includes(format)}
                onChange={(checked) =>
                  patch({
                    formats: checked
                      ? [...form.formats, format]
                      : form.formats.filter((item) => item !== format),
                  })
                }
              >
                {config?.format_labels?.[format] ?? FORMAT_OPTION_LABELS[format]}
              </CheckPill>
            ))}
          </div>
        </Field>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Legendas">
            <Segmented<CaptionMode>
              size="sm"
              value={form.captions}
              onChange={(captions) => patch({ captions })}
              options={(config?.caption_modes ?? ["burn", "sidecar", "both"]).map((mode) => ({
                value: mode,
                label: CAPTION_LABELS[mode] ?? mode,
              }))}
            />
            <p className="pt-1 text-[0.7rem] text-mist-400">
              No 9:16 o burn-in fica fora dos ~20% de baixo (UI do TikTok/Shorts).
            </p>
          </Field>

          <Field label="Plataformas do texto social">
            <div className="flex flex-wrap gap-2 pt-1">
              {(["yt", "tiktok"] as Platform[]).map((platform) => (
                <CheckPill
                  key={platform}
                  checked={form.platforms.includes(platform)}
                  onChange={(checked) =>
                    patch({
                      platforms: checked
                        ? [...form.platforms, platform]
                        : form.platforms.filter((item) => item !== platform),
                    })
                  }
                >
                  {platform === "yt" ? "YouTube" : "TikTok"}
                </CheckPill>
              ))}
            </div>
          </Field>
        </div>

        <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
          <Toggle
            checked={form.useBudget}
            onChange={(useBudget) => patch({ useBudget })}
            label="Limitar custo OpenRouter"
            hint="reduz o nº de candidatos ou aborta antes do passo caro"
          />
          <div className={cx("flex items-center gap-2", !form.useBudget && "opacity-40")}>
            <span className="text-[0.8rem] text-mist-400">US$</span>
            <span className="inline-block w-24">
              <TextInput
                value={form.budget}
                onChange={(event) => patch({ budget: event.target.value })}
                disabled={!form.useBudget}
                inputMode="decimal"
                aria-label="orçamento em dólar"
                aria-invalid={form.useBudget && !(Number(form.budget) > 0)}
                className={cx(
                  "text-center font-mono",
                  form.useBudget && !(Number(form.budget) > 0) && "border-red-400/60",
                )}
              />
            </span>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-white/8 pt-4">
          <Button onClick={() => void submit(true)} loading={busy === "dry"}>
            Estimar custo (dry-run)
          </Button>
          <p className="text-[0.75rem] text-mist-400">
            Baixa o vídeo, mede a duração e para antes de transcrever, pontuar e renderizar.
          </p>
        </div>

        {error && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {error}
          </p>
        )}
        {health && !health.openrouter_key && (
          <p className="rounded-xl border border-amber-300/25 bg-amber-300/8 px-3.5 py-2.5 text-[0.8rem] text-amber-100">
            Sem <code>OPENROUTER_API_KEY</code> no <code>.env</code> o job falha na transcrição —
            configure a chave antes de gerar cortes.
          </p>
        )}
      </Card>

      <Card className="space-y-3">
        <h3 className="text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
          Como a IA escolhe a quantidade
        </h3>
        <ul className="grid gap-1.5 text-[0.8rem] text-mist-300 sm:grid-cols-2">
          {(config?.target_ranges ?? []).map((range) => (
            <li key={`${range.from_min}-${range.to_min}`} className="flex justify-between gap-3">
              <span className="text-mist-400">
                {range.to_min ? `${range.from_min}–${range.to_min} min` : `> ${range.from_min} min`}
              </span>
              <span className="font-mono">
                {range.min_clips}–{range.max_clips} cortes
              </span>
            </li>
          ))}
        </ul>
        {health && (
          <p className="border-t border-white/8 pt-3 text-[0.72rem] text-mist-400">
            Modelos: STT <span className="text-mist-300">{health.models.stt}</span> · candidatos{" "}
            <span className="text-mist-300">{health.models.candidates}</span> · score{" "}
            <span className="text-mist-300">{health.models.score}</span>
          </p>
        )}
      </Card>
    </div>
  );
}
