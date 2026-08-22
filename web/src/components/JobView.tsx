import { useState } from "react";
import { api } from "../lib/api";
import { CAPTION_LABELS, formatDuration, formatRelative, formatUsd } from "../lib/format";
import type { Clip, Job } from "../lib/types";
import { ClipCard } from "./ClipCard";
import { ClipDetail } from "./ClipDetail";
import { LogConsole } from "./LogConsole";
import { StageTimeline } from "./StageTimeline";
import { Badge, Button, Card, EmptyState, Spinner, StatusDot, TextInput, cx } from "./ui";

const STATUS_LABEL: Record<string, string> = {
  queued: "na fila",
  running: "rodando",
  done: "concluído",
  error: "erro",
  canceled: "cancelado",
};

export function JobView({
  job,
  connected,
  onChanged,
  onDeleted,
}: {
  job: Job;
  connected: boolean;
  onChanged: () => void;
  onDeleted: () => void;
}) {
  const [openClip, setOpenClip] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [countInput, setCountInput] = useState(String(job.selection?.selected || 8));
  const [error, setError] = useState<string | null>(null);
  const [clips, setClips] = useState<Clip[] | null>(null);

  const visibleClips = clips ?? job.clips;
  const active = job.status === "running" || job.status === "queued";
  const selected = job.selection;

  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    setError(null);
    try {
      await action();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  };

  const applyRating = (slug: string, verdict: "good" | "bad", note: string) => {
    setClips(
      (clips ?? job.clips).map((clip) =>
        clip.slug === slug ? { ...clip, rating: verdict, rating_note: note } : clip,
      ),
    );
  };

  const detail = visibleClips.find((clip) => clip.slug === openClip) ?? null;

  return (
    <div className="space-y-5 fade-up">
      <Card className="space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <StatusDot status={job.status} />
              <span className="text-[0.75rem] font-medium uppercase tracking-wide text-mist-400">
                {STATUS_LABEL[job.status] ?? job.status}
              </span>
              {active && connected && <Badge tone="brand">ao vivo</Badge>}
              {job.options.dry_run && <Badge tone="warn">dry-run</Badge>}
              {job.resumed_from && <Badge>resume</Badge>}
            </div>
            <h2 className="truncate text-xl font-semibold tracking-tight text-white">
              {job.source?.title || job.url}
            </h2>
            <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.75rem] text-mist-400">
              <span className="font-mono">{job.id}</span>
              <span aria-hidden>·</span>
              <span>{formatRelative(job.created_at)}</span>
              {job.source?.duration_s ? (
                <>
                  <span aria-hidden>·</span>
                  <span>fonte {formatDuration(job.source.duration_s)}</span>
                </>
              ) : null}
              <span aria-hidden>·</span>
              <span>modo {job.options.mode}</span>
              <span aria-hidden>·</span>
              <span>limiar {job.options.min_score}</span>
              <span aria-hidden>·</span>
              <span>{CAPTION_LABELS[job.options.captions] ?? job.options.captions}</span>
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {active ? (
              <Button
                variant="danger"
                size="sm"
                onClick={() => void act("cancel", () => api.cancel(job.id))}
                loading={busy === "cancel"}
              >
                Cancelar
              </Button>
            ) : (
              <>
                <Button
                  size="sm"
                  onClick={() => void act("more", () => api.resume(job.id, { mode: "more" }))}
                  loading={busy === "more"}
                  title="Pede ~50% mais cortes reaproveitando transcrição e scores"
                >
                  Mais cortes
                </Button>
                <div className="flex items-center gap-1.5">
                  <TextInput
                    value={countInput}
                    onChange={(event) => setCountInput(event.target.value)}
                    inputMode="numeric"
                    aria-label="quantidade de cortes"
                    className="w-16 px-2 py-1.5 text-center font-mono text-[0.8rem]"
                  />
                  <Button
                    size="sm"
                    onClick={() =>
                      void act("count", () =>
                        api.resume(job.id, { mode: "count", count: Number(countInput) || 1 }),
                      )
                    }
                    loading={busy === "count"}
                    title="Força até N cortes (só os que passarem do limiar)"
                  >
                    Refazer com N
                  </Button>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    void act("delete", async () => {
                      await api.remove(job.id, false);
                      onDeleted();
                    })
                  }
                  loading={busy === "delete"}
                >
                  Remover
                </Button>
              </>
            )}
          </div>
        </div>

        {error && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {error}
          </p>
        )}
        {job.error && (
          <p className="rounded-xl border border-red-400/30 bg-red-500/10 px-3.5 py-2.5 text-[0.8rem] text-red-200">
            {job.error}
          </p>
        )}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <StageTimeline stages={job.stages} />
          <div className="space-y-3">
            {selected && (
              <div className="space-y-2 rounded-2xl border border-white/8 bg-white/3 p-4">
                <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                  Seleção
                </h3>
                <dl className="grid grid-cols-2 gap-y-1.5 text-[0.78rem]">
                  <Stat label="selecionados" value={selected.selected} strong />
                  <Stat label="candidatos" value={selected.candidates} />
                  <Stat label="dedupe" value={selected.deduped} />
                  <Stat label="abaixo do limiar" value={selected.below_threshold} />
                  <Stat label="9:16 ok" value={selected.vertical_ok} />
                  <Stat label="9:16 descartado" value={selected.vertical_skipped} />
                </dl>
                <p className="border-t border-white/8 pt-2 text-[0.72rem] leading-snug text-mist-400">
                  {selected.reason}
                </p>
              </div>
            )}
            {job.estimate && (
              <div className="space-y-1 rounded-2xl border border-white/8 bg-white/3 p-4">
                <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                  Custo OpenRouter
                </h3>
                <p className="font-mono text-lg text-white">
                  {formatUsd(job.estimate.total_usd)}
                </p>
                <p className="text-[0.72rem] text-mist-400">
                  estimado para {job.estimate.candidates} candidatos
                  {job.estimate.budget_usd != null &&
                    ` · orçamento ${formatUsd(job.estimate.budget_usd)}`}
                </p>
                {job.estimate.note && (
                  <p className="text-[0.72rem] text-amber-200">{job.estimate.note}</p>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>

      <LogConsole entries={job.log} />

      <section className="space-y-3">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-sm font-semibold text-white">
            Cortes{" "}
            <span className="font-mono text-[0.78rem] text-mist-400">{visibleClips.length}</span>
          </h3>
          {active && (
            <span className="flex items-center gap-2 text-[0.75rem] text-mist-400">
              <Spinner className="size-3" /> os cortes aparecem conforme renderizam
            </span>
          )}
        </div>

        {visibleClips.length === 0 ? (
          <EmptyState
            title={active ? "Renderizando…" : "Nenhum corte entregue"}
            description={
              active
                ? "Os cards aparecem aqui em tempo real, um por corte finalizado."
                : job.status === "done"
                  ? "Nenhum momento passou do limiar de score. Baixe o limiar ou tente --more; o job não inventa corte ruim."
                  : "Sem cortes para este job."
            }
          />
        ) : (
          <div
            className={cx(
              "grid gap-4",
              "sm:grid-cols-2 xl:grid-cols-3",
            )}
          >
            {visibleClips.map((clip) => (
              <ClipCard
                key={clip.slug}
                clip={clip}
                jobId={job.id}
                onOpen={() => setOpenClip(clip.slug)}
              />
            ))}
          </div>
        )}
      </section>

      {detail && (
        <ClipDetail
          clip={detail}
          jobId={job.id}
          onClose={() => setOpenClip(null)}
          onRated={applyRating}
        />
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  strong = false,
}: {
  label: string;
  value: number;
  strong?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <dt className="text-mist-400">{label}</dt>
      <dd className={cx("font-mono", strong ? "text-base text-white" : "text-mist-200")}>
        {value}
      </dd>
    </div>
  );
}
