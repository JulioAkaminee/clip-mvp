export function formatDuration(seconds: number | undefined | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatMinutes(minutes: number | undefined | null): string {
  if (!minutes) return "—";
  return formatDuration(minutes * 60);
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null) return "—";
  return `US$ ${value < 0.01 ? value.toFixed(4) : value.toFixed(2)}`;
}

export function formatRelative(timestamp: number | null | undefined): string {
  if (!timestamp) return "—";
  const diff = Date.now() / 1000 - timestamp;
  if (diff < 60) return "agora";
  if (diff < 3600) return `${Math.floor(diff / 60)} min atrás`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h atrás`;
  return new Date(timestamp * 1000).toLocaleDateString("pt-BR");
}

export function formatTime(timestamp: number | null | undefined): string {
  if (!timestamp) return "";
  return new Date(timestamp * 1000).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatElapsed(seconds: number | null | undefined): string {
  if (seconds == null) return "";
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes}m${String(rest).padStart(2, "0")}s`;
}

/** Nome amigável dos arquivos exportados por corte. */
export const ARTIFACT_LABELS: Record<string, string> = {
  "vertical_facetrack.mp4": "9:16 face tracking",
  "vertical_center.mp4": "9:16 center",
  "horizontal_16x9.mp4": "16:9",
  "captions.srt": "legendas .srt (16:9)",
  "captions_9x16.srt": "legendas .srt (9:16)",
  "captions_16x9.ass": "burn-in .ass (16:9)",
  "captions_9x16.ass": "burn-in .ass (9:16)",
  "meta.json": "meta.json",
  "poster.jpg": "thumbnail",
};

/** Chaves de formato usadas no progresso por clipe (`clips[].formats`). */
export const RENDER_FORMAT_LABELS: Record<string, string> = {
  vertical_facetrack: "9:16 face",
  vertical_center: "9:16 center",
  horizontal_16x9: "16:9",
};

export const VIDEO_ARTIFACTS = [
  "vertical_facetrack.mp4",
  "vertical_center.mp4",
  "horizontal_16x9.mp4",
] as const;

export const FORMAT_OPTION_LABELS: Record<string, string> = {
  face: "9:16 face tracking",
  "9x16": "9:16 center",
  "16x9": "16:9",
};

export const CAPTION_LABELS: Record<string, string> = {
  burn: "burn-in",
  sidecar: "sidecar (.srt)",
  both: "burn-in + sidecar",
};

export const STAGE_HINTS: Record<string, string> = {
  download: "yt-dlp em 720p + extração do áudio",
  transcribe: "Whisper via OpenRouter, com timestamps por palavra",
  candidates: "a IA escolhe quais e quantos momentos fecham contexto",
  score: "score 0–100 com texto + 3 frames (vision)",
  select: "dedupe, limiar de score e teto da faixa",
  captions: "SRT + ASS com safe area do 9:16",
  render: "ffmpeg: crops, loudnorm e burn-in",
  meta: "títulos, descrições e hashtags YT + TikTok",
};

export const SKIP_REASONS: Record<string, string> = {
  context_exceeds_90s:
    "O contexto fechado desse momento passa de 90s e não existe sub-janela de frase que caiba no teto, então o 9:16 foi descartado em vez de cortar a fala no meio. Só o 16:9 foi exportado.",
};

export function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-mist-400";
  if (score >= 85) return "text-lime-300";
  if (score >= 70) return "text-brand-400";
  if (score >= 60) return "text-amber-300";
  return "text-mist-400";
}

export function scoreRing(score: number | null | undefined): string {
  if (score == null) return "border-white/15 bg-white/5";
  if (score >= 85) return "border-lime-300/60 bg-lime-300/10";
  if (score >= 70) return "border-brand-400/60 bg-brand-400/10";
  if (score >= 60) return "border-amber-300/50 bg-amber-300/10";
  return "border-white/15 bg-white/5";
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return Promise.reject(new Error("clipboard indisponível"));
}

/** Encurta uma URL longa para caber no card sem virar sopa de caracteres. */
export function shortenUrl(url: string | undefined, max = 46): string {
  if (!url) return "";
  const trimmed = url.replace(/^https?:\/\/(www\.)?/, "");
  return trimmed.length <= max ? trimmed : `${trimmed.slice(0, max - 1)}…`;
}
