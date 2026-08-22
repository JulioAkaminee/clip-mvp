import { posterUrl } from "../lib/api";
import {
  RENDER_FORMAT_LABELS,
  formatDuration,
  scoreRing,
  scoreTone,
} from "../lib/format";
import type { Clip } from "../lib/types";
import { Badge, Spinner, cx } from "./ui";

const FORMAT_ORDER = ["vertical_facetrack", "vertical_center", "horizontal_16x9"] as const;

const FORMAT_TONE: Record<string, string> = {
  done: "border-lime-300/35 bg-lime-300/10 text-lime-300",
  running: "border-brand-400/50 bg-brand-500/15 text-brand-400",
  error: "border-red-400/35 bg-red-500/12 text-red-200",
};

export function ClipCard({
  clip,
  jobId,
  onOpen,
}: {
  clip: Clip;
  jobId: string;
  onOpen: () => void;
}) {
  const horizontal = clip.windows?.horizontal_16x9;
  const vertical = clip.windows?.vertical_9x16;
  const hasPoster = Boolean(clip.artifacts["poster.jpg"]) || clip.status === "done";
  const rendering = clip.status === "running";

  return (
    <button
      onClick={onOpen}
      title={clip.title}
      className="group panel overflow-hidden text-left transition-all hover:border-white/20 hover:shadow-xl hover:shadow-black/30 focus-visible:border-brand-400/60"
    >
      <div className="relative aspect-video overflow-hidden bg-ink-850">
        {hasPoster ? (
          <img
            src={posterUrl(jobId, clip.slug)}
            alt=""
            loading="lazy"
            className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="grid size-full place-items-center gap-2 text-[0.78rem] text-mist-400">
            {rendering ? (
              <span className="flex items-center gap-2">
                <Spinner className="size-3.5" /> renderizando…
              </span>
            ) : (
              "aguardando render"
            )}
          </div>
        )}

        <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-950 via-ink-950/70 to-transparent p-3">
          <div className="flex items-end justify-between gap-2">
            <span className="line-clamp-2 text-[0.82rem] font-medium leading-snug text-white">
              {clip.title}
            </span>
            <span
              className={cx(
                "grid size-10 shrink-0 place-items-center rounded-xl border font-mono text-sm font-semibold",
                scoreRing(clip.score),
                scoreTone(clip.score),
              )}
              title="score de viralização"
            >
              {clip.score ?? "—"}
            </span>
          </div>
        </div>

        {clip.rating && (
          <span className="absolute left-2 top-2 rounded-full bg-ink-950/70 backdrop-blur-sm">
            <Badge tone={clip.rating === "good" ? "good" : "bad"}>
              {clip.rating === "good" ? "aprovado" : "reprovado"}
            </Badge>
          </span>
        )}
      </div>

      <div className="space-y-2.5 p-3.5">
        {/* Status de render por formato: é isso que mostra o trabalho andando. */}
        <div className="flex flex-wrap gap-1.5">
          {FORMAT_ORDER.filter((key) => clip.formats[key]).map((key) => (
            <span
              key={key}
              className={cx(
                "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] font-medium",
                FORMAT_TONE[clip.formats[key]] ?? "border-white/12 bg-white/6 text-mist-300",
              )}
            >
              {clip.formats[key] === "running" && <Spinner className="size-2.5" />}
              {RENDER_FORMAT_LABELS[key]}
            </span>
          ))}
          {clip.vertical_skipped && <Badge tone="warn">9:16 descartado</Badge>}
        </div>

        <dl className="grid grid-cols-2 gap-1 text-[0.74rem]">
          <div className="flex items-center gap-1.5">
            <dt className="text-mist-400">16:9</dt>
            <dd className="font-mono text-mist-200">
              {formatDuration(horizontal?.duration_s ?? null)}
            </dd>
          </div>
          <div className="flex items-center gap-1.5">
            <dt className="text-mist-400">9:16</dt>
            <dd className="font-mono text-mist-200">
              {vertical ? formatDuration(vertical.duration_s) : "—"}
            </dd>
          </div>
        </dl>

        {(clip.reason || clip.message) && (
          <p className="line-clamp-2 text-[0.75rem] leading-snug text-mist-400">
            {clip.reason || clip.message}
          </p>
        )}
      </div>
    </button>
  );
}
