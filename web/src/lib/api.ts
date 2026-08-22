import type {
  AppConfig,
  ArtifactName,
  Clip,
  Health,
  JobListItem,
  JobProgress,
  JobRequest,
  LogLine,
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

export function posterUrl(jobId: string, slug: string): string {
  return `${BASE}/jobs/${jobId}/clips/${encodeURIComponent(slug)}/poster.jpg`;
}

export function eventsUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/events`;
}
