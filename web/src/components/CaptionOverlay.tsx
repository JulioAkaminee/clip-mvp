import { useRef } from "react";
import {
  activeWordIndex,
  outlineShadow,
  type CaptionCue,
  type CaptionStyle,
} from "../lib/captions";
import { cx } from "./ui";

export function CaptionOverlay({
  cue,
  time,
  style,
  vertical = true,
  compact = false,
  editable = false,
  onPositionChange,
}: {
  cue: CaptionCue | null;
  time: number;
  style: CaptionStyle;
  vertical?: boolean;
  compact?: boolean;
  editable?: boolean;
  onPositionChange?: (positionV: number) => void;
}) {
  const boxRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);
  const highlight = style.highlight ?? "pop";
  const color = style.color ?? "#FFDE00";
  const outline = style.outline_color ?? "#000000";
  const accent = style.highlight_color ?? "#FFFFFF";
  const uppercase = style.uppercase ?? true;
  const fontScale = style.font_size ?? 1;
  const bottomPercent = Math.max(8, Math.min(82, (style.position_v ?? 0.2) * 100));
  const look = style.style ?? "viral";
  const boxed = look === "minimal";
  const activeIndex = cue ? activeWordIndex(cue, time) : -1;
  const words = cue?.words ?? [];

  const updateFromPointer = (clientY: number) => {
    const host = boxRef.current?.parentElement;
    if (!host || !onPositionChange) return;
    const rect = host.getBoundingClientRect();
    const next = Math.max(0.08, Math.min(0.85, 1 - (clientY - rect.top) / rect.height));
    onPositionChange(Math.round(next * 100) / 100);
  };

  return (
    <div
      ref={boxRef}
      className={cx(
        "absolute inset-x-3 z-20 flex justify-center",
        editable ? "cursor-ns-resize" : "pointer-events-none",
      )}
      style={{ bottom: `${bottomPercent}%` }}
      onPointerDown={(event) => {
        if (!editable) return;
        dragging.current = true;
        event.currentTarget.setPointerCapture(event.pointerId);
        updateFromPointer(event.clientY);
      }}
      onPointerMove={(event) => {
        if (!editable || !dragging.current) return;
        updateFromPointer(event.clientY);
      }}
      onPointerUp={() => {
        dragging.current = false;
      }}
    >
      {words.length > 0 && (
        <div
          className={cx(
            "max-w-[94%] text-center font-black leading-[1.15] tracking-tight",
            boxed && "rounded-xl border border-white/12 bg-black/78 px-3 py-2 backdrop-blur-md",
            look === "cyber" && "tracking-[0.04em]",
            look === "punchy" && "uppercase",
          )}
          style={{
            fontSize: `${(compact ? 0.78 : vertical ? 0.98 : 1.22) * fontScale}rem`,
            fontFamily:
              look === "punchy"
                ? "Impact, Haettenschweiler, sans-serif"
                : look === "minimal"
                  ? "Inter, ui-sans-serif, system-ui, sans-serif"
                  : "Arial Black, Arial, sans-serif",
          }}
        >
          {words.map((word, index) => {
            const spoken = index < activeIndex;
            const current = index === activeIndex;
            const upcoming = index > activeIndex;
            const display = uppercase ? word.text.toUpperCase() : word.text;
            const filled = highlight === "fill" || highlight === "karaoke";
            const popping = highlight === "pop" || highlight === "pulse" || highlight === "karaoke";
            const wordColor =
              highlight === "none"
                ? color
                : current
                  ? accent
                  : filled && spoken
                    ? accent
                    : upcoming || spoken
                      ? color
                      : color;
            return (
              <span
                key={`${word.start}-${index}`}
                className="inline-block px-[0.12em] transition-transform duration-150 ease-out"
                style={{
                  color: wordColor,
                  transform:
                    current && popping ? (highlight === "pulse" ? "scale(1.18)" : "scale(1.12)") : "scale(1)",
                  textShadow: boxed ? "none" : outlineShadow(outline, current && popping),
                  opacity: upcoming && highlight === "karaoke" ? 0.55 : 1,
                }}
              >
                {display}
              </span>
            );
          })}
        </div>
      )}
      {editable && (
        <span className="pointer-events-none absolute -bottom-6 rounded-full bg-brand-500/90 px-2 py-0.5 text-[0.6rem] font-bold tracking-wide text-white">
          ↕ {bottomPercent.toFixed(0)}%
        </span>
      )}
    </div>
  );
}
