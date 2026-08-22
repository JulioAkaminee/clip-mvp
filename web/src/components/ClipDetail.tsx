import { useEffect, useMemo, useState } from "react";
import { api, artifactUrl, posterUrl } from "../lib/api";
import type { Clip, SocialCopy } from "../lib/types";
import {
  BREAKDOWN_LABELS,
  FORMATS,
  humanDuration,
  scoreRing,
  scoreTone,
  scoreVerdict,
  skipReasonText,
  type FormatInfo,
} from "../lib/format";
import { useCountUp } from "../hooks/useCountUp";
import { ClipPlayer } from "./ClipPlayer";
import { SubtitleStudio, type SubtitleConfig } from "./SubtitleStudio";
import {
  Button,
  Callout,
  Card,
  CopyButton,
  Disclosure,
  LinkButton,
  Tabs,
  cx,
} from "./ui";

/**
 * A tela de um corte. A ordem responde à pergunta "posso publicar isso?":
 * primeiro assistir, depois os textos prontos para colar, depois baixar — e só
 * então o porquê da nota, para quem quiser auditar.
 */
export function ClipDetail({
  jobId,
  clip,
  onBack,
  onRated,
  onSubtitlesChanged,
}: {
  jobId: string;
  clip: Clip;
  onBack: () => void;
  onRated: (slug: string, verdict: "good" | "bad", note: string) => void;
  onSubtitlesChanged: (slug: string, subtitles: NonNullable<Clip["subtitles"]>) => void;
}) {
  const available = useMemo(
    () => FORMATS.filter((format) => Boolean(clip.artifacts[format.file as never])),
    [clip.artifacts],
  );
  const [active, setActive] = useState<FormatInfo | null>(available[0] ?? null);
  const current = active && available.includes(active) ? active : (available[0] ?? null);
  const [rating, setRating] = useState(clip.rating);
  const [savingStyle, setSavingStyle] = useState(false);
  const shownScore = useCountUp(clip.score);

  // Esc volta para a grade: a triagem é ida e volta, e alcançar o botão
  // "Voltar" com o mouse a cada corte quebra o ritmo.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (event.key === "Escape") onBack();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onBack]);

  const subtitles: SubtitleConfig = {
    style: clip.subtitles?.style ?? "viral",
    positionV: clip.subtitles?.position_v ?? 0.2,
    fontSize: clip.subtitles?.font_size ?? 1,
    textColor: clip.subtitles?.color ?? "#FFDE00",
    outlineColor: clip.subtitles?.outline_color ?? "#000000",
    uppercase: clip.subtitles?.uppercase ?? true,
    highlight: clip.subtitles?.highlight ?? "pop",
    highlightColor: clip.subtitles?.highlight_color ?? "#FFFFFF",
  };

  const rate = async (verdict: "good" | "bad") => {
    setRating(verdict);
    try {
      await api.rate(jobId, clip.slug, verdict);
      onRated(clip.slug, verdict, "");
    } catch {
      setRating(clip.rating);
    }
  };

  const saveSubtitles = async (next: SubtitleConfig) => {
    setSavingStyle(true);
    const payload = {
      style: next.style,
      position_v: next.positionV,
      font_size: next.fontSize,
      color: next.textColor,
      outline_color: next.outlineColor,
      uppercase: next.uppercase,
      highlight: next.highlight,
      highlight_color: next.highlightColor,
    };
    try {
      const saved = await api.updateSubtitles(jobId, clip.slug, payload);
      onSubtitlesChanged(clip.slug, saved.subtitles);
    } catch {
      onSubtitlesChanged(clip.slug, payload);
    } finally {
      setSavingStyle(false);
    }
  };

  const captionsFile = current?.vertical ? "captions_9x16.json" : "captions.json";
  const skipText = skipReasonText(clip.vertical_skipped);

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3 pt-2">
        <Button variant="ghost" size="sm" onClick={onBack} title="Esc">
          ← Voltar
        </Button>
        {clip.score != null && (
          <span
            className={cx(
              "rounded-full border px-2.5 py-0.5 text-[0.8rem] font-semibold",
              scoreRing(clip.score),
              scoreTone(clip.score),
            )}
          >
            <span className="tabular-nums">{shownScore ?? clip.score}</span> / 100
          </span>
        )}
        <span className={cx("truncate text-[0.8rem]", scoreTone(clip.score))}>
          {scoreVerdict(clip.score)}
        </span>
      </div>

      <h1 className="text-xl leading-snug font-semibold text-white">
        {clip.youtube?.shorts_title || clip.title || clip.slug.replace(/-/g, " ")}
      </h1>

      {skipText && (
        <Callout tone="warn" title="Este momento não virou vídeo vertical">
          <p>{skipText}</p>
        </Callout>
      )}

      {clip.copy_source === "fallback" && (
        <Callout tone="warn" title="Os textos abaixo são automáticos, não foram escritos pela IA">
          <p>
            O modelo de textos não respondeu para este corte. Os títulos e hashtags são um
            preenchimento genérico — vale reescrever antes de publicar, ou trocar o modelo em
            Configurações e rodar de novo.
          </p>
        </Callout>
      )}

      {current ? (
        <Card className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Tabs
              value={current.key}
              onChange={(key) => setActive(FORMATS.find((f) => f.key === key) ?? null)}
              options={FORMATS.map((format) => ({
                value: format.key,
                label: format.name,
                disabled: !available.includes(format),
              }))}
            />
            <span className="text-[0.72rem] text-mist-400">{current.where}</span>
          </div>

          <ClipPlayer
            key={current.file}
            src={artifactUrl(jobId, clip.slug, current.file)}
            // Cada orientação tem o seu quadro: usar o pôster 16:9 no player
            // vertical deixava a cena encaixotada entre tarjas pretas, e não
            // usar nenhum deixava um retângulo preto enquanto o vídeo carrega.
            poster={posterUrl(jobId, clip.slug, current.vertical ? "vertical" : "horizontal")}
            vertical={current.vertical}
            captionsUrl={
              clip.artifacts[captionsFile as never]
                ? artifactUrl(jobId, clip.slug, captionsFile)
                : undefined
            }
            captionStyle={clip.subtitles}
          />

          <div className="flex flex-wrap items-center gap-2 border-t border-white/8 pt-3">
            <LinkButton
              size="sm"
              variant="primary"
              href={artifactUrl(jobId, clip.slug, current.file, true)}
              download
            >
              Baixar este vídeo
            </LinkButton>
            {clip.artifacts["captions.srt" as never] && (
              <LinkButton
                size="sm"
                href={artifactUrl(
                  jobId,
                  clip.slug,
                  current.vertical ? "captions_9x16.srt" : "captions.srt",
                  true,
                )}
                download
              >
                Legenda .srt
              </LinkButton>
            )}
            <span className="ml-auto flex items-center gap-1.5">
              <span className="text-[0.72rem] text-mist-400">Este corte ficou bom?</span>
              <Button
                size="sm"
                variant={rating === "good" ? "primary" : "outline"}
                onClick={() => void rate("good")}
                aria-pressed={rating === "good"}
              >
                Sim
              </Button>
              <Button
                size="sm"
                variant={rating === "bad" ? "danger" : "outline"}
                onClick={() => void rate("bad")}
                aria-pressed={rating === "bad"}
              >
                Não
              </Button>
            </span>
          </div>
          <p className="text-[0.7rem] text-mist-400">
            A resposta ensina a ferramenta o seu gosto e influencia os próximos vídeos.
          </p>
        </Card>
      ) : (
        <Card>
          <p className="text-[0.85rem] text-mist-400">Este corte ainda não tem vídeo pronto.</p>
        </Card>
      )}

      <section className="space-y-3">
        <h2 className="text-[0.9rem] font-semibold text-mist-200">Pronto para colar</h2>
        <CopyBlocks clip={clip} />
      </section>

      <Disclosure summary="Mudar o estilo da legenda" hint="Vale para os próximos cortes deste vídeo">
        <SubtitleStudio config={subtitles} onChange={(next) => void saveSubtitles(next)} />
        <p className="text-[0.72rem] text-mist-400">
          {savingStyle
            ? "Salvando…"
            : "O estilo fica guardado neste corte. Os vídeos já montados mantêm a legenda antiga; rode o vídeo de novo para queimar a nova."}
        </p>
      </Disclosure>

      <Disclosure summary="Por que essa nota" hint="Como a ferramenta avaliou este momento">
        <div className="grid gap-3 sm:grid-cols-2">
          {Object.entries(BREAKDOWN_LABELS).map(([key, meta]) => {
            const value = clip.breakdown[key] ?? 0;
            return (
              <div key={key} className="space-y-1">
                <div className="flex items-baseline justify-between">
                  <span className="text-[0.8rem] font-medium text-mist-200">{meta.name}</span>
                  <span className="font-mono text-[0.75rem] text-mist-400">
                    {Math.round(value)}/25
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-white/8">
                  <div
                    className="h-full rounded-full bg-brand-500/80"
                    style={{ width: `${Math.max(2, Math.min(100, (value / 25) * 100))}%` }}
                  />
                </div>
                <p className="text-[0.7rem] text-mist-400">{meta.help}</p>
              </div>
            );
          })}
        </div>
        {clip.reason && (
          <p className="rounded-xl border border-white/8 bg-white/3 p-3 text-[0.8rem] leading-relaxed text-mist-300">
            {clip.reason}
          </p>
        )}
        <dl className="grid gap-2 text-[0.75rem] sm:grid-cols-2">
          {clip.windows.horizontal_16x9 && (
            <div>
              <dt className="text-mist-400">Trecho horizontal</dt>
              <dd className="text-mist-200">
                {humanDuration(clip.windows.horizontal_16x9.duration_s)} · começa em{" "}
                {humanDuration(clip.windows.horizontal_16x9.start)} do vídeo original
              </dd>
            </div>
          )}
          {clip.windows.vertical_9x16 && (
            <div>
              <dt className="text-mist-400">Trecho vertical</dt>
              <dd className="text-mist-200">
                {humanDuration(clip.windows.vertical_9x16.duration_s)}
                {clip.windows.vertical_9x16.shrunk_from_16x9 && " · recortado do horizontal"}
              </dd>
            </div>
          )}
        </dl>
      </Disclosure>
    </div>
  );
}

/** Os textos sociais, cada um com o seu botão de copiar ao lado. */
function CopyBlocks({ clip }: { clip: Clip }) {
  const yt: SocialCopy = clip.youtube ?? {};
  const tk: SocialCopy = clip.tiktok ?? {};
  const hashtags = (list?: string[]) => (list ?? []).join(" ");

  const blocks: { group: string; items: { label: string; value: string; long?: boolean }[] }[] = [
    {
      group: "YouTube Shorts",
      items: [
        { label: "Título", value: yt.shorts_title ?? "" },
        { label: "Descrição", value: yt.description ?? "", long: true },
        { label: "Hashtags", value: hashtags(yt.hashtags) },
      ],
    },
    {
      group: "YouTube (horizontal)",
      items: [
        { label: "Título", value: yt.horizontal_title || yt.long_title || "" },
        { label: "Descrição", value: yt.horizontal_description ?? "", long: true },
        { label: "Tags", value: (yt.tags ?? []).join(", ") },
      ],
    },
    {
      group: "TikTok",
      items: [
        { label: "Legenda", value: tk.caption || tk.title || "", long: true },
        { label: "Hashtags", value: hashtags(tk.hashtags) },
      ],
    },
  ];

  return (
    <div className="grid gap-3 lg:grid-cols-3">
      {blocks.map((block) => (
        <Card key={block.group} className="space-y-3 p-4">
          <h3 className="text-[0.8rem] font-semibold text-mist-200">{block.group}</h3>
          {block.items
            .filter((item) => item.value)
            .map((item) => (
              <div key={item.label} className="space-y-1">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[0.68rem] tracking-wide text-mist-400 uppercase">
                    {item.label}
                  </span>
                  <CopyButton value={item.value} />
                </div>
                <p
                  className={cx(
                    "rounded-lg border border-white/8 bg-black/25 p-2.5 text-[0.78rem] leading-relaxed break-words text-mist-200",
                    item.long && "whitespace-pre-line",
                  )}
                >
                  {item.value}
                </p>
              </div>
            ))}
          {block.items.every((item) => !item.value) && (
            <p className="text-[0.75rem] text-mist-400">Sem texto gerado para esta rede.</p>
          )}
        </Card>
      ))}
    </div>
  );
}
