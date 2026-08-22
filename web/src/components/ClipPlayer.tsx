import { useEffect, useRef, useState } from "react";
import {
  cueAt,
  parseCaptionsJson,
  parseSrt,
  type CaptionCue,
  type CaptionStyle,
} from "../lib/captions";
import { formatDuration } from "../lib/format";
import { CaptionOverlay } from "./CaptionOverlay";
import { cx } from "./ui";

export function ClipPlayer({
  src,
  poster,
  vertical,
  captionsUrl,
  captionStyle,
  editableCaptions = false,
  onCaptionStyleChange,
}: {
  src: string;
  poster?: string;
  vertical?: boolean;
  captionsUrl?: string;
  captionStyle?: CaptionStyle;
  editableCaptions?: boolean;
  onCaptionStyleChange?: (next: CaptionStyle) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [paused, setPaused] = useState(false);
  const [started, setStarted] = useState(false);
  const [duration, setDuration] = useState(0);
  const [current, setCurrent] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const [cues, setCues] = useState<CaptionCue[]>([]);

  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    setPaused(false);
    setStarted(false);
    setCurrent(0);
    void el.play().catch(() => setPaused(true));
  }, [src]);

  useEffect(() => {
    if (!captionsUrl) {
      setCues([]);
      return;
    }
    let cancelled = false;
    void fetch(captionsUrl)
      .then(async (response) => {
        if (!response.ok) return [];
        if (captionsUrl.endsWith(".json")) {
          return parseCaptionsJson(await response.json());
        }
        return parseSrt(await response.text());
      })
      .then((next) => {
        if (!cancelled) setCues(next);
      })
      .catch(() => {
        if (!cancelled) setCues([]);
      });
    return () => {
      cancelled = true;
    };
  }, [captionsUrl]);

  const toggle = () => {
    const el = videoRef.current;
    if (!el) return;
    if (el.paused) {
      void el.play().then(() => setPaused(false)).catch(() => setPaused(true));
    } else {
      el.pause();
      setPaused(true);
    }
  };

  const seekTo = (value: number) => {
    const el = videoRef.current;
    if (!el || !Number.isFinite(value)) return;
    el.currentTime = value;
    setCurrent(value);
  };

  const style: CaptionStyle = {
    style: "viral",
    position_v: 0.2,
    font_size: 1,
    color: "#FFDE00",
    outline_color: "#000000",
    uppercase: true,
    highlight: "pop",
    highlight_color: "#FFFFFF",
    ...captionStyle,
  };
  const active = cueAt(cues, current);

  return (
    <div
      className="space-y-2"
      onClick={(event) => event.stopPropagation()}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div
        className={cx(
          "relative mx-auto overflow-hidden rounded-2xl border border-white/10 bg-black",
          vertical ? "max-w-[19rem]" : "w-full",
        )}
      >
        <video
          ref={videoRef}
          src={src}
          poster={poster}
          playsInline
          autoPlay
          preload="auto"
          className={cx("w-full bg-black", vertical ? "aspect-[9/16]" : "aspect-video")}
          onClick={toggle}
          onPlay={() => {
            setPaused(false);
            setStarted(true);
          }}
          onPause={() => setPaused(true)}
          onTimeUpdate={(event) => {
            if (!seeking) setCurrent(event.currentTarget.currentTime);
          }}
          onDurationChange={(event) => setDuration(event.currentTarget.duration || 0)}
          onLoadedMetadata={(event) => {
            setDuration(event.currentTarget.duration || 0);
            void event.currentTarget.play().catch(() => setPaused(true));
          }}
        />
        <CaptionOverlay
          cue={active}
          time={current}
          vertical={vertical}
          editable={editableCaptions}
          style={style}
          onPositionChange={(position_v) => onCaptionStyleChange?.({ ...style, position_v })}
        />
        {(paused || !started) && (
          <button
            type="button"
            onClick={toggle}
            className="absolute inset-0 z-10 grid place-items-center bg-black/25 text-white"
            aria-label="Reproduzir"
          >
            <span className="grid size-14 place-items-center rounded-full bg-brand-500/95 text-xl shadow-lg shadow-black/40">
              ▶
            </span>
          </button>
        )}
      </div>

      <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-ink-950/80 px-3 py-2">
        <button
          type="button"
          onClick={toggle}
          className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/8 text-sm text-white hover:bg-white/15"
          aria-label={paused ? "Reproduzir" : "Pausar"}
        >
          {paused ? "▶" : "❚❚"}
        </button>
        <span className="w-10 shrink-0 font-mono text-[0.7rem] text-mist-300">
          {formatDuration(current)}
        </span>
        <input
          type="range"
          min={0}
          max={Math.max(duration, 0.1)}
          step={0.05}
          value={Math.min(current, duration || 0)}
          onPointerDown={() => setSeeking(true)}
          onPointerUp={(event) => {
            setSeeking(false);
            seekTo(Number(event.currentTarget.value));
          }}
          onChange={(event) => {
            const next = Number(event.target.value);
            setCurrent(next);
            if (seeking) seekTo(next);
          }}
          className="h-1.5 flex-1 cursor-pointer appearance-none rounded-full bg-white/15 accent-brand-500"
          aria-label="Posição do vídeo"
        />
        <span className="w-10 shrink-0 text-right font-mono text-[0.7rem] text-mist-300">
          {formatDuration(duration)}
        </span>
      </div>
    </div>
  );
}
