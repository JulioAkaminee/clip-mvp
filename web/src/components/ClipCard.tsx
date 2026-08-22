import { useEffect, useRef, useState } from "react";
import { artifactUrl, posterUrl } from "../lib/api";
import type { Clip } from "../lib/types";
import { FORMATS, formatDuration, scoreBorder, scoreTone, scoreWord } from "../lib/format";
import { cx } from "./ui";

/**
 * Um corte na bancada de triagem.
 *
 * A miniatura é **vertical**: o 9:16 é o que vai para o TikTok e o Shorts, e
 * julgar o corte por um quadro 16:9 é olhar para um enquadramento que não vai
 * ao ar — some justamente o que o face tracking fez.
 *
 * O card existe desde o instante em que o pipeline registra o corte, muito
 * antes de o vídeo estar pronto, então precisa ser legível esperando,
 * renderizando e pronto.
 */
export function ClipCard({
  jobId,
  clip,
  selected,
  isNew,
  onOpen,
  onFocus,
}: {
  jobId: string;
  clip: Clip;
  selected: boolean;
  isNew: boolean;
  onOpen: () => void;
  onFocus: () => void;
}) {
  const done = clip.status === "done";
  const failed = clip.status === "error";
  const duration =
    clip.windows.vertical_9x16?.duration_s ?? clip.windows.horizontal_16x9?.duration_s;
  const title = clip.youtube?.shorts_title || clip.title || clip.slug.replace(/-/g, " ");
  const rendering = FORMATS.find((format) => clip.formats[format.file] === "running");
  const preview = FORMATS.find(
    (format) => format.vertical && clip.formats[format.file] === "done",
  );

  const [scrubbing, setScrubbing] = useState(false);
  const [posterLoaded, setPosterLoaded] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  // A seleção vive no teclado, então o card precisa se trazer para a vista
  // quando é escolhido de fora — senão navegar com as setas some da tela.
  useEffect(() => {
    if (selected) buttonRef.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  /**
   * Passar o mouse avança o vídeo em vez de dar zoom no card: o movimento
   * mostra o conteúdo. Fica mudo e volta ao começo ao sair — é prévia, não
   * reprodução.
   */
  const startScrub = () => {
    if (!preview) return;
    setScrubbing(true);
  };
  const stopScrub = () => {
    setScrubbing(false);
    const el = videoRef.current;
    if (el) {
      el.pause();
      el.currentTime = 0;
    }
  };

  return (
    <button
      ref={buttonRef}
      type="button"
      onClick={onOpen}
      onFocus={onFocus}
      onMouseEnter={startScrub}
      onMouseLeave={stopScrub}
      disabled={!done}
      aria-label={
        done
          ? `Abrir o corte "${title}"${clip.score != null ? `, nota ${clip.score} de 100` : ""}`
          : `${title} — ainda sendo gerado`
      }
      className={cx(
        "group relative block w-full overflow-hidden rounded-xl bg-ink-950 text-left",
        "ring-1 transition-[box-shadow,--tw-ring-color] duration-200",
        isNew && "clip-in",
        done ? "cursor-pointer" : "cursor-default",
        selected
          ? "ring-2 ring-brand-400"
          : "ring-white/10 hover:ring-white/25",
      )}
    >
      <div className="relative aspect-[9/16] w-full overflow-hidden">
        {done ? (
          <>
            {/* A miniatura pode estar sendo extraída ainda; sem isto o card
                fica um retângulo preto que parece defeito. */}
            {!posterLoaded && <div className="absolute inset-0 animate-pulse bg-white/5" aria-hidden />}
            <img
              src={posterUrl(jobId, clip.slug, "vertical")}
              alt=""
              loading="lazy"
              onLoad={() => setPosterLoaded(true)}
              className={cx(
                "absolute inset-0 size-full object-cover transition-opacity duration-300",
                posterLoaded && !(scrubbing && preview) ? "opacity-100" : "opacity-0",
              )}
            />
            {preview && scrubbing && (
              <video
                ref={videoRef}
                src={artifactUrl(jobId, clip.slug, preview.file)}
                muted
                loop
                autoPlay
                playsInline
                preload="none"
                aria-hidden
                className="absolute inset-0 size-full object-cover"
              />
            )}
          </>
        ) : (
          <div className="grid size-full place-items-center bg-ink-900">
            {failed ? (
              <span className="px-4 text-center text-[0.75rem] text-red-200">
                não foi possível gerar
              </span>
            ) : (
              <span className="flex flex-col items-center gap-2 px-4 text-center">
                <span
                  className="size-6 animate-spin rounded-full border-2 border-white/15 border-t-brand-400"
                  aria-hidden
                />
                <span className="text-[0.72rem] text-mist-400">
                  {rendering ? rendering.name.toLowerCase() : "na fila"}
                </span>
              </span>
            )}
          </div>
        )}

        {/* O título fica por cima de um quadro qualquer — inclusive de uma
            parede branca. A tarja precisa segurar contraste no pior caso, não
            no melhor. */}
        <div
          className="pointer-events-none absolute inset-x-0 bottom-0 h-1/2 bg-gradient-to-t from-black via-black/80 to-transparent"
          aria-hidden
        />

        {clip.score != null && (
          <span
            className={cx(
              "absolute top-2.5 left-2.5 rounded-md border bg-black/80 px-1.5 py-0.5",
              "text-[0.8rem] font-semibold tabular-nums",
              scoreBorder(clip.score),
              scoreTone(clip.score),
            )}
          >
            {clip.score}
          </span>
        )}

        {clip.rating && (
          <span
            className={cx(
              "absolute top-2.5 right-2.5 grid size-6 place-items-center rounded-md text-[0.7rem] font-semibold",
              clip.rating === "good" ? "bg-lime-300 text-ink-950" : "bg-red-400 text-ink-950",
            )}
            title={clip.rating === "good" ? "marcado como bom" : "marcado como ruim"}
          >
            {clip.rating === "good" ? "✓" : "✕"}
          </span>
        )}

        <div className="absolute inset-x-0 bottom-0 space-y-1 p-3">
          <p className="line-clamp-2 text-[0.85rem] leading-snug font-medium text-white">
            {title}
          </p>
          <p className="flex items-center gap-1.5 truncate text-[0.7rem] text-white/75">
            {duration != null && (
              <span className="font-mono tabular-nums">{formatDuration(duration)}</span>
            )}
            {clip.vertical_skipped ? (
              <>
                <span aria-hidden>·</span>
                <span className="text-amber-200">só horizontal</span>
              </>
            ) : (
              clip.score != null && (
                <>
                  <span aria-hidden>·</span>
                  <span className={scoreTone(clip.score)}>{scoreWord(clip.score)}</span>
                </>
              )
            )}
          </p>
        </div>
      </div>
    </button>
  );
}
