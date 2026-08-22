import { formatMinutes, formatRelative, shortenUrl } from "../lib/format";
import type { Health, JobListItem } from "../lib/types";
import { Badge, Button, StatusDot, cx } from "./ui";

const STATUS_LABEL: Record<string, string> = {
  queued: "na fila",
  running: "rodando",
  done: "pronto",
  error: "erro",
  canceled: "cancelado",
};

export function Sidebar({
  jobs,
  selectedId,
  health,
  onSelect,
  onNew,
}: {
  jobs: JobListItem[];
  selectedId: string | null;
  health: Health | null;
  onSelect: (id: string) => void;
  onNew: () => void;
}) {
  return (
    <aside className="flex h-full min-h-0 w-full flex-col gap-4 border-white/8 lg:w-80 lg:border-r lg:pr-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight text-white">
            <span className="grid size-7 place-items-center rounded-lg bg-gradient-to-br from-brand-400 to-brand-600 text-[0.7rem] font-bold text-white">
              CM
            </span>
            clip<span className="text-mist-400">-mvp</span>
          </h1>
          <p className="mt-1 text-[0.75rem] text-mist-400">
            Cortes automáticos com contexto fechado
          </p>
        </div>
        <Button size="sm" variant="primary" onClick={onNew} title="Novo job">
          + Novo
        </Button>
      </div>

      <HealthPanel health={health} />

      <div className="flex min-h-0 flex-1 flex-col gap-2">
        <div className="flex items-center justify-between px-1">
          <h2 className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
            Jobs
          </h2>
          <span className="text-[0.72rem] text-mist-400">{jobs.length}</span>
        </div>
        <div className="-mx-1 min-h-0 flex-1 space-y-1.5 overflow-y-auto px-1 pb-2">
          {jobs.length === 0 && (
            <p className="rounded-xl border border-dashed border-white/10 px-3 py-6 text-center text-[0.78rem] text-mist-400">
              Nenhum job ainda. Cole um link para começar.
            </p>
          )}
          {jobs.map((job) => {
            const active = job.status === "running" || job.status === "queued";
            return (
              <button
                key={job.job_id}
                onClick={() => onSelect(job.job_id)}
                className={cx(
                  "w-full rounded-xl border px-3 py-2.5 text-left transition-colors",
                  selectedId === job.job_id
                    ? "border-brand-400/45 bg-brand-500/10"
                    : "border-white/8 bg-white/3 hover:border-white/20 hover:bg-white/6",
                )}
              >
                <span className="flex items-center gap-2">
                  <StatusDot status={job.status ?? "pending"} />
                  <span
                    className="min-w-0 flex-1 truncate text-[0.82rem] font-medium text-mist-200"
                    title={job.source_url || job.job_id}
                  >
                    {shortenUrl(job.source_url, 26) || job.job_id}
                  </span>
                  {active && (
                    <span className="shrink-0 font-mono text-[0.7rem] text-brand-400">
                      {Math.round(job.percent ?? 0)}%
                    </span>
                  )}
                </span>
                <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 pl-4 text-[0.7rem] text-mist-400">
                  <span>{STATUS_LABEL[job.status ?? ""] ?? "sem progresso"}</span>
                  <span aria-hidden>·</span>
                  <span>{formatRelative(job.updated_at)}</span>
                  {job.clips_total ? (
                    <>
                      <span aria-hidden>·</span>
                      <span>
                        {job.clips_done}/{job.clips_total} cortes
                      </span>
                    </>
                  ) : null}
                  {job.source_minutes ? (
                    <>
                      <span aria-hidden>·</span>
                      <span>{formatMinutes(job.source_minutes)}</span>
                    </>
                  ) : null}
                </span>
                {active && job.eta_text && (
                  <span className="mt-0.5 block pl-4 text-[0.7rem] text-brand-400">
                    {job.eta_text}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}

function HealthPanel({ health }: { health: Health | null }) {
  if (!health) {
    return (
      <div className="rounded-xl border border-white/8 bg-white/3 px-3 py-2.5 text-[0.75rem] text-mist-400">
        Verificando ambiente…
      </div>
    );
  }
  const items = [
    { label: "ffmpeg", ok: health.ffmpeg, hint: "render e legendas" },
    { label: "yt-dlp", ok: health.yt_dlp, hint: "download da fonte" },
    { label: "MediaPipe", ok: health.mediapipe, hint: "face tracking do 9:16" },
    { label: "OpenRouter", ok: health.openrouter_key, hint: "STT + LLM + vision" },
  ];
  const missing = items.filter((item) => !item.ok);
  return (
    <div className="space-y-2 rounded-xl border border-white/8 bg-white/3 p-3">
      <div className="flex items-center justify-between">
        <span className="text-[0.72rem] font-semibold uppercase tracking-[0.12em] text-mist-400">
          Ambiente
        </span>
        <Badge tone={missing.length === 0 ? "good" : "warn"}>
          {missing.length === 0 ? "pronto" : `${missing.length} pendência(s)`}
        </Badge>
      </div>
      <ul className="grid grid-cols-2 gap-1.5">
        {items.map((item) => (
          <li
            key={item.label}
            title={item.hint}
            className="flex items-center gap-1.5 text-[0.74rem] text-mist-300"
          >
            <span
              className={cx("size-1.5 rounded-full", item.ok ? "bg-lime-300" : "bg-amber-300/80")}
            />
            {item.label}
          </li>
        ))}
      </ul>
      {!health.openrouter_key && (
        <p className="text-[0.7rem] leading-snug text-mist-400">
          Preencha <code className="text-mist-300">OPENROUTER_API_KEY</code> no{" "}
          <code className="text-mist-300">.env</code>: sem chave o job para no primeiro passo de IA.
        </p>
      )}
      {!health.mediapipe && (
        <p className="text-[0.7rem] leading-snug text-mist-400">
          Sem MediaPipe o <code className="text-mist-300">vertical_facetrack</code> não é gerado.
          Instale com <code className="text-mist-300">pip install -e '.[facetrack]'</code>.
        </p>
      )}
    </div>
  );
}
