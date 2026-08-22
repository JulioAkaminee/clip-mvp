import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl, posterUrl } from "../lib/api";
import {
  ARTIFACT_LABELS,
  SKIP_REASONS,
  VIDEO_ARTIFACTS,
  copyToClipboard,
  formatDuration,
  scoreRing,
  scoreTone,
} from "../lib/format";
import type { Clip } from "../lib/types";
import { Badge, Button, Segmented, TextInput, cx } from "./ui";

type VideoArtifact = (typeof VIDEO_ARTIFACTS)[number];

const VIDEO_LABELS: Record<string, string> = {
  "vertical_facetrack.mp4": "9:16 face tracking",
  "vertical_center.mp4": "9:16 center",
  "horizontal_16x9.mp4": "16:9",
};

const BREAKDOWN_LABELS: Record<string, string> = {
  hook: "Hook (3s)",
  emocao: "Emoção",
  citavel: "Citável",
  arco: "Arco completo",
};

const BREAKDOWN_COLORS: Record<string, string> = {
  hook: "from-brand-600 to-brand-400",
  emocao: "from-fuchsia-600 to-fuchsia-400",
  citavel: "from-amber-500 to-amber-300",
  arco: "from-lime-600 to-lime-300",
};

const SPEAKER_LABELS: Record<string, string> = {
  diarization: "diarização (fala → rosto)",
  activity_proxy: "proxy de atividade facial",
  unavailable: "sem diarização",
};

export function ClipDetail({
  clip,
  jobId,
  onClose,
  onRated,
}: {
  clip: Clip;
  jobId: string;
  onClose: () => void;
  onRated: (slug: string, verdict: "good" | "bad", note: string) => void;
}) {
  const available = useMemo(
    () => VIDEO_ARTIFACTS.filter((name) => clip.artifacts[name]),
    [clip.artifacts],
  );
  const [tab, setTab] = useState<VideoArtifact>(available[0] ?? "horizontal_16x9.mp4");
  const [note, setNote] = useState(clip.rating_note ?? "");
  const [rating, setRating] = useState(clip.rating);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [onClose]);

  const isVertical = tab.startsWith("vertical");
  const horizontal = clip.windows?.horizontal_16x9;
  const vertical = clip.windows?.vertical_9x16;
  const speakerMethod = clip.speaker_matching?.method;

  const rate = async (verdict: "good" | "bad") => {
    setBusy(true);
    try {
      await api.rate(jobId, clip.slug, verdict, note);
      setRating(verdict);
      onRated(clip.slug, verdict, note);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-ink-950/85 p-3 backdrop-blur-sm sm:p-6"
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal
      aria-label={`Corte ${clip.title}`}
    >
      <div className="panel my-auto w-full max-w-5xl overflow-hidden fade-up">
        <header className="flex items-start justify-between gap-4 border-b border-white/8 px-5 py-4">
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-2">
              <span
                className={cx(
                  "grid size-9 place-items-center rounded-xl border font-mono text-sm font-semibold",
                  scoreRing(clip.score),
                  scoreTone(clip.score),
                )}
              >
                {clip.score ?? "—"}
              </span>
              <h2 className="truncate text-base font-semibold text-white">{clip.title}</h2>
            </div>
            <p className="font-mono text-[0.72rem] text-mist-400">{clip.out_dir ?? clip.slug}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar">
            ✕
          </Button>
        </header>

        <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-4">
            {available.length > 0 ? (
              <>
                <Segmented<VideoArtifact>
                  value={tab}
                  onChange={setTab}
                  options={available.map((name) => ({ value: name, label: VIDEO_LABELS[name] }))}
                />
                <div
                  className={cx(
                    "mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black",
                    isVertical ? "max-w-[19rem]" : "w-full",
                  )}
                >
                  <video
                    key={`${clip.slug}-${tab}`}
                    src={artifactUrl(jobId, clip.slug, tab)}
                    poster={posterUrl(jobId, clip.slug)}
                    controls
                    preload="metadata"
                    className={cx("w-full", isVertical ? "aspect-[9/16]" : "aspect-video")}
                  />
                </div>
              </>
            ) : (
              <p className="rounded-xl border border-dashed border-white/12 px-4 py-8 text-center text-[0.82rem] text-mist-400">
                {clip.status === "running"
                  ? "Renderizando este corte…"
                  : "Nenhum vídeo exportado para este corte."}
              </p>
            )}

            {clip.vertical_skipped && (
              <p className="rounded-xl border border-amber-300/25 bg-amber-300/8 px-4 py-3 text-[0.8rem] leading-relaxed text-amber-100">
                {SKIP_REASONS[clip.vertical_skipped] ?? clip.vertical_skipped}
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <WindowCard
                title="16:9 (YouTube)"
                window={horizontal}
                note="duração escolhida pela IA, sem teto fixo"
              />
              <WindowCard
                title="9:16 (Shorts / TikTok)"
                window={vertical}
                note="máximo 90s, sempre em fronteira de frase"
              />
            </div>

            <section className="space-y-2 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Downloads
              </h3>
              <ul className="grid gap-1 sm:grid-cols-2">
                {Object.keys(clip.artifacts).map((name) => (
                  <li key={name}>
                    <a
                      href={artifactUrl(jobId, clip.slug, name, true)}
                      download
                      className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-[0.78rem] text-mist-300 underline-offset-2 transition-colors hover:bg-white/6 hover:text-white hover:underline"
                    >
                      <span>{ARTIFACT_LABELS[name] ?? name}</span>
                      <span className="font-mono text-[0.68rem] text-mist-400">↓</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>
          </div>

          <aside className="space-y-4">
            <section className="space-y-2.5 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Score {clip.score ?? "—"}/100
              </h3>
              <ul className="space-y-2">
                {Object.entries(clip.breakdown ?? {}).map(([key, value]) => (
                  <li key={key} className="space-y-1">
                    <div className="flex justify-between text-[0.74rem]">
                      <span className="text-mist-300">{BREAKDOWN_LABELS[key] ?? key}</span>
                      <span className="font-mono text-mist-400">{Math.round(value)}/25</span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full bg-white/8">
                      <div
                        className={cx(
                          "h-full rounded-full bg-gradient-to-r",
                          BREAKDOWN_COLORS[key] ?? "from-brand-600 to-brand-400",
                        )}
                        style={{ width: `${(Math.min(25, value) / 25) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              {clip.reason && (
                <p className="border-t border-white/8 pt-2.5 text-[0.76rem] leading-snug text-mist-400">
                  {clip.reason}
                </p>
              )}
              <div className="flex flex-wrap gap-1.5">
                {clip.context_complete != null && (
                  <Badge tone={clip.context_complete ? "good" : "warn"}>
                    {clip.context_complete ? "contexto fechado" : "contexto aberto"}
                  </Badge>
                )}
                {speakerMethod && (
                  <Badge tone={speakerMethod === "diarization" ? "neutral" : "warn"}>
                    {SPEAKER_LABELS[speakerMethod] ?? speakerMethod}
                  </Badge>
                )}
              </div>
            </section>

            <SocialPanel clip={clip} />

            <section className="space-y-2.5 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Este corte presta?
              </h3>
              <p className="text-[0.74rem] leading-snug text-mist-400">
                O veredicto vai para <code className="text-mist-300">work/feedback.jsonl</code> e
                entra como few-shot nos próximos prompts de candidatos e score.
              </p>
              <TextInput
                value={note}
                onChange={(event) => setNote(event.target.value)}
                placeholder="nota opcional (ex: começou cedo demais)"
              />
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant={rating === "good" ? "primary" : "outline"}
                  onClick={() => void rate("good")}
                  loading={busy}
                  className="flex-1"
                >
                  Bom
                </Button>
                <Button
                  size="sm"
                  variant={rating === "bad" ? "danger" : "outline"}
                  onClick={() => void rate("bad")}
                  loading={busy}
                  className="flex-1"
                >
                  Ruim
                </Button>
              </div>
            </section>
          </aside>
        </div>
      </div>
    </div>
  );
}

function WindowCard({
  title,
  window: info,
  note,
}: {
  title: string;
  window: { start: number; end: number; duration_s: number } | undefined;
  note?: string;
}) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/3 p-3.5">
      <h4 className="text-[0.74rem] font-semibold text-mist-200">{title}</h4>
      {info ? (
        <>
          <p className="mt-1 font-mono text-lg text-white">{formatDuration(info.duration_s)}</p>
          <p className="font-mono text-[0.7rem] text-mist-400">
            {formatDuration(info.start)} → {formatDuration(info.end)}
          </p>
        </>
      ) : (
        <p className="mt-1 text-[0.8rem] text-mist-400">não exportado</p>
      )}
      {note && <p className="mt-1.5 text-[0.7rem] leading-snug text-mist-400">{note}</p>}
    </div>
  );
}

function SocialPanel({ clip }: { clip: Clip }) {
  const [platform, setPlatform] = useState<"yt_short" | "yt_long" | "tiktok">("yt_short");
  const [copied, setCopied] = useState<string | null>(null);
  const youtube = clip.youtube ?? {};
  const tiktok = clip.tiktok ?? {};
  const hasYoutube = Object.keys(youtube).length > 0;
  const hasTiktok = Object.keys(tiktok).length > 0;

  const copy = async (label: string, value: string) => {
    try {
      await copyToClipboard(value);
      setCopied(label);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied(null);
    }
  };

  if (!hasYoutube && !hasTiktok) {
    return (
      <section className="rounded-2xl border border-white/8 bg-white/3 p-4 text-[0.78rem] text-mist-400">
        Títulos e hashtags aparecem quando o estágio de textos terminar.
      </section>
    );
  }

  const options = [
    ...(hasYoutube ? [{ value: "yt_short" as const, label: "Shorts" }] : []),
    ...(hasYoutube ? [{ value: "yt_long" as const, label: "YT 16:9" }] : []),
    ...(hasTiktok ? [{ value: "tiktok" as const, label: "TikTok" }] : []),
  ];

  const rows: { label: string; value: string }[] =
    platform === "tiktok"
      ? [
          { label: "Caption", value: tiktok.caption ?? "" },
          { label: "Hashtags", value: (tiktok.hashtags ?? []).join(" ") },
        ]
      : platform === "yt_short"
        ? [
            { label: "Título", value: youtube.shorts_title ?? youtube.title ?? "" },
            { label: "Descrição", value: youtube.description ?? "" },
            { label: "Hashtags", value: (youtube.hashtags ?? []).join(" ") },
          ]
        : [
            { label: "Título", value: youtube.long_title ?? youtube.title ?? "" },
            { label: "Descrição", value: youtube.description ?? "" },
            { label: "Tags", value: (youtube.tags ?? []).join(", ") },
          ];

  return (
    <section className="space-y-2.5 rounded-2xl border border-white/8 bg-white/3 p-4">
      <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
        Texto para publicar
      </h3>
      <Segmented size="sm" value={platform} onChange={setPlatform} options={options} />
      <ul className="space-y-2">
        {rows
          .filter((row) => row.value)
          .map((row) => (
            <li key={row.label} className="space-y-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[0.7rem] uppercase tracking-wide text-mist-400">
                  {row.label}
                </span>
                <button
                  onClick={() => void copy(row.label, row.value)}
                  className="text-[0.68rem] text-brand-400 hover:text-brand-500"
                >
                  {copied === row.label ? "copiado" : "copiar"}
                </button>
              </div>
              <p className="rounded-lg bg-ink-950/60 px-2.5 py-1.5 text-[0.76rem] leading-snug text-mist-200">
                {row.value}
              </p>
            </li>
          ))}
      </ul>
    </section>
  );
}
