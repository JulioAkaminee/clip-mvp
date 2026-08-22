import { useEffect, useRef, useState } from "react";
import type { HighlightMode, SubtitleStyle } from "../lib/types";
import { estimateWords, type CaptionCue } from "../lib/captions";
import { CaptionOverlay } from "./CaptionOverlay";
import { cx } from "./ui";

export interface SubtitleConfig {
  style: SubtitleStyle;
  positionV: number;
  fontSize: number;
  textColor: string;
  outlineColor: string;
  uppercase: boolean;
  highlight: HighlightMode;
  highlightColor: string;
}

interface SubtitleStudioProps {
  config: SubtitleConfig;
  onChange: (updated: SubtitleConfig) => void;
  videoThumbnail?: string | null;
}

const SAMPLE = "você não vai acreditar no resultado disso";

const PRESETS: {
  id: SubtitleStyle;
  name: string;
  badge: string;
  desc: string;
  textColor: string;
  outlineColor: string;
  uppercase: boolean;
  highlight: HighlightMode;
  highlightColor: string;
  fontSize: number;
}[] = [
  {
    id: "viral",
    name: "Viral Hormozi",
    badge: "Retenção",
    desc: "Amarelo grosso, palavra atual explode em branco.",
    textColor: "#FFDE00",
    outlineColor: "#111111",
    uppercase: true,
    highlight: "pop",
    highlightColor: "#FFFFFF",
    fontSize: 1.1,
  },
  {
    id: "minimal",
    name: "Podcast Clean",
    badge: "Elegante",
    desc: "Caixa escura, palavra atual preenche em âmbar.",
    textColor: "#F4F4F5",
    outlineColor: "#000000",
    uppercase: false,
    highlight: "fill",
    highlightColor: "#F5C518",
    fontSize: 0.95,
  },
  {
    id: "cyber",
    name: "Neon Pulse",
    badge: "Tech",
    desc: "Verde elétrico com pulso na sílaba falada.",
    textColor: "#7CFFB2",
    outlineColor: "#04210D",
    uppercase: true,
    highlight: "pulse",
    highlightColor: "#E7FFE9",
    fontSize: 1.05,
  },
  {
    id: "gradient",
    name: "Karaoke Pop",
    badge: "Feed",
    desc: "Magenta com preenchimento tipo karaokê.",
    textColor: "#FF7AD9",
    outlineColor: "#1A0010",
    uppercase: true,
    highlight: "karaoke",
    highlightColor: "#FFFFFF",
    fontSize: 1.05,
  },
  {
    id: "punchy",
    name: "Impact",
    badge: "Urgência",
    desc: "Impact branco, palavra atual sobe e acende.",
    textColor: "#FFF7F2",
    outlineColor: "#8B0000",
    uppercase: true,
    highlight: "pop",
    highlightColor: "#FFD166",
    fontSize: 1.2,
  },
];

const HIGHLIGHTS: { id: HighlightMode; name: string; hint: string }[] = [
  { id: "pop", name: "Pop", hint: "cresce e muda de cor" },
  { id: "fill", name: "Fill", hint: "pinta o que já foi falado" },
  { id: "karaoke", name: "Karaokê", hint: "preenche e destaca a atual" },
  { id: "pulse", name: "Pulse", hint: "pulsa no ritmo da fala" },
  { id: "none", name: "Estático", hint: "sem destaque por palavra" },
];

const COLORS = [
  "#FFDE00",
  "#FFFFFF",
  "#7CFFB2",
  "#00F0FF",
  "#FF7AD9",
  "#FF4D4D",
  "#FF8A00",
  "#F5C518",
];

export function SubtitleStudio({ config, onChange, videoThumbnail }: SubtitleStudioProps) {
  const [showSafeArea, setShowSafeArea] = useState(true);
  const [previewTime, setPreviewTime] = useState(0.15);
  const phoneRef = useRef<HTMLDivElement>(null);
  const dragging = useRef(false);

  const cue: CaptionCue = {
    start: 0,
    end: 2.4,
    text: SAMPLE,
    words: estimateWords(SAMPLE, 0, 2.4),
  };

  useEffect(() => {
    const timer = window.setInterval(() => {
      setPreviewTime((value) => (value + 0.12) % 2.5);
    }, 120);
    return () => window.clearInterval(timer);
  }, []);

  const applyPreset = (id: SubtitleStyle) => {
    const preset = PRESETS.find((item) => item.id === id);
    if (!preset) return;
    onChange({
      ...config,
      style: preset.id,
      textColor: preset.textColor,
      outlineColor: preset.outlineColor,
      uppercase: preset.uppercase,
      highlight: preset.highlight,
      highlightColor: preset.highlightColor,
      fontSize: preset.fontSize,
    });
  };

  const setPosition = (clientY: number) => {
    if (!phoneRef.current) return;
    const rect = phoneRef.current.getBoundingClientRect();
    const next = Math.max(0.1, Math.min(0.85, 1 - (clientY - rect.top) / rect.height));
    onChange({ ...config, positionV: Math.round(next * 100) / 100 });
  };

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-mist-300">
              Preset visual
            </p>
            <p className="text-[0.72rem] text-mist-400">
              Cada preset já traz cor, caixa e o jeito da palavra atual.
            </p>
          </div>
        </div>
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-5">
          {PRESETS.map((preset) => {
            const selected = config.style === preset.id;
            return (
              <button
                key={preset.id}
                type="button"
                onClick={() => applyPreset(preset.id)}
                className={cx(
                  "rounded-2xl border p-3 text-left transition-all",
                  selected
                    ? "border-brand-400 bg-brand-500/12 ring-1 ring-brand-400/40"
                    : "border-white/10 bg-ink-950/70 hover:border-white/20",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[0.82rem] font-semibold text-white">{preset.name}</span>
                  <span className="rounded-full bg-white/6 px-2 py-0.5 text-[0.62rem] text-mist-300">
                    {preset.badge}
                  </span>
                </div>
                <p className="mt-1 text-[0.68rem] leading-snug text-mist-400">{preset.desc}</p>
                <div className="mt-3 rounded-xl bg-black/70 px-2 py-2 text-center">
                  <span
                    className="inline-block text-[0.68rem] font-black"
                    style={{
                      color: preset.highlightColor,
                      textShadow:
                        preset.id === "minimal"
                          ? undefined
                          : `-1px -1px 0 ${preset.outlineColor}, 1px 1px 0 ${preset.outlineColor}`,
                    }}
                  >
                    {preset.uppercase ? "PALAVRA" : "palavra"}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12">
        <div className="flex flex-col items-center lg:col-span-5">
          <div className="mb-2 flex w-full max-w-[260px] items-center justify-between text-xs text-mist-400">
            <span>Preview 9:16</span>
            <button
              type="button"
              onClick={() => setShowSafeArea((value) => !value)}
              className="text-brand-400 hover:text-brand-300"
            >
              {showSafeArea ? "Ocultar safe area" : "Mostrar safe area"}
            </button>
          </div>
          <div
            ref={phoneRef}
            className="relative aspect-[9/16] w-full max-w-[260px] overflow-hidden rounded-[2.2rem] border-4 border-ink-700 bg-black shadow-2xl"
            onPointerDown={(event) => {
              dragging.current = true;
              event.currentTarget.setPointerCapture(event.pointerId);
              setPosition(event.clientY);
            }}
            onPointerMove={(event) => {
              if (dragging.current) setPosition(event.clientY);
            }}
            onPointerUp={() => {
              dragging.current = false;
            }}
          >
            {videoThumbnail ? (
              <img src={videoThumbnail} alt="" className="size-full object-cover opacity-55" />
            ) : (
              <div className="size-full bg-gradient-to-b from-ink-800 via-ink-900 to-black" />
            )}
            {showSafeArea && (
              <div className="pointer-events-none absolute inset-x-0 bottom-0 h-[20%] border-t border-dashed border-amber-300/40 bg-amber-300/10" />
            )}
            <CaptionOverlay
              cue={cue}
              time={previewTime}
              compact
              style={{
                style: config.style,
                position_v: config.positionV,
                font_size: config.fontSize,
                color: config.textColor,
                outline_color: config.outlineColor,
                uppercase: config.uppercase,
                highlight: config.highlight,
                highlight_color: config.highlightColor,
              }}
            />
          </div>
          <p className="mt-2 text-center text-[0.68rem] text-mist-400">
            Arraste no preview para mover. A palavra atual já anima como no corte.
          </p>
        </div>

        <div className="space-y-3 lg:col-span-7">
          <section className="space-y-2 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-mist-300">
                Destaque palavra a palavra
              </h4>
              <span className="text-[0.68rem] text-mist-400">
                {HIGHLIGHTS.find((item) => item.id === config.highlight)?.hint}
              </span>
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
              {HIGHLIGHTS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onChange({ ...config, highlight: item.id })}
                  className={cx(
                    "rounded-xl border px-2 py-2 text-center text-[0.72rem] font-medium",
                    config.highlight === item.id
                      ? "border-brand-400 bg-brand-500/15 text-white"
                      : "border-white/10 bg-white/4 text-mist-300 hover:bg-white/8",
                  )}
                >
                  {item.name}
                </button>
              ))}
            </div>
          </section>

          <section className="space-y-3 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
            <div className="flex items-center justify-between">
              <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-mist-300">
                Posição
              </h4>
              <span className="font-mono text-[0.72rem] text-brand-400">
                {(config.positionV * 100).toFixed(0)}%
              </span>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {[
                { label: "Embaixo", value: 0.2 },
                { label: "Meio", value: 0.5 },
                { label: "Cima", value: 0.78 },
              ].map((item) => (
                <button
                  key={item.label}
                  type="button"
                  onClick={() => onChange({ ...config, positionV: item.value })}
                  className={cx(
                    "rounded-xl border px-2 py-2 text-[0.72rem]",
                    Math.abs(config.positionV - item.value) < 0.02
                      ? "border-brand-400 bg-brand-500/15 text-white"
                      : "border-white/10 text-mist-300 hover:bg-white/6",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>
            <input
              type="range"
              min={0.1}
              max={0.85}
              step={0.01}
              value={config.positionV}
              onChange={(event) => onChange({ ...config, positionV: Number(event.target.value) })}
              className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-white/10 accent-brand-500"
            />
          </section>

          <div className="grid gap-3 sm:grid-cols-2">
            <section className="space-y-2 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-mist-300">
                Tamanho
              </h4>
              <div className="grid grid-cols-4 gap-1.5">
                {[
                  { label: "P", value: 0.8 },
                  { label: "M", value: 1 },
                  { label: "G", value: 1.2 },
                  { label: "GG", value: 1.45 },
                ].map((item) => (
                  <button
                    key={item.label}
                    type="button"
                    onClick={() => onChange({ ...config, fontSize: item.value })}
                    className={cx(
                      "rounded-lg border py-1.5 text-xs font-bold",
                      config.fontSize === item.value
                        ? "border-brand-400 bg-brand-500/15 text-brand-200"
                        : "border-white/10 text-mist-300 hover:bg-white/6",
                    )}
                  >
                    {item.label}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={() => onChange({ ...config, uppercase: !config.uppercase })}
                className={cx(
                  "w-full rounded-lg border px-3 py-1.5 text-xs",
                  config.uppercase
                    ? "border-brand-400 bg-brand-500/15 text-white"
                    : "border-white/10 text-mist-300",
                )}
              >
                {config.uppercase ? "MAIÚSCULAS ligadas" : "Caixa normal"}
              </button>
            </section>

            <section className="space-y-2 rounded-2xl border border-white/10 bg-ink-950/70 p-4">
              <h4 className="text-xs font-semibold uppercase tracking-[0.12em] text-mist-300">
                Cores
              </h4>
              <p className="text-[0.68rem] text-mist-400">Texto</p>
              <div className="flex flex-wrap gap-1.5">
                {COLORS.map((hex) => (
                  <button
                    key={`text-${hex}`}
                    type="button"
                    onClick={() => onChange({ ...config, textColor: hex })}
                    className={cx(
                      "size-6 rounded-full border",
                      config.textColor.toUpperCase() === hex
                        ? "border-white ring-2 ring-brand-400"
                        : "border-black/40",
                    )}
                    style={{ backgroundColor: hex }}
                    aria-label={`texto ${hex}`}
                  />
                ))}
              </div>
              <p className="pt-1 text-[0.68rem] text-mist-400">Palavra atual</p>
              <div className="flex flex-wrap gap-1.5">
                {COLORS.map((hex) => (
                  <button
                    key={`hi-${hex}`}
                    type="button"
                    onClick={() => onChange({ ...config, highlightColor: hex })}
                    className={cx(
                      "size-6 rounded-full border",
                      config.highlightColor.toUpperCase() === hex
                        ? "border-white ring-2 ring-brand-400"
                        : "border-black/40",
                    )}
                    style={{ backgroundColor: hex }}
                    aria-label={`destaque ${hex}`}
                  />
                ))}
              </div>
            </section>
          </div>
        </div>
      </div>
    </div>
  );
}
