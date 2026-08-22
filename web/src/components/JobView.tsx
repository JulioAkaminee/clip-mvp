import { useState } from "react";
import { api } from "../lib/api";
import { formatMinutes, formatUsd, shortenUrl } from "../lib/format";
import type { Clip, JobProgress, LogLine } from "../lib/types";
import { ClipCard } from "./ClipCard";
import { ClipDetail } from "./ClipDetail";
import { LogConsole } from "./LogConsole";
import { ProgressHeader } from "./ProgressHeader";
import { StageTimeline } from "./StageTimeline";
import { Badge, Button, Card, EmptyState, Spinner, TextInput, cx } from "./ui";

export function JobView({
  progress,
  clips,
  log,
  live,
  onChanged,
  onRated,
}: {
  progress: JobProgress;
  clips: Clip[];
  log: LogLine[];
  live: boolean;
  onChanged: () => void;
  onRated: (slug: string, verdict: "good" | "bad", note: string) => void;
}) {
  const [openClip, setOpenClip] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [countInput, setCountInput] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);

  const running = progress.status === "running" || progress.status === "queued";
  const summary = progress.result?.summary ?? null;
  const cost = summary?.cost_estimate ?? null;
  const detail = clips.find((clip) => clip.slug === openClip) ?? null;

  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setActionError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5 fade-up">
      <Card className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold tracking-tight text-white">
                {shortenUrl(progress.source_url) || progress.job_id}
              </h2>
              {summary?.dry_run && <Badge tone="warn">dry-run</Badge>}
            </div>
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] text-mist-400">
              <span className="font-mono">{progress.job_id}</span>
              {progress.source_minutes > 0 && (
                <>
                  <span aria-hidden>·</span>
                  <span>fonte {formatMinutes(progress.source_minutes)}</span>
                </>
              )}
              {summary && (
                <>
                  <span aria-hidden>·</span>
                  <span>limiar {Math.round(summary.min_score)}</span>
                </>
              )}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {running ? (
              <Button
                variant="danger"
                size="sm"
                onClick={() => void act("cancel", () => api.cancel(progress.job_id))}
                loading={busy === "cancel"}
              >
                Cancelar
              </Button>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={() =>
                    void act("more", () => api.retry(progress.job_id, { more: true }))
                  }
                  loading={busy === "more"}
                  title="Pede ~50% mais cortes reaproveitando download, transcrição e candidatos do cache"
                >
                  Mais cortes (+50%)
                </Button>
                <div className="flex items-center gap-1.5">
                  <span className="inline-block w-14">
                    <TextInput
                      value={countInput}
                      onChange={(event) => setCountInput(event.target.value)}
                      inputMode="numeric"
                      placeholder="12"
                      aria-label="quantidade de cortes"
                      className="px-2 py-1.5 text-center font-mono text-[0.8rem]"
                    />
                  </span>
                  <span className="text-[0.75rem] text-mist-400">cortes</span>
                  <Button
                    size="sm"
                    disabled={!(Number(countInput) > 0)}
                    onClick={() =>
                      void act("count", () =>
                        api.retry(progress.job_id, { count: Number(countInput) }),
                      )
                    }
                    loading={busy === "count"}
                    title="Refaz a seleção tentando chegar a esse número; entrega menos se não houver momento acima do limiar"
                  >
                    Refazer
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>

        <ProgressHeader progress={progress} live={live} />

        {progress.error && (
          <div
            className={cx(
              "space-y-2 rounded-xl border px-4 py-3",
              progress.stale
                ? "border-amber-300/30 bg-amber-300/8"
                : "border-red-400/30 bg-red-500/10",
            )}
          >
            <p
              className={cx(
                "text-[0.82rem] font-medium",
                progress.stale ? "text-amber-100" : "text-red-100",
              )}
            >
              {progress.stale
                ? `Interrompido em ${progress.error.stage_label}: ${progress.error.message}`
                : `Falhou em ${progress.error.stage_label}: ${progress.error.message}`}
            </p>
            {progress.error.hint && (
              <p className="text-[0.78rem] text-amber-100">{progress.error.hint}</p>
            )}
            {progress.error.retriable && (
              <Button
                size="sm"
                onClick={() => void act("retry", () => api.retry(progress.job_id))}
                loading={busy === "retry"}
              >
                {progress.stale ? "Retomar de onde parou" : "Tentar de novo"}
              </Button>
            )}
          </div>
        )}

        {actionError && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {actionError}
          </p>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <StageTimeline stages={progress.stages} />

          <div className="space-y-3">
            {summary && (
              <div className="space-y-2 rounded-2xl border border-white/8 bg-white/3 p-4">
                <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                  Seleção
                </h3>
                <dl className="grid grid-cols-2 gap-y-1.5 text-[0.78rem]">
                  <Stat label="selecionados" value={summary.selected} strong />
                  <Stat label="candidatos" value={summary.candidates} />
                  <Stat label="dedupe" value={summary.deduped_removed} />
                  <Stat
                    label="abaixo do piso"
                    value={summary.below_floor_removed ?? 0}
                    title={
                      summary.quality_floor != null
                        ? `Cortes acima do limiar mas abaixo de ${Math.round(summary.quality_floor)} — muito distantes do melhor deste vídeo`
                        : undefined
                    }
                  />
                  <Stat label="9:16 ok" value={summary.vertical_ok} />
                  <Stat label="9:16 descartado" value={summary.vertical_skipped} />
                </dl>
                {summary.notes.length > 0 && (
                  <ul className="space-y-1 border-t border-white/8 pt-2">
                    {summary.notes.map((note) => (
                      <li key={note} className="text-[0.72rem] leading-snug text-mist-400">
                        {note}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {cost && (
              <div className="space-y-1.5 rounded-2xl border border-white/8 bg-white/3 p-4">
                <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                  Custo OpenRouter (estimado)
                </h3>
                <p className="font-mono text-lg text-white">{formatUsd(cost.total_usd)}</p>
                <dl className="space-y-0.5 text-[0.72rem] text-mist-400">
                  <Line label={`STT (${cost.stt_minutes.toFixed(1)} min)`} value={cost.stt_usd} />
                  <Line label={`candidatos (${cost.n_candidates})`} value={cost.text_usd} />
                  <Line label="score com vision" value={cost.vision_usd} />
                </dl>
                {summary?.dry_run && (
                  <p className="border-t border-white/8 pt-2 text-[0.72rem] text-amber-200">
                    Dry-run: nada foi transcrito, pontuado ou renderizado.
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>

      <LogConsole entries={log} />

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">
            Cortes <span className="font-mono text-[0.78rem] text-mist-400">{clips.length}</span>
          </h3>
          {running && progress.clips_total > 0 && (
            <span className="flex items-center gap-2 text-[0.75rem] text-mist-400">
              <Spinner className="size-3" /> {progress.clips_done}/{progress.clips_total}{" "}
              renderizados
            </span>
          )}
        </div>

        {clips.length === 0 ? (
          <EmptyState
            title={running ? "Ainda escolhendo os momentos…" : "Nenhum corte entregue"}
            description={
              running
                ? "Os cards aparecem aqui conforme cada corte é renderizado."
                : summary?.dry_run
                  ? "Dry-run só estima custo. Rode o job de novo sem dry-run para exportar."
                  : "Nenhum momento passou do limiar de score — o job não inventa corte fraco. Baixe o limiar ou peça mais cortes."
            }
          />
        ) : (
          <div className={cx("grid gap-4", "sm:grid-cols-2 xl:grid-cols-3")}>
            {clips.map((clip) => (
              <ClipCard
                key={clip.slug}
                clip={clip}
                jobId={progress.job_id}
                onOpen={() => setOpenClip(clip.slug)}
              />
            ))}
          </div>
        )}
      </section>

      {detail && (
        <ClipDetail
          clip={detail}
          jobId={progress.job_id}
          onClose={() => setOpenClip(null)}
          onRated={onRated}
        />
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  strong = false,
  title,
}: {
  label: string;
  value: number;
  strong?: boolean;
  title?: string;
}) {
  return (
    <div className="flex items-baseline gap-1.5" title={title}>
      <dt className="text-mist-400">{label}</dt>
      <dd className={cx("font-mono", strong ? "text-base text-white" : "text-mist-200")}>
        {value}
      </dd>
    </div>
  );
}

function Line({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex justify-between gap-2">
      <dt>{label}</dt>
      <dd className="font-mono text-mist-300">{formatUsd(value)}</dd>
    </div>
  );
}
