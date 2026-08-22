import { STAGE_HINTS, formatElapsed } from "../lib/format";
import type { StageState } from "../lib/types";
import { ProgressBar, cx } from "./ui";

const ICONS: Record<string, string> = {
  pending: "·",
  done: "✓",
  skipped: "–",
  error: "✗",
};

/** Lista de estágios do backend, com percentual e tempo de cada um. */
export function StageTimeline({ stages }: { stages: StageState[] }) {
  return (
    <ol className="space-y-1">
      {stages.map((stage) => {
        const active = stage.status === "running";
        const units = stage.units_total > 1 && (active || stage.status === "done");
        return (
          <li
            key={stage.name}
            className={cx(
              "rounded-xl border px-3.5 py-2.5 transition-colors",
              active
                ? "border-brand-400/40 bg-brand-500/8"
                : stage.status === "error"
                  ? "border-red-400/30 bg-red-500/8"
                  : "border-white/8 bg-white/3",
            )}
          >
            <div className="flex items-center gap-3">
              <span
                className={cx(
                  "grid size-5 shrink-0 place-items-center rounded-full border text-[0.65rem]",
                  stage.status === "done"
                    ? "border-lime-300/50 bg-lime-300/15 text-lime-300"
                    : stage.status === "error"
                      ? "border-red-400/50 bg-red-500/15 text-red-200"
                      : active
                        ? "border-brand-400/60 bg-brand-500/20 text-brand-400"
                        : "border-white/12 text-mist-400",
                )}
                aria-hidden
              >
                {active ? (
                  <span className="size-1.5 animate-pulse rounded-full bg-brand-400" />
                ) : (
                  ICONS[stage.status]
                )}
              </span>

              <span className="flex-1 truncate text-[0.82rem] font-medium text-mist-200">
                {stage.label}
                {stage.status === "skipped" && (
                  <span className="ml-2 text-[0.72rem] font-normal text-mist-400">
                    (cache)
                  </span>
                )}
              </span>

              {units && (
                <span className="shrink-0 font-mono text-[0.7rem] text-mist-400">
                  {Math.round(stage.units_done)}/{Math.round(stage.units_total)}
                </span>
              )}
              {stage.elapsed_seconds != null && stage.status !== "pending" && (
                <span className="w-14 shrink-0 text-right font-mono text-[0.7rem] text-mist-400">
                  {formatElapsed(stage.elapsed_seconds)}
                </span>
              )}
            </div>

            {(active || stage.message) && (
              <p
                className="mt-1 truncate pl-8 text-[0.72rem] text-mist-400"
                title={stage.message || STAGE_HINTS[stage.name]}
              >
                {stage.message || STAGE_HINTS[stage.name] || ""}
              </p>
            )}
            {active && (
              <div className="mt-2 pl-8">
                <ProgressBar value={stage.percent / 100} active />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
