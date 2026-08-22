export type JobStatus = "queued" | "running" | "done" | "error" | "canceled";
export type StageStatus = "pending" | "running" | "done" | "skipped" | "error";
export type FormatName = "vertical_facetrack" | "vertical_center" | "horizontal_16x9";
export type CaptionMode = "burn" | "sidecar" | "both";
export type Platform = "yt" | "tiktok";
export type Mode = "auto" | "more" | "count";

export interface JobOptions {
  url: string;
  mode: Mode;
  count: number | null;
  min_score: number;
  max_score_only: number | null;
  formats: FormatName[];
  captions: CaptionMode;
  platforms: Platform[];
  dry_run: boolean;
  budget_usd: number | null;
  demo?: boolean | null;
}

export interface Stage {
  key: string;
  label: string;
  status: StageStatus;
  progress: number;
  message: string;
  started_at: number | null;
  finished_at: number | null;
}

export interface LogEntry {
  t: number;
  level: string;
  message: string;
}

export interface WindowInfo {
  start: number;
  end: number;
  duration_s: number;
  context_complete?: boolean;
  boundary_method?: string;
  note?: string | null;
}

export interface ClipMeta {
  youtube?: {
    shorts_title?: string;
    long_title?: string;
    description?: string;
    tags?: string[];
    hashtags?: string[];
  };
  tiktok?: {
    caption?: string;
    hashtags?: string[];
  };
  [key: string]: unknown;
}

export interface Clip {
  slug: string;
  title: string;
  score: number;
  breakdown: Record<string, number>;
  reason: string;
  context_complete: boolean;
  boundary_method: string;
  windows: {
    horizontal_16x9?: WindowInfo | null;
    vertical_9x16?: WindowInfo | null;
  };
  vertical_skipped: string | null;
  face_track: string | null;
  artifacts: Record<string, string>;
  transcript_text: string;
  meta: ClipMeta | null;
  rating: "good" | "bad" | null;
  rating_note: string | null;
}

export interface SelectionStats {
  mode: string;
  candidates: number;
  selected: number;
  deduped: number;
  below_threshold: number;
  min_score: number;
  target_min: number;
  target_max: number;
  vertical_ok: number;
  vertical_skipped: number;
  reason: string;
}

export interface CostLine {
  step: string;
  detail: string;
  usd: number;
}

export interface Estimate {
  duration_s: number;
  candidates: number;
  selected: number;
  lines: CostLine[];
  total_usd: number;
  within_budget: boolean;
  budget_usd: number | null;
  note: string;
  source?: Record<string, unknown>;
}

export interface Job {
  id: string;
  url: string;
  status: JobStatus;
  created_at: number;
  started_at: number | null;
  finished_at: number | null;
  options: JobOptions;
  source: { title?: string; duration_s?: number; uploader?: string; thumbnail?: string };
  stages: Stage[];
  selection: SelectionStats | null;
  estimate: Estimate | null;
  clips: Clip[];
  error: string | null;
  log: LogEntry[];
  resumed_from: string | null;
}

export interface Health {
  ok: boolean;
  version: string;
  ffmpeg: boolean;
  ffprobe: boolean;
  yt_dlp: boolean;
  mediapipe: boolean;
  openrouter_key: boolean;
  demo_mode: boolean;
  models: Record<string, string>;
  work_dir: string;
  out_dir: string;
}

export interface AppConfig {
  formats: FormatName[];
  platforms: Platform[];
  caption_modes: CaptionMode[];
  default_min_score: number;
  vertical_max_s: number;
  pad_ms: [number, number];
  safe_area_bottom: number;
  target_ranges: { from_min: number; to_min: number | null; min_clips: number; max_clips: number }[];
}

export interface JobRequest {
  url: string;
  mode: Mode;
  count?: number | null;
  min_score: number;
  max_score_only?: number | null;
  formats: FormatName[];
  captions: CaptionMode;
  platforms: Platform[];
  dry_run: boolean;
  budget_usd?: number | null;
}
