import { useCallback, useEffect, useState } from "react";
import { api } from "./lib/api";
import type { AppConfig, Health, Job } from "./lib/types";
import { useJobStream } from "./hooks/useJobStream";
import { JobView } from "./components/JobView";
import { NewJobForm } from "./components/NewJobForm";
import { Sidebar } from "./components/Sidebar";
import { Button, Card } from "./components/ui";

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
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
      const running = list.find((job) => job.status === "running" || job.status === "queued");
      setSelectedId(running?.id ?? null);
    })();
  }, [refreshJobs]);

  const { job, connected, reload } = useJobStream(selectedId, () => void refreshJobs());

  // Mantém a lista lateral fresca enquanto há job na fila ou rodando.
  useEffect(() => {
    const hasActive = jobs.some((item) => item.status === "running" || item.status === "queued");
    if (!hasActive) return;
    const timer = window.setInterval(() => void refreshJobs(), 5000);
    return () => window.clearInterval(timer);
  }, [jobs, refreshJobs]);

  const onCreated = async (jobId: string) => {
    await refreshJobs();
    setSelectedId(jobId);
  };

  return (
    <div className="min-h-screen">
      <div className="mx-auto flex min-h-screen max-w-[100rem] flex-col gap-6 px-4 py-5 lg:flex-row lg:px-6">
        <div className="lg:sticky lg:top-5 lg:h-[calc(100vh-2.5rem)]">
          <Sidebar
            jobs={jobs}
            selectedId={selectedId}
            health={health}
            onSelect={setSelectedId}
            onNew={() => setSelectedId(null)}
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

          {selectedId === null || job === null ? (
            <NewJobForm config={config} health={health} onCreated={onCreated} />
          ) : (
            <JobView
              job={job}
              connected={connected}
              onChanged={() => {
                void reload();
                void refreshJobs();
              }}
              onDeleted={() => {
                setSelectedId(null);
                void refreshJobs();
              }}
            />
          )}
        </main>
      </div>
    </div>
  );
}
