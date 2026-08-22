export function formatDuration(seconds: number | undefined | null): string {
  if (seconds == null || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function formatClock(seconds: number | undefined | null): string {
  if (seconds == null) return "—";
  return formatDuration(seconds);
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

export const FORMAT_LABELS: Record<string, string> = {
  vertical_facetrack: "9:16 face tracking",
  vertical_center: "9:16 center",
  horizontal_16x9: "16:9",
};

export const FORMAT_SHORT: Record<string, string> = {
  vertical_facetrack: "9:16 face",
  vertical_center: "9:16 center",
  horizontal_16x9: "16:9",
};

export const CAPTION_LABELS: Record<string, string> = {
  burn: "burn-in",
  sidecar: "sidecar (.srt)",
  both: "burn-in + sidecar",
};

export const STAGE_HINTS: Record<string, string> = {
  download: "Baixa a fonte em 720p com yt-dlp",
  transcribe: "Whisper via OpenRouter, com timestamps por palavra",
  candidates: "A IA escolhe quais e quantos momentos viram corte",
  score: "Score 0–100 com texto + 3 frames (vision)",
  select: "Dedupe, limiar de score e teto da faixa",
  render: "ffmpeg: crops, loudnorm e legendas",
  meta: "Títulos, descrições e hashtags YT + TikTok",
};

export function scoreTone(score: number): string {
  if (score >= 85) return "text-lime-300";
  if (score >= 70) return "text-brand-400";
  if (score >= 60) return "text-amber-300";
  return "text-mist-400";
}

export function scoreRing(score: number): string {
  if (score >= 85) return "border-lime-300/60 bg-lime-300/10";
  if (score >= 70) return "border-brand-400/60 bg-brand-400/10";
  if (score >= 60) return "border-amber-300/50 bg-amber-300/10";
  return "border-white/15 bg-white/5";
}

export function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) return navigator.clipboard.writeText(text);
  return Promise.reject(new Error("clipboard indisponível"));
}
