import type { HighlightMode, SubtitleStyle } from "./types";
export type { HighlightMode };

export interface CaptionWord {
  text: string;
  start: number;
  end: number;
}

export interface CaptionCue {
  start: number;
  end: number;
  text: string;
  words: CaptionWord[];
}

export interface CaptionStyle {
  style?: SubtitleStyle;
  position_v?: number;
  font_size?: number;
  color?: string;
  outline_color?: string;
  uppercase?: boolean;
  highlight?: HighlightMode;
  highlight_color?: string;
}

export function parseSrtTime(value: string): number {
  const match = value.match(/(\d+):(\d+):(\d+)[,.](\d+)/);
  if (!match) return Number.NaN;
  const [, hh, mm, ss, ms] = match;
  return (
    Number(hh) * 3600 +
    Number(mm) * 60 +
    Number(ss) +
    Number(ms.padEnd(3, "0").slice(0, 3)) / 1000
  );
}

export function estimateWords(text: string, start: number, end: number): CaptionWord[] {
  const tokens = text.split(/\s+/).filter(Boolean);
  if (tokens.length === 0) return [];
  const span = Math.max(0.05, end - start);
  const step = span / tokens.length;
  return tokens.map((token, index) => ({
    text: token,
    start: start + index * step,
    end: start + (index + 1) * step,
  }));
}

export function parseSrt(raw: string): CaptionCue[] {
  const blocks = raw.replace(/^\uFEFF/, "").split(/\r?\n\r?\n/);
  const cues: CaptionCue[] = [];
  for (const block of blocks) {
    const lines = block.split(/\r?\n/).filter((line) => line.trim().length > 0);
    if (lines.length < 2) continue;
    const stamp = lines.find((line) => line.includes("-->"));
    if (!stamp) continue;
    const [startRaw, endRaw] = stamp.split("-->").map((part) => part.trim());
    const text = lines.slice(lines.indexOf(stamp) + 1).join(" ").trim();
    const start = parseSrtTime(startRaw);
    const end = parseSrtTime(endRaw);
    if (text && Number.isFinite(start) && Number.isFinite(end)) {
      cues.push({ start, end, text, words: estimateWords(text, start, end) });
    }
  }
  return cues;
}

export function parseCaptionsJson(raw: unknown): CaptionCue[] {
  const payload = raw as { cues?: Array<Partial<CaptionCue>> } | null;
  const items = payload?.cues ?? [];
  return items
    .map((cue) => {
      const start = Number(cue.start);
      const end = Number(cue.end);
      const text = String(cue.text ?? "").trim();
      if (!text || !Number.isFinite(start) || !Number.isFinite(end)) return null;
      const words =
        Array.isArray(cue.words) && cue.words.length > 0
          ? cue.words
              .map((word) => ({
                text: String(word.text ?? "").trim(),
                start: Number(word.start),
                end: Number(word.end),
              }))
              .filter((word) => word.text && Number.isFinite(word.start) && Number.isFinite(word.end))
          : estimateWords(text, start, end);
      return { start, end, text, words };
    })
    .filter((cue): cue is CaptionCue => cue !== null);
}

export function cueAt(cues: CaptionCue[], time: number): CaptionCue | null {
  return cues.find((cue) => time >= cue.start && time < cue.end) ?? null;
}

export function activeWordIndex(cue: CaptionCue, time: number): number {
  if (cue.words.length === 0) return -1;
  const exact = cue.words.findIndex((word) => time >= word.start && time < word.end);
  if (exact >= 0) return exact;
  if (time < cue.words[0].start) return 0;
  return cue.words.length - 1;
}

export function outlineShadow(color: string, strong = false): string {
  const w = strong ? 2.4 : 1.8;
  return [
    `-${w}px -${w}px 0 ${color}`,
    `${w}px -${w}px 0 ${color}`,
    `-${w}px ${w}px 0 ${color}`,
    `${w}px ${w}px 0 ${color}`,
    "0 6px 14px rgba(0,0,0,0.55)",
  ].join(", ");
}
