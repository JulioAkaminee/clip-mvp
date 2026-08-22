import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "../lib/api";
import type {
  AppConfig,
  FormatKey,
  Health,
  JobRequest,
  VideoProbeResult,
} from "../lib/types";
import {
  FORMATS,
  formatUsd,
  humanDuration,
  STRICTNESS,
  type StrictnessOption,
} from "../lib/format";
import { SubtitleStudio, type SubtitleConfig } from "./SubtitleStudio";
import {
  Button,
  Callout,
  Card,
  ChoiceCard,
  Disclosure,
  Field,
  Skeleton,
  TextInput,
  Toggle,
  cx,
} from "./ui";

type Amount = "auto" | "more" | "count";

const DEFAULT_SUBTITLES: SubtitleConfig = {
  style: "viral",
  positionV: 0.2,
  fontSize: 1.1,
  textColor: "#FFDE00",
  outlineColor: "#111111",
  uppercase: true,
  highlight: "pop",
  highlightColor: "#FFFFFF",
};

/**
 * Tela inicial: um campo e um botão.
 *
 * Tudo o que não é "cole o link" mora atrás de **Ajustes**, fechado por
 * padrão. Quem só quer cortes não precisa saber que existe limiar de score,
 * orçamento em dólar ou três formatos de saída; quem quer, abre e encontra
 * tudo com nome de gente.
 */
export function NewJob({
  config,
  health,
  onCreated,
}: {
  config: AppConfig | null;
  health: Health | null;
  onCreated: (jobId: string) => void;
}) {
  const [url, setUrl] = useState("");
  const [probe, setProbe] = useState<VideoProbeResult | null>(null);
  const [probing, setProbing] = useState(false);
  const [amount, setAmount] = useState<Amount>("auto");
  const [count, setCount] = useState(6);
  const [strictness, setStrictness] = useState<StrictnessOption>(STRICTNESS[1]);
  const [formats, setFormats] = useState<FormatKey[]>(["face", "16x9"]);
  const [subtitles, setSubtitles] = useState<SubtitleConfig>(DEFAULT_SUBTITLES);
  const [budgetOn, setBudgetOn] = useState(false);
  const [budget, setBudget] = useState("2.00");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const probeToken = useRef(0);
  const trimmed = url.trim();
  const looksLikeUrl = /^https?:\/\/\S+\.\S+/.test(trimmed);

  const runProbe = useCallback(async (value: string) => {
    const token = ++probeToken.current;
    setProbing(true);
    try {
      const result = await api.probeVideo(value);
      if (probeToken.current === token) setProbe(result);
    } catch {
      if (probeToken.current === token) setProbe(null);
    } finally {
      if (probeToken.current === token) setProbing(false);
    }
  }, []);

  // Olhar o vídeo assim que o link parece um link: a pessoa confirma que colou
  // o que queria e já vê custo e tempo antes de gastar qualquer coisa.
  useEffect(() => {
    if (!looksLikeUrl) {
      setProbe(null);
      probeToken.current++;
      setProbing(false);
      return;
    }
    const timer = window.setTimeout(() => void runProbe(trimmed), 550);
    return () => window.clearTimeout(timer);
  }, [trimmed, looksLikeUrl, runProbe]);

  const toggleFormat = (key: FormatKey) => {
    setFormats((current) =>
      current.includes(key) ? current.filter((item) => item !== key) : [...current, key],
    );
  };

  const submit = async () => {
    if (!looksLikeUrl || formats.length === 0) return;
    setSubmitting(true);
    setError(null);
    const payload: JobRequest = {
      url: trimmed,
      more: amount === "more",
      count: amount === "count" ? count : null,
      min_score: strictness.minScore,
      max_score_only: null,
      formats,
      captions: "both",
      platforms: ["yt", "tiktok"],
      dry_run: false,
      budget: budgetOn ? Number(budget.replace(",", ".")) || null : null,
      subtitle_style: subtitles.style,
      subtitle_position_v: subtitles.positionV,
      subtitle_font_size: subtitles.fontSize,
      subtitle_color: subtitles.textColor,
      subtitle_outline_color: subtitles.outlineColor,
      subtitle_uppercase: subtitles.uppercase,
      subtitle_highlight: subtitles.highlight,
      subtitle_highlight_color: subtitles.highlightColor,
    };
    try {
      const created = await api.createJob(payload);
      onCreated(created.job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSubmitting(false);
    }
  };

  const noKey = health != null && !health.openrouter_key;
  const noFacetrack = health != null && !health.mediapipe && formats.includes("face");
  const estimate = probe?.ok ? probe.estimate : null;

  return (
    <div className="mx-auto max-w-3xl space-y-5">
      <header className="space-y-1.5 pt-2">
        <h1 className="text-2xl font-semibold text-white">Novo corte</h1>
        <p className="text-[0.88rem] text-mist-300">
          Cole o link de um vídeo longo. A ferramenta escolhe os melhores momentos e devolve
          cada um pronto para publicar.
        </p>
      </header>

      {noKey && (
        <Callout
          tone="warn"
          title="Falta configurar a chave da OpenRouter"
          action={
            <Button size="sm" variant="outline" onClick={() => window.location.reload()}>
              Ir para a configuração
            </Button>
          }
        >
          <p>Sem ela a ferramenta não consegue transcrever nem escolher os momentos.</p>
        </Callout>
      )}

      <Card className="space-y-4">
        <Field label="Link do vídeo" htmlFor="video-url" hint="YouTube, Twitch e outros">
          <div className="flex flex-col gap-2 sm:flex-row">
            <TextInput
              id="video-url"
              value={url}
              autoFocus
              inputMode="url"
              spellCheck={false}
              placeholder="https://youtube.com/watch?v=..."
              onChange={(event) => setUrl(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && looksLikeUrl && !submitting) void submit();
              }}
            />
            <Button
              variant="primary"
              className="shrink-0 sm:w-40"
              onClick={() => void submit()}
              disabled={!looksLikeUrl || submitting || formats.length === 0}
              loading={submitting}
            >
              Gerar cortes
            </Button>
          </div>
        </Field>

        {probing && (
          <div className="flex gap-3 rounded-xl border border-white/8 bg-white/3 p-3">
            <Skeleton className="h-16 w-28 shrink-0" />
            <div className="flex-1 space-y-2 py-1">
              <Skeleton className="h-3 w-3/5" />
              <Skeleton className="h-3 w-2/5" />
            </div>
          </div>
        )}

        {!probing && probe?.ok && (
          <div className="fade-up flex flex-col gap-3 rounded-xl border border-white/8 bg-white/3 p-3 sm:flex-row">
            {probe.thumbnail && (
              <img
                src={probe.thumbnail}
                alt=""
                className="h-20 w-full shrink-0 rounded-lg object-cover sm:w-32"
              />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-[0.9rem] font-medium text-mist-200">{probe.title}</p>
              <p className="mt-0.5 text-[0.78rem] text-mist-400">
                {probe.uploader && <span>{probe.uploader} · </span>}
                {probe.duration_s > 0 ? humanDuration(probe.duration_s) : "duração desconhecida"}
              </p>
              {estimate && (
                <p className="mt-2 text-[0.78rem] text-mist-300">
                  Deve render <strong className="text-mist-200">
                    {estimate.clips_min} a {estimate.clips_max} cortes
                  </strong>
                  , levar cerca de{" "}
                  <strong className="text-mist-200">{humanDuration(estimate.seconds)}</strong> e
                  custar por volta de{" "}
                  <strong className="text-mist-200">{formatUsd(estimate.cost_usd)}</strong> na
                  OpenRouter.
                </p>
              )}
            </div>
          </div>
        )}

        {!probing && probe && !probe.ok && (
          <Callout tone="warn" title="Não consegui ler esse link">
            <p>
              {probe.error ||
                "Confira se o vídeo abre normalmente numa aba anônima. Dá para tentar mesmo assim — o erro vai aparecer com mais detalhe."}
            </p>
          </Callout>
        )}

        {error && (
          <Callout tone="bad" title="Não deu para iniciar">
            <p>{error}</p>
          </Callout>
        )}
      </Card>

      <Disclosure
        summary="Ajustes"
        hint={`${amount === "auto" ? "Quantidade automática" : amount === "more" ? "Mais cortes" : `${count} cortes`} · ${strictness.name.toLowerCase()} · ${formats.length} formato${formats.length === 1 ? "" : "s"}`}
      >
        <section className="space-y-2" role="radiogroup" aria-label="Quantos cortes">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">Quantos cortes?</h3>
          <ChoiceCard
            selected={amount === "auto"}
            onSelect={() => setAmount("auto")}
            title="Deixe a ferramenta decidir"
            description={
              config
                ? "Vídeo curto rende poucos cortes; podcast de duas horas rende muitos. Recomendado."
                : "Recomendado."
            }
          />
          <ChoiceCard
            selected={amount === "more"}
            onSelect={() => setAmount("more")}
            title="Quero mais opções"
            description="Cerca de 50% a mais de cortes, ainda respeitando a nota mínima."
          />
          <ChoiceCard
            selected={amount === "count"}
            onSelect={() => setAmount("count")}
            title="Número exato"
            description="Só entrega esse tanto se houver momento bom o suficiente — nunca inventa corte fraco."
          />
          {amount === "count" && (
            <div className="flex items-center gap-3 pl-7">
              <input
                type="range"
                min={1}
                max={20}
                value={count}
                onChange={(event) => setCount(Number(event.target.value))}
                className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/15 accent-brand-500"
                aria-label="Número de cortes"
              />
              <span className="w-20 text-right text-[0.8rem] text-mist-200">
                {count} corte{count === 1 ? "" : "s"}
              </span>
            </div>
          )}
        </section>

        <section className="space-y-2" role="radiogroup" aria-label="Rigor da seleção">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">Quão exigente ser?</h3>
          {STRICTNESS.map((option) => (
            <ChoiceCard
              key={option.id}
              selected={strictness.id === option.id}
              onSelect={() => setStrictness(option)}
              title={option.name}
              description={option.description}
            />
          ))}
        </section>

        <section className="space-y-2">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">Quais versões gerar?</h3>
          {FORMATS.map((format) => {
            const checked = formats.includes(format.key);
            return (
              <label
                key={format.key}
                className={cx(
                  "flex w-full cursor-pointer items-start gap-3 rounded-xl border p-3 transition-all",
                  checked
                    ? "border-brand-400/60 bg-brand-500/10"
                    : "border-white/10 bg-white/3 hover:border-white/25",
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={() => toggleFormat(format.key)}
                  className="mt-0.5 size-4 shrink-0 accent-brand-500"
                />
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="text-[0.85rem] font-medium text-mist-200">{format.name}</span>
                    <span className="rounded-full border border-white/12 bg-white/6 px-2 py-0.5 text-[0.68rem] text-mist-400">
                      {format.where}
                    </span>
                  </span>
                  <span className="mt-0.5 block text-[0.75rem] leading-relaxed text-mist-400">
                    {format.description}
                  </span>
                </span>
              </label>
            );
          })}
          {formats.length === 0 && (
            <p className="text-[0.75rem] text-amber-200">Escolha pelo menos uma versão.</p>
          )}
          {noFacetrack && (
            <Callout tone="warn" title="O zoom no rosto não está disponível">
              <p>
                Falta a biblioteca de detecção de rosto. O vídeo vertical vai sair com o quadro
                inteiro. Para habilitar, rode no Terminal:
              </p>
              <code className="mt-2 block rounded-lg bg-black/40 px-3 py-2 font-mono text-[0.72rem]">
                pip install 'clip-mvp[facetrack]'
              </code>
            </Callout>
          )}
        </section>

        <section className="space-y-2">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">Estilo da legenda</h3>
          <p className="text-[0.75rem] text-mist-400">
            A legenda é queimada no vídeo vertical. Dá para trocar depois, corte a corte.
          </p>
          <SubtitleStudio
            config={subtitles}
            onChange={setSubtitles}
            videoThumbnail={probe?.thumbnail ?? null}
          />
        </section>

        <section className="space-y-2">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">Limite de gasto</h3>
          <Toggle
            checked={budgetOn}
            onChange={setBudgetOn}
            label="Parar se passar de um valor"
            hint="A ferramenta reduz o trabalho ou avisa antes de gastar acima do limite."
          />
          {budgetOn && (
            <div className="flex items-center gap-2 pl-1">
              <span className="text-[0.8rem] text-mist-400">US$</span>
              <TextInput
                value={budget}
                inputMode="decimal"
                onChange={(event) => setBudget(event.target.value)}
                className="w-28"
                aria-label="Limite de gasto em dólares"
              />
            </div>
          )}
        </section>
      </Disclosure>

      <p className="pb-6 text-center text-[0.75rem] text-mist-400">
        Nada é enviado para lugar nenhum além da OpenRouter. Os vídeos ficam no seu computador.
      </p>
    </div>
  );
}
