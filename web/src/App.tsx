import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { AppConfig, Health, JobListItem } from "./lib/types";
import { useJobProgress } from "./hooks/useJobProgress";
import { JobView } from "./components/JobView";
import { NewJobForm } from "./components/NewJobForm";
import { SettingsPage } from "./components/SettingsPage";
import { Sidebar } from "./components/Sidebar";
import { Button, Card, Spinner } from "./components/ui";

type Screen = "new" | "settings" | "job";

const JOBS_POLL_MS = 4000;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>("new");
  const [bootError, setBootError] = useState<string | null>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const data = await api.jobs();
      setJobs(data.jobs);
      return data.jobs;
    } catch (err) {
      setBootError(err instanceof Error ? err.message : String(err));
      return [];
    }
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const [healthData, configData] = await Promise.all([api.health(), api.config()]);
        setHealth(healthData);
        setConfig(configData);
      } catch (err) {
        setBootError(err instanceof Error ? err.message : String(err));
      }
      const list = await refreshJobs();
      const active = list.find((job) => job.status === "running" || job.status === "queued");
      if (active) {
        setSelectedId(active.job_id);
        setScreen("job");
      }
    })();
  }, [refreshJobs]);

  const { progress, clips, log, live, error, applyRating, reload } = useJobProgress(
    selectedId,
    () => void refreshJobs(),
  );

  // Mantém a lista lateral (percentual e ETA de cada job) fresca.
  useEffect(() => {
    const hasActive = jobs.some((job) => job.status === "running" || job.status === "queued");
    if (!hasActive) return;
    const timer = window.setInterval(() => void refreshJobs(), JOBS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      /* a tela de Configurações já mostra o erro de salvamento */
    }
  }, []);

  const onCreated = async (jobId: string) => {
    await refreshJobs();
    setSelectedId(jobId);
    setScreen("job");
  };

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex min-h-screen max-w-[100rem] flex-col gap-6 px-4 py-5 lg:flex-row lg:px-6">
        <div className="lg:sticky lg:top-5 lg:h-[calc(100vh-2.5rem)]">
          <Sidebar
            jobs={jobs}
            selectedId={selectedId}
            screen={screen}
            health={health}
            onSelect={(id) => {
              setSelectedId(id);
              setScreen("job");
            }}
            onNew={() => {
              setSelectedId(null);
              setScreen("new");
            }}
            onSettings={() => setScreen("settings")}
          />
        </div>

        <main className="min-w-0 flex-1 pb-10">
          {bootError && (
            <Card className="mb-4 border-red-400/25 bg-red-500/8">
              <h2 className="text-sm font-semibold text-red-200">API indisponível</h2>
              <p className="mt-1 text-[0.8rem] text-red-100/80">{bootError}</p>
              <p className="mt-2 text-[0.78rem] text-mist-400">
                Suba o backend com <code className="text-mist-200">clip serve</code> e recarregue.
              </p>
              <Button
                size="sm"
                className="mt-3"
                onClick={() => {
                  setBootError(null);
                  void refreshJobs();
                }}
              >
                Tentar de novo
              </Button>
            </Card>
          )}

          {/* Um job selecionado que ainda não respondeu não é "criar job novo":
              cair no formulário aqui piscava a tela a cada troca de job e, se o
              fetch falhasse, escondia o erro atrás de um formulário em branco. */}
          {screen === "settings" ? (
            <SettingsPage
              health={health}
              onChanged={() => {
                void refreshHealth();
              }}
            />
          ) : screen === "new" || selectedId === null ? (
            <NewJobForm config={config} health={health} onCreated={onCreated} />
          ) : error !== null && progress === null ? (
            <Card className="border-red-400/25 bg-red-500/8">
              <h2 className="text-sm font-semibold text-red-200">
                Não foi possível carregar este job
              </h2>
              <p className="mt-1 text-[0.8rem] text-red-100/80">{error}</p>
              <p className="mt-2 text-[0.78rem] text-mist-400">
                O job pode ter sido removido de <code className="text-mist-200">work/</code>, ou a
                API caiu.
              </p>
              <div className="mt-3 flex gap-2">
                <Button size="sm" onClick={() => void reload()}>
                  Tentar de novo
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    setSelectedId(null);
                    setScreen("new");
                  }}
                >
                  Criar outro job
                </Button>
              </div>
            </Card>
          ) : progress === null ? (
            <Card className="flex items-center gap-3">
              <Spinner className="text-brand-400" />
              <span className="text-[0.85rem] text-mist-300">Carregando progresso do job…</span>
            </Card>
          ) : (
            <JobView
              key={progress.job_id}
              progress={progress}
              clips={clips}
              log={log}
              live={live}
              onChanged={() => {
                void reload();
                void refreshJobs();
              }}
              onRated={applyRating}
            />
          )}
        </main>
      </div>
    </div>
  );
}
