import type {
  AppConfig,
  AppSettings,
  ArtifactName,
  Clip,
  ConnectionTestResult,
  Health,
  JobListItem,
  JobProgress,
  JobRequest,
  LogLine,
  ModelRoleKey,
  ModelsCatalog,
  SettingsUpdate,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail) && body.detail[0]?.msg) detail = body.detail[0].msg;
    } catch {
      /* resposta sem JSON */
    }
    throw new ApiError(detail, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  health: () => request<Health>("/health"),
  config: () => request<AppConfig>("/config"),
  jobs: () => request<{ jobs: JobListItem[] }>("/jobs"),
  job: (id: string) => request<JobProgress>(`/jobs/${id}`),
  clips: (id: string) => request<{ clips: Clip[] }>(`/jobs/${id}/clips`),
  history: (id: string) => request<{ events: LogLine[] }>(`/jobs/${id}/history`),
  probeVideo: (url: string) =>
    request<import("./types").VideoProbeResult>("/preview/probe", {
      method: "POST",
      body: JSON.stringify({ url }),
    }),
  createJob: (payload: JobRequest) =>
    request<{ job_id: string; already_running: boolean }>("/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  cancel: (id: string) => request<{ canceled: boolean }>(`/jobs/${id}/cancel`, { method: "POST" }),
  retry: (id: string, payload?: Partial<JobRequest>) =>
    request<{ retried: boolean }>(`/jobs/${id}/retry`, {
      method: "POST",
      body: JSON.stringify({ url: "", ...payload }),
    }),
  rate: (id: string, slug: string, verdict: "good" | "bad", note = "") =>
    request<Record<string, unknown>>(`/jobs/${id}/clips/${slug}/rate`, {
      method: "POST",
      body: JSON.stringify({ verdict, note }),
    }),
  updateSubtitles: (
    id: string,
    slug: string,
    payload: NonNullable<Clip["subtitles"]>,
  ) =>
    request<{ ok: boolean; subtitles: NonNullable<Clip["subtitles"]> }>(
      `/jobs/${id}/clips/${slug}/subtitles`,
      {
        method: "PATCH",
        body: JSON.stringify(payload),
      },
    ),
  settings: () => request<AppSettings>("/settings"),
  updateSettings: (payload: SettingsUpdate) =>
    request<AppSettings>("/settings", {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  testConnection: (apiKey?: string) =>
    request<ConnectionTestResult>("/settings/test", {
      method: "POST",
      body: JSON.stringify(apiKey ? { api_key: apiKey } : {}),
    }),
  models: (params?: { role?: ModelRoleKey; q?: string; refresh?: boolean }) => {
    const query = new URLSearchParams();
    if (params?.role) query.set("role", params.role);
    if (params?.q) query.set("q", params.q);
    if (params?.refresh) query.set("refresh", "true");
    const suffix = query.size ? `?${query}` : "";
    return request<ModelsCatalog>(`/settings/models${suffix}`);
  },
};

export function artifactUrl(
  jobId: string,
  slug: string,
  name: ArtifactName | string,
  download = false,
): string {
  const suffix = download ? "?download=true" : "";
  return `${BASE}/jobs/${jobId}/clips/${encodeURIComponent(slug)}/files/${encodeURIComponent(name)}${suffix}`;
}

/**
 * Thumbnail do corte. `orientation: "vertical"` devolve o quadro do 9:16 — que
 * é o que vai para o TikTok e o Shorts, e portanto o que se julga na grade.
 */
export function posterUrl(
  jobId: string,
  slug: string,
  orientation: "horizontal" | "vertical" = "horizontal",
): string {
  const query = orientation === "vertical" ? "?orientation=vertical" : "";
  return `${BASE}/jobs/${jobId}/clips/${encodeURIComponent(slug)}/poster.jpg${query}`;
}

export function eventsUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/events`;
}

export function bundleUrl(jobId: string, bundle: "vertical" | "horizontal" | "all"): string {
  return `${BASE}/jobs/${jobId}/download/${bundle}`;
}
