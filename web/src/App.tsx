import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { AppConfig, Health, JobListItem } from "./lib/types";
import { useJobProgress } from "./hooks/useJobProgress";
import { JobView } from "./components/JobView";
import { NewJob } from "./components/NewJob";
import { Onboarding } from "./components/Onboarding";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { Button, Callout, Skeleton } from "./components/ui";

type Screen = "new" | "settings" | "job";

const JOBS_POLL_MS = 4000;

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [screen, setScreen] = useState<Screen>("new");
  const [booting, setBooting] = useState(true);
  const [bootError, setBootError] = useState<string | null>(null);
  /** Some com o onboarding depois de salvar a chave, sem esperar o /health. */
  const [setupDone, setSetupDone] = useState(false);

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

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch {
      /* a tela de Configurações já mostra o erro de salvamento */
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
      // Abrir direto no job que está rodando: quem volta para a aba quer ver
      // o andamento, não um formulário em branco.
      const active = list.find((job) => job.status === "running" || job.status === "queued");
      if (active) {
        setSelectedId(active.job_id);
        setScreen("job");
      }
      setBooting(false);
    })();
  }, [refreshJobs]);

  const { progress, clips, log, live, applyRating, applySubtitles, reload } = useJobProgress(
    selectedId,
    () => void refreshJobs(),
  );

  // Mantém percentual e ETA frescos na lista lateral enquanto algo roda.
  useEffect(() => {
    const hasActive = jobs.some((job) => job.status === "running" || job.status === "queued");
    if (!hasActive) return;
    const timer = window.setInterval(() => void refreshJobs(), JOBS_POLL_MS);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  if (booting) {
    return (
      <div className="mx-auto max-w-3xl space-y-4 px-4 py-16">
        <Skeleton className="h-8 w-52" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  // Sem chave a ferramenta não faz nada: em vez de deixar a pessoa colar um
  // link e falhar no meio do caminho, o pré-requisito vem primeiro.
  if (!setupDone && health != null && !health.openrouter_key) {
    return (
      <Onboarding
        health={health}
        onReady={() => {
          setSetupDone(true);
          void refreshHealth();
        }}
      />
    );
  }

  const onCreated = async (jobId: string) => {
    await refreshJobs();
    setSelectedId(jobId);
    setScreen("job");
  };

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex min-h-screen max-w-[100rem] flex-col gap-5 px-4 py-5 lg:flex-row lg:px-6">
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
            <div className="mb-4">
              <Callout
                tone="bad"
                title="Não estou conseguindo falar com a ferramenta"
                action={
                  <Button
                    size="sm"
                    onClick={() => {
                      setBootError(null);
                      void refreshJobs();
                    }}
                  >
                    Tentar de novo
                  </Button>
                }
              >
                <p>
                  Confira se o comando <code>clip serve</code> ainda está rodando no Terminal.
                </p>
              </Callout>
            </div>
          )}

          {screen === "settings" ? (
            <Settings health={health} onChanged={() => void refreshHealth()} />
          ) : screen === "job" && selectedId !== null && progress === null ? (
            // Carregando um job já escolhido. Cair no formulário de "novo
            // corte" aqui fazia a tela piscar como se o clique não tivesse
            // funcionado.
            <div className="space-y-4 pt-2">
              <Skeleton className="h-7 w-64" />
              <Skeleton className="h-32 w-full" />
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                <Skeleton className="h-56 w-full" />
                <Skeleton className="h-56 w-full" />
                <Skeleton className="h-56 w-full" />
              </div>
            </div>
          ) : screen === "new" || selectedId === null || progress === null ? (
            <NewJob config={config} health={health} onCreated={onCreated} />
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
              onSubtitlesChanged={applySubtitles}
            />
          )}
        </main>
      </div>
    </div>
  );
}
