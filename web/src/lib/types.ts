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

export type FormatStatus = "pending" | "running" | "done" | "error";

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
  /** Cortes acima do limiar mas muito abaixo do melhor deste vídeo (SPEC §3.5). */
  below_floor_removed: number;
  quality_floor: number | null;
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
  /** Tempo no estágio atual: o único sinal de vida quando não há o que contar. */
  stage_elapsed_seconds: number | null;
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
  /** Reemissão periódica do backend (não é uma transição de estágio). */
  heartbeat?: boolean;
  error: JobError | null;
  source_minutes: number;
  result: { summary: JobSummary } | null;
  source_url?: string;
  running?: boolean;
  /** Job abandonado (processo morto / servidor reiniciado), não em execução. */
  stale?: boolean;
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
  stale?: boolean;
}

export interface WindowInfo {
  start: number;
  end: number;
  duration_s: number;
  /** Só no 9:16: a janela fecha contexto por conta própria? */
  context_complete?: boolean;
  /** Só no 9:16: encolhida a partir do 16:9 para caber no teto de 90s. */
  shrunk_from_16x9?: boolean;
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

export type KeySource = "ui" | "env";
export type ModelSource = "ui" | "env" | "inherited";
export type ModelRoleKey = "stt" | "candidates" | "score" | "meta" | "diarization";

export interface Health {
  ok: boolean;
  ffmpeg: boolean;
  ffprobe: boolean;
  yt_dlp: boolean;
  mediapipe: boolean;
  openrouter_key: boolean;
  /** Chave mascarada (`sk-or-…cdef`). Nunca o valor completo. */
  openrouter_key_masked?: string | null;
  openrouter_key_source?: KeySource | null;
  ui_built: boolean;
  models: Record<string, string>;
  work_dir: string;
  out_dir: string;
}

export interface SettingsOpenRouter {
  configured: boolean;
  masked: string | null;
  source: KeySource | null;
  base_url: string;
}

export interface ModelRoleState {
  role: ModelRoleKey;
  label: string;
  description: string;
  requires: string[];
  optional: boolean;
  inherits_from: ModelRoleKey | null;
  value: string;
  env_default: string;
  source: ModelSource;
  effective: string;
}

export interface AppSettings {
  openrouter: SettingsOpenRouter;
  models: ModelRoleState[];
  settings_file: string;
  updated_at: number | null;
}

export interface SettingsUpdate {
  api_key?: string | null;
  clear_api_key?: boolean;
  models?: Partial<Record<ModelRoleKey, string>>;
}

export interface ConnectionTestResult {
  ok: boolean;
  message: string;
  label?: string | null;
  usage_usd?: number | null;
  limit_usd?: number | null;
  limit_remaining_usd?: number | null;
  is_free_tier?: boolean | null;
  models_available?: number;
}

export interface OpenRouterModel {
  id: string;
  name: string;
  context_length: number | null;
  input_modalities: string[];
  prompt_usd_per_mtok: number | null;
  completion_usd_per_mtok: number | null;
  free: boolean;
}

export interface ModelsCatalog {
  models: OpenRouterModel[];
  total: number;
  matching: number;
  cached: boolean;
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
