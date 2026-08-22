import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl } from "../lib/api";
import {
  FORMAT_LABELS,
  copyToClipboard,
  formatDuration,
  scoreRing,
  scoreTone,
} from "../lib/format";
import type { Clip } from "../lib/types";
import { Badge, Button, Segmented, TextInput, cx } from "./ui";

const VIDEO_KEYS = ["vertical_facetrack", "vertical_center", "horizontal_16x9"] as const;
type VideoKey = (typeof VIDEO_KEYS)[number];

const BREAKDOWN_LABELS: Record<string, string> = {
  hook: "Hook (3s)",
  emocao: "Emoção",
  citavel: "Citável",
  arco: "Arco completo",
};

const SKIP_REASONS: Record<string, string> = {
  context_exceeds_90s:
    "O contexto fechado desse momento passa de 90s, então o 9:16 foi descartado em vez de cortar a frase no meio. Só o 16:9 foi exportado.",
  vertical_window_invalida: "A janela 9:16 proposta era inválida e foi descartada.",
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
    () => VIDEO_KEYS.filter((key) => clip.artifacts[key]),
    [clip.artifacts],
  );
  const [tab, setTab] = useState<VideoKey>(available[0] ?? "horizontal_16x9");
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

  const isVertical = tab !== "horizontal_16x9";
  const window16x9 = clip.windows.horizontal_16x9;
  const window9x16 = clip.windows.vertical_9x16;

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
                {clip.score}
              </span>
              <h2 className="truncate text-base font-semibold text-white">{clip.title}</h2>
            </div>
            <p className="font-mono text-[0.72rem] text-mist-400">{clip.slug}</p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Fechar">
            ✕
          </Button>
        </header>

        <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-4">
            {available.length > 0 ? (
              <>
                <Segmented<VideoKey>
                  value={tab}
                  onChange={setTab}
                  options={available.map((key) => ({ value: key, label: FORMAT_LABELS[key] }))}
                />
                <div
                  className={cx(
                    "mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black",
                    isVertical ? "max-w-[19rem]" : "w-full",
                  )}
                >
                  <video
                    key={`${clip.slug}-${tab}`}
                    src={artifactUrl(jobId, clip.slug, clip.artifacts[tab])}
                    poster={
                      clip.artifacts.poster
                        ? artifactUrl(jobId, clip.slug, clip.artifacts.poster)
                        : undefined
                    }
                    controls
                    preload="metadata"
                    className={cx("w-full", isVertical ? "aspect-[9/16]" : "aspect-video")}
                  />
                </div>
              </>
            ) : (
              <p className="rounded-xl border border-dashed border-white/12 px-4 py-8 text-center text-[0.82rem] text-mist-400">
                Nenhum vídeo exportado para este corte.
              </p>
            )}

            {clip.vertical_skipped && (
              <p className="rounded-xl border border-amber-300/25 bg-amber-300/8 px-4 py-3 text-[0.8rem] leading-relaxed text-amber-100">
                {SKIP_REASONS[clip.vertical_skipped] ?? clip.vertical_skipped}
              </p>
            )}

            <div className="grid gap-3 sm:grid-cols-2">
              <WindowCard title="16:9 (YouTube)" window={window16x9} note="duração escolhida pela IA" />
              <WindowCard
                title="9:16 (Shorts / TikTok)"
                window={window9x16}
                note={
                  window9x16?.note === "shrunk_to_90s"
                    ? "encolhido para caber em 90s sem cortar frase"
                    : "máximo 90s"
                }
              />
            </div>

            {clip.transcript_text && <Transcript text={clip.transcript_text} />}
          </div>

          <aside className="space-y-4">
            <section className="space-y-2.5 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Score {clip.score}/100
              </h3>
              <ul className="space-y-2">
                {Object.entries(clip.breakdown).map(([key, value]) => (
                  <li key={key} className="space-y-1">
                    <div className="flex justify-between text-[0.74rem]">
                      <span className="text-mist-300">{BREAKDOWN_LABELS[key] ?? key}</span>
                      <span className="font-mono text-mist-400">{value}/25</span>
                    </div>
                    <div className="h-1 overflow-hidden rounded-full bg-white/8">
                      <div
                        className="h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400"
                        style={{ width: `${(Math.min(25, value) / 25) * 100}%` }}
                      />
                    </div>
                  </li>
                ))}
              </ul>
              <p className="border-t border-white/8 pt-2.5 text-[0.76rem] leading-snug text-mist-400">
                {clip.reason}
              </p>
              <div className="flex flex-wrap gap-1.5">
                <Badge tone={clip.context_complete ? "good" : "warn"}>
                  {clip.context_complete ? "contexto fechado" : "contexto incompleto"}
                </Badge>
                <Badge>fronteira por {clip.boundary_method === "word" ? "palavra" : "segmento"}</Badge>
                {clip.face_track && <Badge>{clip.face_track}</Badge>}
              </div>
            </section>

            <SocialPanel clip={clip} />

            <section className="space-y-2 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Downloads
              </h3>
              <ul className="space-y-1">
                {Object.entries(clip.artifacts).map(([key, name]) => (
                  <li key={key}>
                    <a
                      href={artifactUrl(jobId, clip.slug, name, true)}
                      download
                      className="flex items-center justify-between gap-2 rounded-lg px-2 py-1.5 text-[0.78rem] text-mist-300 transition-colors hover:bg-white/6 hover:text-white"
                    >
                      <span>{FORMAT_LABELS[key] ?? key.replace(/_/g, " ")}</span>
                      <span className="font-mono text-[0.7rem] text-mist-400">{name}</span>
                    </a>
                  </li>
                ))}
              </ul>
            </section>

            <section className="space-y-2.5 rounded-2xl border border-white/8 bg-white/3 p-4">
              <h3 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
                Este corte presta?
              </h3>
              <p className="text-[0.74rem] leading-snug text-mist-400">
                O veredicto entra como few-shot nos próximos prompts de candidatos e score.
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
  window: Clip["windows"]["horizontal_16x9"];
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

function Transcript({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="rounded-2xl border border-white/8 bg-white/3 p-4">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-2 text-[0.78rem] font-semibold text-mist-200"
        aria-expanded={open}
      >
        Transcrição do corte
        <span className={cx("text-mist-400 transition-transform", open && "rotate-90")} aria-hidden>
          ▸
        </span>
      </button>
      <p
        className={cx(
          "mt-2 text-[0.8rem] leading-relaxed text-mist-300",
          !open && "line-clamp-3",
        )}
      >
        {text}
      </p>
    </div>
  );
}

function SocialPanel({ clip }: { clip: Clip }) {
  const [platform, setPlatform] = useState<"yt_short" | "yt_long" | "tiktok">("yt_short");
  const [copied, setCopied] = useState<string | null>(null);
  const youtube = clip.meta?.youtube;
  const tiktok = clip.meta?.tiktok;

  const copy = async (label: string, value: string) => {
    try {
      await copyToClipboard(value);
      setCopied(label);
      setTimeout(() => setCopied(null), 1600);
    } catch {
      setCopied(null);
    }
  };

  if (!youtube && !tiktok) {
    return (
      <section className="rounded-2xl border border-white/8 bg-white/3 p-4 text-[0.78rem] text-mist-400">
        Títulos e hashtags aparecem quando a etapa de meta terminar.
      </section>
    );
  }

  const options = [
    ...(youtube ? [{ value: "yt_short" as const, label: "Shorts" }] : []),
    ...(youtube ? [{ value: "yt_long" as const, label: "YT 16:9" }] : []),
    ...(tiktok ? [{ value: "tiktok" as const, label: "TikTok" }] : []),
  ];

  const rows: { label: string; value: string }[] =
    platform === "tiktok"
      ? [
          { label: "Caption", value: tiktok?.caption ?? "" },
          { label: "Hashtags", value: (tiktok?.hashtags ?? []).join(" ") },
        ]
      : platform === "yt_short"
        ? [
            { label: "Título", value: youtube?.shorts_title ?? "" },
            { label: "Descrição", value: youtube?.description ?? "" },
            { label: "Hashtags", value: (youtube?.hashtags ?? []).join(" ") },
          ]
        : [
            { label: "Título", value: youtube?.long_title ?? youtube?.shorts_title ?? "" },
            { label: "Descrição", value: youtube?.description ?? "" },
            { label: "Tags", value: (youtube?.tags ?? []).join(", ") },
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
