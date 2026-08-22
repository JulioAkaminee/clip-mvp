import type { Health, JobListItem } from "../lib/types";
import { prettyUrl, timeAgo } from "../lib/format";
import { ProgressBar, StatusDot, cx } from "./ui";

const STATUS_WORD: Record<string, string> = {
  running: "processando",
  queued: "na fila",
  done: "pronto",
  error: "parou",
  canceled: "cancelado",
};

/**
 * Navegação. Um botão para começar, a lista do que já foi feito e as
 * configurações — nesta ordem, porque é a frequência com que se usa cada um.
 */
export function Sidebar({
  jobs,
  selectedId,
  screen,
  health,
  onSelect,
  onNew,
  onSettings,
}: {
  jobs: JobListItem[];
  selectedId: string | null;
  screen: string;
  health: Health | null;
  onSelect: (id: string) => void;
  onNew: () => void;
  onSettings: () => void;
}) {
  const needsSetup = health != null && !health.openrouter_key;

  return (
    <nav className="panel flex h-full w-full flex-col gap-3 p-3 lg:w-64" aria-label="Navegação">
      <div className="px-1 pt-1">
        <p className="text-[0.95rem] font-semibold text-white">clip</p>
        <p className="text-[0.7rem] text-mist-400">cortes automáticos</p>
      </div>

      <button
        type="button"
        onClick={onNew}
        className={cx(
          "w-full rounded-xl px-3 py-2.5 text-[0.85rem] font-medium transition-all",
          screen === "new"
            ? "bg-brand-500 text-white shadow-lg shadow-brand-600/25"
            : "border border-white/12 bg-white/4 text-mist-200 hover:border-white/25 hover:bg-white/8",
        )}
      >
        + Novo corte
      </button>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {jobs.length === 0 ? (
          <p className="px-1 py-4 text-[0.75rem] leading-relaxed text-mist-400">
            Seus vídeos processados aparecem aqui.
          </p>
        ) : (
          <>
            <p className="px-1 pt-2 pb-1.5 text-[0.66rem] tracking-wider text-mist-400 uppercase">
              Recentes
            </p>
            <ul className="space-y-0.5">
              {jobs.map((job) => {
                const selected = screen === "job" && job.job_id === selectedId;
                const active = job.status === "running" || job.status === "queued";
                // Enquanto o download não termina não existe título: aí a URL
                // é o único identificador que temos.
                const label = job.source_title?.trim() || prettyUrl(job.source_url) || job.job_id;
                return (
                  <li key={job.job_id}>
                    <button
                      type="button"
                      onClick={() => onSelect(job.job_id)}
                      aria-current={selected ? "page" : undefined}
                      aria-label={`${label} — ${
                        job.stale
                          ? "interrompido"
                          : active
                            ? `${Math.round(job.percent ?? 0)}% processado`
                            : (STATUS_WORD[job.status ?? ""] ?? "")
                      }`}
                      className={cx(
                        "w-full space-y-1 rounded-lg px-2.5 py-2 text-left transition-colors",
                        selected ? "bg-white/10" : "hover:bg-white/6",
                      )}
                    >
                      <span className="flex items-center gap-1.5">
                        <StatusDot status={job.stale ? "error" : (job.status ?? "pending")} />
                        <span className="min-w-0 flex-1 truncate text-[0.78rem] text-mist-200">
                          {label}
                        </span>
                      </span>
                      <span className="flex items-baseline justify-between gap-2 pl-3">
                        <span className="text-[0.68rem] text-mist-400">
                          {job.stale
                            ? "interrompido"
                            : active
                              ? `${Math.round(job.percent ?? 0)}%`
                              : `${STATUS_WORD[job.status ?? ""] ?? ""}${
                                  job.clips_done ? ` · ${job.clips_done} cortes` : ""
                                }`}
                        </span>
                        <span className="text-[0.66rem] text-mist-400">
                          {timeAgo(job.updated_at)}
                        </span>
                      </span>
                      {active && (
                        <span className="block pl-3">
                          <ProgressBar value={(job.percent ?? 0) / 100} active />
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>

      <button
        type="button"
        onClick={onSettings}
        aria-label={needsSetup ? "Configurações — falta a chave" : "Configurações"}
        className={cx(
          "flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2.5 text-[0.82rem] transition-colors",
          screen === "settings"
            ? "bg-white/10 text-mist-200"
            : "text-mist-400 hover:bg-white/6 hover:text-mist-200",
        )}
      >
        <span>Configurações</span>
        {needsSetup && (
          <span className="rounded-full bg-amber-300/20 px-1.5 py-0.5 text-[0.62rem] text-amber-200">
            falta a chave
          </span>
        )}
      </button>
    </nav>
  );
}
