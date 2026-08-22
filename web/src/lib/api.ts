import type { AppConfig, Estimate, Health, Job, JobRequest } from "./types";

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
  jobs: () => request<{ jobs: Job[]; running: string | null; queued: string[] }>("/jobs"),
  job: (id: string) => request<Job>(`/jobs/${id}`),
  createJob: (payload: JobRequest) =>
    request<Job>("/jobs", { method: "POST", body: JSON.stringify(payload) }),
  estimate: (payload: JobRequest) =>
    request<Estimate>("/estimate", {
      method: "POST",
      body: JSON.stringify({ ...payload, dry_run: true }),
    }),
  cancel: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),
  resume: (id: string, payload: { mode: "more" | "count" | "auto"; count?: number | null }) =>
    request<Job>(`/jobs/${id}/resume`, { method: "POST", body: JSON.stringify(payload) }),
  remove: (id: string, files = false) =>
    request<{ deleted: string }>(`/jobs/${id}?files=${files}`, { method: "DELETE" }),
  rate: (id: string, slug: string, verdict: "good" | "bad", note = "") =>
    request<Record<string, unknown>>(`/jobs/${id}/clips/${slug}/rate`, {
      method: "POST",
      body: JSON.stringify({ verdict, note }),
    }),
};

export function artifactUrl(jobId: string, slug: string, name: string, download = false): string {
  const suffix = download ? "?download=true" : "";
  return `${BASE}/jobs/${jobId}/clips/${slug}/files/${encodeURIComponent(name)}${suffix}`;
}

export function eventsUrl(jobId: string): string {
  return `${BASE}/jobs/${jobId}/events`;
}
