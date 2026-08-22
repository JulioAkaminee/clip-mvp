import { useCallback, useEffect, useMemo, useState } from "react";
import { api, bundleUrl } from "../lib/api";
import type { Clip, JobProgress, LogLine } from "../lib/types";
import {
  friendlyError,
  humanDuration,
  pluralize,
  prettyUrl,
  STAGE_SHORT,
  STAGE_STORY,
} from "../lib/format";
import { useArrivals } from "../hooks/useArrivals";
import { ClipCard } from "./ClipCard";
import { ClipDetail } from "./ClipDetail";
import { Button, Callout, Card, EmptyState, LinkButton, ProgressBar, cx } from "./ui";

const clipKey = (clip: Clip) => clip.slug;
const clipReady = (clip: Clip) => clip.status === "done";

/**
 * A tela de um job, em duas velocidades (PRODUCT.md, princípio 3).
 *
 * **Esperando** — o job leva 20 a 30 minutos e a aba fica aberta em segundo
 * plano. A tela precisa responder "está vivo e falta quanto" de relance, de
 * longe, sem ler: percentual grande, uma frase, e os cortes aparecendo à
 * medida que ficam prontos. É o próprio trabalho aparecendo que dá a energia,
 * não enfeite.
 *
 * **Escolhendo** — o job acabou e são 5 a 15 cortes para triar. Aí a tela é
 * densa e responde ao teclado: setas para andar, Enter para abrir, G/R para
 * julgar.
 */
export function JobView({
  progress,
  clips,
  log,
  live,
  onChanged,
  onRated,
  onSubtitlesChanged,
}: {
  progress: JobProgress;
  clips: Clip[];
  log: LogLine[];
  live: boolean;
  onChanged: () => void;
  onRated: (slug: string, verdict: "good" | "bad", note: string) => void;
  onSubtitlesChanged: (slug: string, subtitles: NonNullable<Clip["subtitles"]>) => void;
}) {
  const [openSlug, setOpenSlug] = useState<string | null>(null);
  const [cursor, setCursor] = useState(0);
  const [busy, setBusy] = useState(false);

  const running = progress.status === "running" || progress.status === "queued";
  const finished = progress.status === "done";
  const summary = progress.result?.summary ?? null;
  const ready = useMemo(() => clips.filter(clipReady), [clips]);
  const open = clips.find((clip) => clip.slug === openSlug) ?? null;
  const arrivals = useArrivals(clips, clipKey, clipReady);

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const rate = useCallback(
    async (clip: Clip, verdict: "good" | "bad") => {
      onRated(clip.slug, verdict, "");
      try {
        await api.rate(progress.job_id, clip.slug, verdict);
      } catch {
        /* o card volta ao estado anterior na próxima leitura */
      }
    },
    [onRated, progress.job_id],
  );

  // Triagem por teclado. Só na grade: dentro do detalhe o teclado é do player.
  useEffect(() => {
    if (open || ready.length === 0) return;
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.metaKey || event.ctrlKey || event.altKey) return;

      const move = (delta: number) => {
        event.preventDefault();
        setCursor((i) => Math.max(0, Math.min(ready.length - 1, i + delta)));
      };
      switch (event.key) {
        case "ArrowRight":
        case "j":
          return move(1);
        case "ArrowLeft":
        case "k":
          return move(-1);
        case "Enter":
          event.preventDefault();
          return setOpenSlug(ready[cursor]?.slug ?? null);
        case "g":
          return void rate(ready[cursor], "good");
        case "r":
          return void rate(ready[cursor], "bad");
        default:
          return;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, ready, cursor, rate]);

  if (open) {
    return (
      <ClipDetail
        jobId={progress.job_id}
        clip={open}
        onBack={() => setOpenSlug(null)}
        onRated={onRated}
        onSubtitlesChanged={onSubtitlesChanged}
      />
    );
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4 pt-1">
        <div className="min-w-0">
          <p className="truncate text-[0.78rem] text-mist-400" title={progress.source_url}>
            {progress.source_title?.trim() || prettyUrl(progress.source_url) || progress.job_id}
          </p>
          <h1 className="mt-0.5 text-2xl font-semibold text-white">
            {finished
              ? ready.length > 0
                ? pluralize(ready.length, "corte pronto", "cortes prontos")
                : "Nenhum corte passou"
              : running
                ? "Trabalhando no seu vídeo"
                : progress.status === "error"
                  ? "O processamento parou"
                  : "Cancelado"}
          </h1>
        </div>

        {finished && ready.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <LinkButton size="sm" href={bundleUrl(progress.job_id, "vertical")} download>
              Verticais
            </LinkButton>
            <LinkButton size="sm" href={bundleUrl(progress.job_id, "horizontal")} download>
              Horizontais
            </LinkButton>
            <LinkButton size="sm" href={bundleUrl(progress.job_id, "all")} download>
              Tudo
            </LinkButton>
          </div>
        )}
      </header>

      {progress.status === "error" && progress.error && (
        <ErrorPanel
          progress={progress}
          busy={busy}
          onRetry={() => act(() => api.retry(progress.job_id))}
        />
      )}

      {progress.stale && progress.status !== "error" && (
        <Callout
          tone="warn"
          title="Esse job parou no meio"
          action={
            <Button
              size="sm"
              variant="primary"
              loading={busy}
              onClick={() => void act(() => api.retry(progress.job_id))}
            >
              Continuar de onde parou
            </Button>
          }
        >
          <p>
            O computador foi desligado ou a ferramenta foi fechada durante o processamento. Nada
            do que já foi feito se perdeu.
          </p>
        </Callout>
      )}

      {running && (
        <WaitingPanel
          progress={progress}
          live={live}
          log={log}
          busy={busy}
          onCancel={() => act(() => api.cancel(progress.job_id))}
        />
      )}

      {clips.length > 0 ? (
        <section>
          <div
            className="grid gap-3"
            style={{ gridTemplateColumns: "repeat(auto-fill, minmax(11rem, 1fr))" }}
          >
            {clips.map((clip) => (
              <ClipCard
                key={clip.slug}
                jobId={progress.job_id}
                clip={clip}
                selected={finished && ready[cursor]?.slug === clip.slug}
                isNew={arrivals.has(clip.slug)}
                onOpen={() => setOpenSlug(clip.slug)}
                onFocus={() => {
                  const index = ready.findIndex((item) => item.slug === clip.slug);
                  if (index >= 0) setCursor(index);
                }}
              />
            ))}
          </div>
          {finished && ready.length > 1 && (
            <p className="mt-3 text-[0.72rem] text-mist-400">
              <Key>←</Key> <Key>→</Key> para andar · <Key>Enter</Key> para abrir ·{" "}
              <Key>G</Key> bom · <Key>R</Key> ruim
            </p>
          )}
        </section>
      ) : finished ? (
        <NoClips
          progress={progress}
          busy={busy}
          onRelax={() => act(() => api.retry(progress.job_id, { min_score: 45, more: true }))}
        />
      ) : null}

      {summary && summary.notes.length > 0 && (
        <Card className="space-y-2">
          <h2 className="text-[0.85rem] font-semibold text-mist-200">O que a ferramenta decidiu</h2>
          <ul className="space-y-1.5">
            {summary.notes.map((note, index) => (
              <li key={index} className="flex gap-2 text-[0.8rem] leading-relaxed text-mist-300">
                <span className="mt-1.5 size-1 shrink-0 rounded-full bg-mist-400" aria-hidden />
                <span>{note}</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded border border-white/15 bg-white/6 px-1.5 py-0.5 font-sans text-[0.68rem] text-mist-300">
      {children}
    </kbd>
  );
}

/**
 * O painel de espera. Grande de propósito: quem olha está de longe, de
 * passagem, querendo saber só se ainda anda e quanto falta.
 */
function WaitingPanel({
  progress,
  live,
  log,
  busy,
  onCancel,
}: {
  progress: JobProgress;
  live: boolean;
  log: LogLine[];
  busy: boolean;
  onCancel: () => void;
}) {
  const [showLog, setShowLog] = useState(false);
  const percent = Math.max(0, Math.min(100, progress.percent));
  const story = STAGE_STORY[progress.stage] ?? progress.stage_label;

  return (
    <section className="space-y-4 rounded-2xl border border-white/8 bg-ink-900/60 p-5">
      <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
        <span className="text-5xl leading-none font-semibold tabular-nums text-white">
          {Math.round(percent)}
          <span className="text-2xl text-mist-400">%</span>
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[0.95rem] text-mist-200" aria-live="polite">
            {story}
          </p>
          <p className="mt-0.5 text-[0.8rem] text-mist-400">
            {progress.eta_seconds != null && progress.eta_seconds > 0
              ? `faltam cerca de ${humanDuration(progress.eta_seconds)}`
              : "calculando quanto falta"}
            {progress.clips_total > 0 &&
              ` · ${progress.clips_done} de ${progress.clips_total} cortes prontos`}
          </p>
        </div>
      </div>

      <ProgressBar
        value={percent / 100}
        active
        label="Progresso do processamento"
        valueText={`${Math.round(percent)}% — ${story}`}
        announce
      />

      <ol className="flex flex-wrap gap-1">
        {progress.stages
          .filter((stage) => STAGE_SHORT[stage.name])
          .map((stage) => (
            <li
              key={stage.name}
              className={cx(
                "rounded px-2 py-0.5 text-[0.68rem] transition-colors duration-200",
                stage.status === "done" && "bg-white/6 text-mist-300",
                stage.status === "running" && "bg-brand-500/20 text-brand-400",
                stage.status === "skipped" && "text-mist-400/60 line-through",
                (stage.status === "pending" || stage.status === "error" || !stage.status) &&
                  "text-mist-400/70",
              )}
            >
              {STAGE_SHORT[stage.name]}
            </li>
          ))}
      </ol>

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/8 pt-3">
        <p className="text-[0.72rem] text-mist-400">
          Pode fechar a aba — o processamento continua.
          {!live && " (atualizando por consulta periódica)"}
        </p>
        <div className="flex gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setShowLog((value) => !value)}>
            {showLog ? "Esconder detalhes" : "Detalhes"}
          </Button>
          <Button size="sm" variant="danger" loading={busy} onClick={onCancel}>
            Cancelar
          </Button>
        </div>
      </div>

      {showLog && (
        <div className="max-h-44 overflow-y-auto rounded-lg border border-white/8 bg-black/40 p-3">
          {log.length === 0 ? (
            <p className="text-[0.75rem] text-mist-400">Nada registrado ainda.</p>
          ) : (
            <ul className="space-y-1">
              {log.slice(-60).map((line, index) => (
                <li key={index} className="font-mono text-[0.7rem] leading-relaxed text-mist-400">
                  {line.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

function ErrorPanel({
  progress,
  busy,
  onRetry,
}: {
  progress: JobProgress;
  busy: boolean;
  onRetry: () => void;
}) {
  const error = progress.error!;
  const friendly = friendlyError(error.message, error.hint);
  return (
    <Callout
      tone="bad"
      title={friendly.what}
      action={
        error.retriable !== false && (
          <Button size="sm" variant="primary" loading={busy} onClick={onRetry}>
            Continuar de onde parou
          </Button>
        )
      }
    >
      <p>{friendly.next}</p>
      <p className="mt-2 text-[0.72rem] text-mist-400">
        Parou em: {STAGE_STORY[error.stage] ?? error.stage_label}
      </p>
    </Callout>
  );
}

function NoClips({
  progress,
  busy,
  onRelax,
}: {
  progress: JobProgress;
  busy: boolean;
  onRelax: () => void;
}) {
  const summary = progress.result?.summary;
  const best = summary?.best_score;
  return (
    <EmptyState
      title="Nenhum momento chegou na nota mínima"
      description={
        best != null
          ? `A ferramenta avaliou ${summary?.candidates ?? 0} momentos e o melhor tirou ${Math.round(best)} de 100 — abaixo do que você pediu. Costuma acontecer em vídeo sem picos claros de conversa.`
          : "A ferramenta não encontrou momentos que se sustentem sozinhos neste vídeo."
      }
      icon="○"
    >
      <Button size="sm" variant="primary" loading={busy} onClick={onRelax} className="mt-1">
        Tentar de novo aceitando notas menores
      </Button>
      <p className="mt-1 text-[0.72rem] text-mist-400">
        Reaproveita a transcrição — não custa quase nada.
      </p>
    </EmptyState>
  );
}
