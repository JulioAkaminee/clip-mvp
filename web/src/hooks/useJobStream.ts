import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "../lib/api";
import type { Clip, Estimate, Job, LogEntry, SelectionStats, Stage } from "../lib/types";

type EventPayload = Record<string, unknown>;

const EVENT_TYPES = [
  "snapshot",
  "stage",
  "log",
  "clip",
  "selection",
  "estimate",
  "source",
  "status",
  "done",
] as const;

/** Assina o SSE do job e mantém um `Job` sempre atualizado na tela. */
export function useJobStream(jobId: string | null, onFinished?: (job: Job) => void) {
  const [job, setJob] = useState<Job | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const finishedRef = useRef(onFinished);
  finishedRef.current = onFinished;

  const reload = useCallback(async () => {
    if (!jobId) return;
    try {
      setJob(await api.job(jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [jobId]);

  useEffect(() => {
    if (!jobId) {
      setJob(null);
      setConnected(false);
      return;
    }
    let disposed = false;
    setError(null);
    api
      .job(jobId)
      .then((initial) => {
        if (!disposed) setJob(initial);
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : String(err));
      });

    const source = new EventSource(eventsUrl(jobId));
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);

    const handle = (type: string) => (event: MessageEvent<string>) => {
      let parsed: { payload: EventPayload } | null = null;
      try {
        parsed = JSON.parse(event.data);
      } catch {
        return;
      }
      if (!parsed) return;
      const payload = parsed.payload;
      setJob((current) => mergeEvent(current, type, payload, jobId));
      if (type === "done") {
        const finished = payload as unknown as Job;
        finishedRef.current?.(finished);
        source.close();
        setConnected(false);
      }
    };

    const listeners = EVENT_TYPES.map((type) => {
      const listener = handle(type);
      source.addEventListener(type, listener as EventListener);
      return [type, listener] as const;
    });

    return () => {
      disposed = true;
      listeners.forEach(([type, listener]) =>
        source.removeEventListener(type, listener as EventListener),
      );
      source.close();
      setConnected(false);
    };
  }, [jobId]);

  return { job, setJob, connected, error, reload };
}

function mergeEvent(
  current: Job | null,
  type: string,
  payload: EventPayload,
  jobId: string,
): Job | null {
  if (type === "snapshot" || type === "done") {
    return payload as unknown as Job;
  }
  if (!current || current.id !== jobId) return current;

  switch (type) {
    case "stage": {
      const stage = payload as unknown as Stage;
      return {
        ...current,
        stages: current.stages.map((item) => (item.key === stage.key ? stage : item)),
      };
    }
    case "log": {
      const entry = payload as unknown as LogEntry;
      return { ...current, log: [...current.log, entry].slice(-400) };
    }
    case "clip": {
      const clip = payload as unknown as Clip;
      const index = current.clips.findIndex((item) => item.slug === clip.slug);
      const clips = [...current.clips];
      if (index >= 0) clips[index] = { ...clips[index], ...clip };
      else clips.push(clip);
      return { ...current, clips };
    }
    case "selection":
      return { ...current, selection: payload as unknown as SelectionStats };
    case "estimate":
      return { ...current, estimate: payload as unknown as Estimate };
    case "source":
      return { ...current, source: payload as Job["source"] };
    case "status": {
      const status = payload["status"] as Job["status"] | undefined;
      const errorMessage = (payload["error"] as string | null) ?? current.error;
      return { ...current, status: status ?? current.status, error: errorMessage };
    }
    default:
      return current;
  }
}
