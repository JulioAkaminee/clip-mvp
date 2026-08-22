import { artifactUrl } from "../lib/api";
import { FORMAT_SHORT, formatDuration, scoreRing, scoreTone } from "../lib/format";
import type { Clip } from "../lib/types";
import { Badge, cx } from "./ui";

const VIDEO_KEYS = ["vertical_facetrack", "vertical_center", "horizontal_16x9"] as const;

export function ClipCard({
  clip,
  jobId,
  onOpen,
}: {
  clip: Clip;
  jobId: string;
  onOpen: () => void;
}) {
  const poster = clip.artifacts.poster ? artifactUrl(jobId, clip.slug, clip.artifacts.poster) : null;
  const vertical = clip.windows.vertical_9x16;
  const horizontal = clip.windows.horizontal_16x9;

  return (
    <button
      onClick={onOpen}
      className="group panel overflow-hidden text-left transition-all hover:border-white/20 hover:shadow-xl hover:shadow-black/30 focus-visible:border-brand-400/60"
    >
      <div className="relative aspect-video overflow-hidden bg-ink-850">
        {poster ? (
          <img
            src={poster}
            alt=""
            loading="lazy"
            className="size-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : (
          <div className="grid size-full place-items-center text-mist-400">sem preview</div>
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
              {clip.score}
            </span>
          </div>
        </div>
        {clip.rating && (
          <span className="absolute right-2 top-2">
            <Badge tone={clip.rating === "good" ? "good" : "bad"}>
              {clip.rating === "good" ? "aprovado" : "reprovado"}
            </Badge>
          </span>
        )}
      </div>

      <div className="space-y-2.5 p-3.5">
        <div className="flex flex-wrap gap-1.5">
          {VIDEO_KEYS.filter((key) => clip.artifacts[key]).map((key) => (
            <Badge key={key} tone="neutral">
              {FORMAT_SHORT[key]}
            </Badge>
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
        <p className="line-clamp-2 text-[0.75rem] leading-snug text-mist-400">{clip.reason}</p>
      </div>
    </button>
  );
}
