import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, eventsUrl } from "../lib/api";
import type { Clip, JobProgress, LogLine } from "../lib/types";

const TERMINAL = new Set(["done", "error", "canceled"]);
const POLL_MS = 2000;
const CLIPS_POLL_MS = 4000;

/**
 * Acompanha um job pelo SSE do backend e cai para polling se o stream morrer —
 * a tela nunca fica congelada no último frame.
 *
 * Também busca `GET /api/jobs/{id}/clips` conforme os cortes vão saindo, para
 * juntar o progresso por clipe com `meta.json` (títulos, hashtags, janelas).
 */
export function useJobProgress(jobId: string | null, onTerminal?: () => void) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const [details, setDetails] = useState<Clip[]>([]);
  const [log, setLog] = useState<LogLine[]>([]);
  const [live, setLive] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const lastMessage = useRef<string>("");
  const terminalNotified = useRef(false);
  const onTerminalRef = useRef(onTerminal);
  onTerminalRef.current = onTerminal;

  const pushLog = useCallback((payload: JobProgress) => {
    const message = payload.message?.trim();
    if (!message || message === lastMessage.current) return;
    lastMessage.current = message;
    setLog((current) =>
      [...current, { t: payload.updated_at, stage: payload.stage, message }].slice(-300),
    );
  }, []);

  const loadClips = useCallback(async (id: string) => {
    try {
      const data = await api.clips(id);
      setDetails(data.clips);
    } catch {
      /* durante o job o job.json pode ainda não existir */
    }
  }, []);

  const reload = useCallback(async () => {
    if (!jobId) return;
    try {
      const payload = await api.job(jobId);
      setProgress(payload);
      pushLog(payload);
      await loadClips(jobId);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, [jobId, loadClips, pushLog]);

  // Reset ao trocar de job.
  useEffect(() => {
    setProgress(null);
    setDetails([]);
    setLog([]);
    setError(null);
    lastMessage.current = "";
    terminalNotified.current = false;
  }, [jobId]);

  // SSE + fallback de polling.
  useEffect(() => {
    if (!jobId) return;
    let disposed = false;
    let poll: number | undefined;
    let source: EventSource | undefined;

    const handle = (payload: JobProgress) => {
      if (disposed) return;
      setProgress(payload);
      pushLog(payload);
      if (TERMINAL.has(payload.status) && !terminalNotified.current) {
        terminalNotified.current = true;
        void loadClips(jobId);
        onTerminalRef.current?.();
      }
    };

    const startPolling = () => {
      if (poll !== undefined) return;
      poll = window.setInterval(async () => {
        try {
          const payload = await api.job(jobId);
          handle(payload);
          if (TERMINAL.has(payload.status)) {
            window.clearInterval(poll);
            poll = undefined;
          }
        } catch {
          /* o job pode ter sido removido; a próxima tentativa resolve */
        }
      }, POLL_MS);
    };

    void (async () => {
      try {
        // O histórico persistido em events.jsonl entra primeiro: abrir um job
        // já terminado mostra o caminho todo, não só o último frame.
        const history = await api.history(jobId).catch(() => ({ events: [] }));
        if (!disposed && history.events.length > 0) {
          setLog(history.events.slice(-300));
          lastMessage.current = history.events[history.events.length - 1]?.message ?? "";
        }
        const initial = await api.job(jobId);
        handle(initial);
        await loadClips(jobId);
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : String(err));
        return;
      }

      if (disposed) return;
      source = new EventSource(eventsUrl(jobId));
      source.onopen = () => setLive(true);
      source.onmessage = (event: MessageEvent<string>) => {
        try {
          handle(JSON.parse(event.data) as JobProgress);
        } catch {
          /* frame incompleto */
        }
      };
      source.onerror = () => {
        setLive(false);
        source?.close();
        startPolling();
      };
    })();

    return () => {
      disposed = true;
      setLive(false);
      source?.close();
      if (poll !== undefined) window.clearInterval(poll);
    };
  }, [jobId, loadClips, pushLog]);

  // Enquanto renderiza, os cortes aparecem um a um: revalida o meta.json.
  useEffect(() => {
    if (!jobId || !progress) return;
    if (TERMINAL.has(progress.status)) return;
    const timer = window.setInterval(() => void loadClips(jobId), CLIPS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [jobId, progress, loadClips]);

  const applyRating = useCallback(
    (slug: string, verdict: "good" | "bad", note: string) => {
      setDetails((current) =>
        current.map((clip) =>
          clip.slug === slug ? { ...clip, rating: verdict, rating_note: note } : clip,
        ),
      );
    },
    [],
  );

  const applySubtitles = useCallback((slug: string, subtitles: NonNullable<Clip["subtitles"]>) => {
    setDetails((current) =>
      current.map((clip) => (clip.slug === slug ? { ...clip, subtitles } : clip)),
    );
  }, []);

  // O card aparece no instante em que o pipeline registra o corte (via SSE) e
  // vai ganhando meta.json/artefatos conforme o job avança — em vez de só
  // surgir no fim, quando a listagem em disco fica pronta.
  const clips = useMemo(
    () => mergeClips(progress?.clips ?? [], details),
    [progress?.clips, details],
  );

  return { progress, clips, log, live, error, reload, applyRating, applySubtitles };
}

const EMPTY_CLIP: Omit<Clip, "slug" | "score" | "status" | "formats" | "vertical_skipped"> = {
  title: "",
  reason: "",
  context_complete: null,
  windows: {},
  breakdown: {},
  speaker_matching: {},
  boundaries: {},
  youtube: {},
  tiktok: {},
  artifacts: {},
  rating: null,
  rating_note: null,
};

function mergeClips(live: JobProgress["clips"], details: Clip[]): Clip[] {
  const bySlug = new Map(details.map((clip) => [clip.slug, clip]));
  const merged: Clip[] = live.map((item) => {
    const detail = bySlug.get(item.slug);
    bySlug.delete(item.slug);
    return {
      ...EMPTY_CLIP,
      ...detail,
      slug: item.slug,
      // O progresso ao vivo manda no status e no render por formato.
      status: item.status,
      formats: item.formats,
      score: item.score ?? detail?.score ?? null,
      vertical_skipped: item.vertical_skipped ?? detail?.vertical_skipped ?? null,
      message: item.message || detail?.message || "",
      title: detail?.title || item.slug.replace(/-/g, " "),
    };
  });
  // Cortes que só existem em disco (job de outra execução) continuam na lista.
  return [...merged, ...bySlug.values()];
}
