/**
 * Espelho do payload de progresso do backend (`clip_mvp/progress.py`).
 * CLI, API e esta UI consomem exatamente o mesmo objeto.
 */

export type JobStatus = "queued" | "running" | "done" | "error" | "canceled";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "error";
export type ClipStatus = "pending" | "running" | "done" | "skipped" | "error";
export type FormatKey = "face" | "9x16" | "16x9";
export type CaptionMode = "burn" | "sidecar" | "both";
export type Platform = "yt" | "tiktok";
export type Mode = "auto" | "more" | "count";

/** Nomes dos arquivos de vídeo produzidos por clipe. */
export type ArtifactName =
  | "vertical_facetrack.mp4"
  | "vertical_center.mp4"
  | "horizontal_16x9.mp4"
  | "captions.srt"
  | "captions_9x16.srt"
  | "captions_16x9.ass"
  | "captions_9x16.ass"
  | "meta.json"
  | "poster.jpg";

export interface StageState {
  name: string;
  label: string;
  weight: number;
  status: StageStatus;
  percent: number;
  message: string;
  units_total: number;
  units_done: number;
  elapsed_seconds: number | null;
  predicted_seconds: number | null;
}

export interface ClipProgress {
  slug: string;
  score: number | null;
  status: ClipStatus;
  /** `{"horizontal_16x9": "done", "vertical_facetrack": "running"}` */
  formats: Record<string, string>;
  message: string;
  vertical_skipped: string | null;
}

export interface JobError {
  stage: string;
  stage_label: string;
  type: string;
  message: string;
  retriable: boolean;
  hint: string;
}

export interface CostEstimate {
  stt_minutes: number;
  stt_usd: number;
  n_candidates: number;
  text_usd: number;
  vision_usd: number;
  total_usd: number;
}

export interface JobSummary {
  job_id: string;
  candidates: number;
  selected: number;
  deduped_removed: number;
  vertical_ok: number;
  vertical_skipped: number;
  min_score: number;
  dry_run: boolean;
  cost_estimate: CostEstimate | null;
  notes: string[];
  clips: { slug: string; score: number; reason: string; out_dir: string }[];
  out_dirs: string[];
}

export interface JobProgress {
  schema_version: number;
  job_id: string;
  status: JobStatus;
  stage: string;
  stage_label: string;
  stage_percent: number;
  percent: number;
  eta_seconds: number | null;
  eta_text: string;
  message: string;
  clips_done: number;
  clips_total: number;
  clips: ClipProgress[];
  stages: StageState[];
  elapsed_seconds: number;
  updated_at: number;
  error: JobError | null;
  source_minutes: number;
  result: { summary: JobSummary } | null;
  source_url?: string;
  running?: boolean;
}

export interface JobListItem {
  job_id: string;
  source_url?: string;
  status?: JobStatus;
  percent?: number;
  stage?: string;
  stage_label?: string;
  eta_seconds?: number | null;
  eta_text?: string;
  clips_done?: number;
  clips_total?: number;
  updated_at?: number;
  source_minutes?: number;
  running?: boolean;
}

export interface WindowInfo {
  start: number;
  end: number;
  duration_s: number;
}

export interface SocialCopy {
  shorts_title?: string;
  long_title?: string;
  title?: string;
  description?: string;
  caption?: string;
  tags?: string[];
  hashtags?: string[];
}

/** Clipe já com `meta.json` e artefatos em disco (`GET /api/jobs/{id}/clips`). */
export interface Clip {
  slug: string;
  title: string;
  score: number | null;
  status: ClipStatus;
  formats: Record<string, string>;
  message?: string;
  reason: string;
  vertical_skipped: string | null;
  context_complete: boolean | null;
  windows: { horizontal_16x9?: WindowInfo; vertical_9x16?: WindowInfo };
  breakdown: Record<string, number>;
  speaker_matching: { method?: string };
  boundaries: Record<string, unknown>;
  youtube: SocialCopy;
  tiktok: SocialCopy;
  artifacts: Partial<Record<ArtifactName, string>>;
  rating: "good" | "bad" | null;
  rating_note: string | null;
  out_dir?: string;
}

export interface Health {
  ok: boolean;
  ffmpeg: boolean;
  ffprobe: boolean;
  yt_dlp: boolean;
  mediapipe: boolean;
  openrouter_key: boolean;
  ui_built: boolean;
  models: Record<string, string>;
  work_dir: string;
  out_dir: string;
}

export interface AppConfig {
  formats: FormatKey[];
  format_labels: Record<string, string>;
  platforms: Platform[];
  caption_modes: CaptionMode[];
  default_min_score: number;
  vertical_max_s: number;
  pad_ms: [number, number];
  stages: { name: string; label: string }[];
  target_ranges: {
    from_min: number;
    to_min: number | null;
    min_clips: number;
    max_clips: number;
  }[];
}

export interface JobRequest {
  url: string;
  more: boolean;
  count: number | null;
  min_score: number | null;
  max_score_only: number | null;
  formats: FormatKey[];
  captions: CaptionMode;
  platforms: Platform[];
  dry_run: boolean;
  budget: number | null;
}

export interface LogLine {
  t: number;
  stage: string;
  message: string;
}
