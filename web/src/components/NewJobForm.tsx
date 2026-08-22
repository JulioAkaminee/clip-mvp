import { useState } from "react";
import { api } from "../lib/api";
import {
  CAPTION_LABELS,
  FORMAT_LABELS,
  formatDuration,
  formatUsd,
} from "../lib/format";
import type {
  AppConfig,
  CaptionMode,
  Estimate,
  FormatName,
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

const ALL_FORMATS: FormatName[] = ["vertical_facetrack", "vertical_center", "horizontal_16x9"];

interface FormState {
  url: string;
  mode: Mode;
  count: number;
  minScore: number;
  formats: FormatName[];
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
    mode: form.mode,
    count: form.mode === "count" ? form.count : null,
    min_score: form.minScore,
    max_score_only: null,
    formats: form.formats,
    captions: form.captions,
    platforms: form.platforms,
    dry_run: dryRun,
    budget_usd: form.useBudget ? Number(form.budget) || null : null,
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
  const [form, setForm] = useState<FormState>(INITIAL);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [busy, setBusy] = useState<"none" | "estimate" | "create">("none");
  const [error, setError] = useState<string | null>(null);

  const patch = (changes: Partial<FormState>) => setForm((current) => ({ ...current, ...changes }));

  const submit = async (dryRun: boolean) => {
    if (!form.url.trim()) {
      setError("Cole a URL do vídeo (ou o caminho de um arquivo local).");
      return;
    }
    setError(null);
    setBusy(dryRun ? "estimate" : "create");
    try {
      if (dryRun) {
        setEstimate(await api.estimate(toRequest(form, true)));
      } else {
        const job = await api.createJob(toRequest(form, false));
        onCreated(job.id);
        setForm((current) => ({ ...current, url: "" }));
        setEstimate(null);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy("none");
    }
  };

  const targetRange = config?.target_ranges ?? [];

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
          contexto da conversa. O 9:16 nunca passa de {config?.vertical_max_s ?? 90}s; o 16:9 tem a
          duração que o arco pedir.
        </p>
      </header>

      <Card className="space-y-5">
        <Field
          label="Link do vídeo"
          hint="YouTube, Twitch ou caminho de arquivo local"
          htmlFor="job-url"
        >
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
          <Field
            label="Quantidade de cortes"
            hint={form.mode === "auto" ? "a IA decide" : undefined}
          >
            <Segmented<Mode>
              value={form.mode}
              onChange={(mode) => patch({ mode })}
              options={[
                { value: "auto", label: "Auto", hint: "A IA escolhe N pela densidade do vídeo" },
                { value: "more", label: "+50%", hint: "--more: pede ~50% mais cortes" },
                { value: "count", label: "Fixo", hint: "--count N (só se passarem do limiar)" },
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
                {FORMAT_LABELS[format]}
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
              No 9:16 o burn-in respeita a safe area (fora dos{" "}
              {Math.round((config?.safe_area_bottom ?? 0.2) * 100)}% de baixo).
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
            hint="reduz candidatos ou aborta se a estimativa estourar"
          />
          <div className={cx("flex items-center gap-2", !form.useBudget && "opacity-40")}>
            <span className="text-[0.8rem] text-mist-400">US$</span>
            <TextInput
              value={form.budget}
              onChange={(event) => patch({ budget: event.target.value })}
              disabled={!form.useBudget}
              inputMode="decimal"
              className="w-24 text-center font-mono"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3 border-t border-white/8 pt-4">
          <Button onClick={() => void submit(true)} loading={busy === "estimate"}>
            Estimar custo (dry-run)
          </Button>
          <p className="text-[0.75rem] text-mist-400">
            Lê só os metadados da fonte: nada é baixado, transcrito ou renderizado.
          </p>
        </div>

        {error && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {error}
          </p>
        )}
      </Card>

      {estimate && <EstimateCard estimate={estimate} />}

      <Card className="space-y-3">
        <h3 className="text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
          Como a IA escolhe a quantidade
        </h3>
        <ul className="grid gap-1.5 text-[0.8rem] text-mist-300 sm:grid-cols-2">
          {targetRange.map((range) => (
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

function EstimateCard({ estimate }: { estimate: Estimate }) {
  const title = (estimate.source?.["title"] as string | undefined) ?? "fonte";
  return (
    <Card className="space-y-4 fade-up">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-white">Estimativa de custo</h3>
          <p className="text-[0.78rem] text-mist-400">
            {title} · {formatDuration(estimate.duration_s)} · {estimate.candidates} candidatos ·
            alvo {estimate.selected} cortes
          </p>
        </div>
        <div className="text-right">
          <div className="font-mono text-xl text-white">{formatUsd(estimate.total_usd)}</div>
          {estimate.budget_usd != null && (
            <Badge tone={estimate.within_budget ? "good" : "bad"}>
              {estimate.within_budget ? "dentro do orçamento" : "acima do orçamento"}
            </Badge>
          )}
        </div>
      </div>
      <ul className="divide-y divide-white/6 text-[0.8rem]">
        {estimate.lines.map((line) => (
          <li key={line.step} className="flex items-center justify-between gap-3 py-1.5">
            <span className="text-mist-300">{line.step}</span>
            <span className="flex items-center gap-3">
              <span className="text-mist-400">{line.detail}</span>
              <span className="w-20 text-right font-mono text-mist-200">{formatUsd(line.usd)}</span>
            </span>
          </li>
        ))}
      </ul>
      {estimate.note && <p className="text-[0.78rem] text-amber-200">{estimate.note}</p>}
    </Card>
  );
}
