import { formatElapsed } from "../lib/format";
import type { JobProgress } from "../lib/types";
import { Badge, ProgressBar, cx } from "./ui";

const STATUS_LABEL: Record<string, string> = {
  queued: "na fila",
  running: "rodando",
  done: "concluído",
  error: "erro",
  canceled: "cancelado",
};

/**
 * Bloco de progresso: percentual global, estágio atual e minutos restantes —
 * os três campos que o backend calcula (`percent`, `stage_label`, `eta_text`).
 */
export function ProgressHeader({
  progress,
  live,
}: {
  progress: JobProgress;
  live: boolean;
}) {
  const running = progress.status === "running" || progress.status === "queued";
  const done = progress.status === "done";
  const failed = progress.status === "error";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2">
        <div className="flex items-baseline gap-3">
          <span
            className={cx(
              "font-mono text-4xl leading-none tracking-tight",
              failed ? "text-red-300" : done ? "text-lime-300" : "text-white",
            )}
          >
            {Math.round(progress.percent)}
            <span className="text-xl text-mist-400">%</span>
          </span>
          <span className="pb-0.5 text-[0.9rem] text-mist-200">{progress.stage_label}</span>
          {running && live && <Badge tone="brand">ao vivo</Badge>}
          {running && !live && <Badge>polling</Badge>}
        </div>

        <div className="text-right">
          <div
            className={cx(
              "font-mono text-lg",
              running ? "text-brand-400" : "text-mist-300",
            )}
            aria-live="polite"
          >
            {running ? progress.eta_text : STATUS_LABEL[progress.status] ?? progress.status}
          </div>
          <div className="text-[0.72rem] text-mist-400">
            {progress.clips_total > 0 && (
              <span>
                {progress.clips_done}/{progress.clips_total} cortes ·{" "}
              </span>
            )}
            {formatElapsed(progress.elapsed_seconds)} decorridos
          </div>
        </div>
      </div>

      <ProgressBar value={progress.percent / 100} active={running} tone={failed ? "error" : done ? "done" : "brand"} />

      {progress.message && (
        <p className="truncate text-[0.8rem] text-mist-400" title={progress.message}>
          {progress.message}
        </p>
      )}
    </div>
  );
}
