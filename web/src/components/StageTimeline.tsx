import { STAGE_HINTS } from "../lib/format";
import type { Stage } from "../lib/types";
import { ProgressBar, cx } from "./ui";

const ICONS: Record<string, string> = {
  pending: "·",
  running: "",
  done: "✓",
  skipped: "–",
  error: "✗",
};

export function StageTimeline({ stages }: { stages: Stage[] }) {
  return (
    <ol className="space-y-1">
      {stages.map((stage) => {
        const active = stage.status === "running";
        return (
          <li
            key={stage.key}
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
              <span className="flex-1 text-[0.82rem] font-medium text-mist-200">{stage.label}</span>
              <span className="max-w-[55%] truncate text-right text-[0.72rem] text-mist-400">
                {stage.message || STAGE_HINTS[stage.key] || ""}
              </span>
            </div>
            {active && (
              <div className="mt-2 pl-8">
                <ProgressBar value={stage.progress} active />
              </div>
            )}
          </li>
        );
      })}
    </ol>
  );
}
