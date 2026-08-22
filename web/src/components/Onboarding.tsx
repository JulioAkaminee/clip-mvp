import { useState } from "react";
import { api, ApiError } from "../lib/api";
import type { ConnectionTestResult, Health } from "../lib/types";
import { formatUsd } from "../lib/format";
import { Button, Callout, Card, TextInput, cx } from "./ui";

/**
 * Primeira execução: a ferramenta não faz nada sem uma chave da OpenRouter, e
 * antes disso a pessoa caía direto no formulário de job — que aceitava o link,
 * começava a rodar e só falhava lá na frente. Aqui o pré-requisito vem antes,
 * explicado, com o teste de conexão no mesmo lugar.
 */
export function Onboarding({
  health,
  onReady,
}: {
  health: Health | null;
  onReady: () => void;
}) {
  const [key, setKey] = useState("");
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<ConnectionTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const missingTools = [
    !health?.ffmpeg && "ffmpeg",
    !health?.yt_dlp && "yt-dlp",
  ].filter(Boolean) as string[];

  const trimmed = key.trim();
  const looksValid = trimmed.startsWith("sk-or-") && trimmed.length > 20;

  const test = async () => {
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      setResult(await api.testConnection(trimmed));
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setTesting(false);
    }
  };

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateSettings({ api_key: trimmed });
      onReady();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <div className="mx-auto flex min-h-screen max-w-2xl flex-col justify-center gap-6 px-4 py-10">
      <header className="space-y-3 text-center">
        <p className="text-[0.75rem] font-medium tracking-[0.2em] text-brand-400 uppercase">
          Bem-vindo
        </p>
        <h1 className="text-3xl font-semibold text-white">
          Transforme um vídeo longo em cortes prontos para publicar
        </h1>
        <p className="mx-auto max-w-lg text-[0.9rem] leading-relaxed text-mist-300">
          Você cola o link de um podcast ou live. A ferramenta assiste, escolhe os melhores
          momentos, corta sem interromper ninguém no meio da frase, legenda e escreve o título e
          as hashtags. Falta só uma coisa para começar.
        </p>
      </header>

      {missingTools.length > 0 && (
        <Callout tone="warn" title={`Instale ${missingTools.join(" e ")} antes de começar`}>
          <p>
            A ferramenta usa esses programas para baixar e cortar o vídeo no seu computador. No
            Mac, abra o Terminal e rode:
          </p>
          <code className="mt-2 block rounded-lg bg-black/40 px-3 py-2 font-mono text-[0.75rem] text-mist-200">
            brew install {missingTools.join(" ")}
          </code>
          <p className="mt-2">Depois reinicie a ferramenta e volte aqui.</p>
        </Callout>
      )}

      <Card className="space-y-5">
        <Step
          number={1}
          title="Pegue uma chave da OpenRouter"
          done={looksValid}
        >
          <p>
            A OpenRouter é o serviço que faz a parte de inteligência artificial: transcrever,
            escolher os momentos e escrever os textos. A conta é gratuita e você só paga pelo que
            usar — normalmente centavos de dólar por vídeo.
          </p>
          <a
            href="https://openrouter.ai/keys"
            target="_blank"
            rel="noreferrer"
            className="mt-2 inline-flex items-center gap-1.5 text-[0.82rem] font-medium text-brand-400 underline-offset-4 hover:underline"
          >
            Criar minha chave em openrouter.ai
            <span aria-hidden>↗</span>
          </a>
        </Step>

        <Step
          number={2}
          title="Cole a chave aqui"
          done={result?.ok === true}
        >
          <div className="mt-2 flex flex-col gap-2 sm:flex-row">
            <TextInput
              type="password"
              value={key}
              autoComplete="off"
              spellCheck={false}
              placeholder="sk-or-v1-..."
              aria-label="Chave da OpenRouter"
              onChange={(event) => {
                setKey(event.target.value);
                setResult(null);
                setError(null);
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && looksValid && !testing) void test();
              }}
              className="font-mono text-[0.8rem]"
            />
            <Button
              variant="outline"
              onClick={() => void test()}
              disabled={!looksValid || testing}
              loading={testing}
              className="shrink-0"
            >
              Testar conexão
            </Button>
          </div>
          <p className="mt-2 text-[0.72rem] text-mist-400">
            A chave fica só no seu computador, num arquivo protegido fora da pasta do projeto.
            Ela nunca aparece inteira nesta tela de novo.
          </p>

          {result && (
            <div className="mt-3">
              {result.ok ? (
                <Callout tone="good" title="Conexão funcionando">
                  <p>
                    {result.label ? `Conta: ${result.label}. ` : ""}
                    {result.limit_remaining_usd != null
                      ? `Você tem ${formatUsd(result.limit_remaining_usd)} de crédito disponível.`
                      : result.is_free_tier
                        ? "Você está no plano gratuito — dá para testar, mas vídeos longos podem esbarrar no limite."
                        : "Crédito disponível na conta."}
                  </p>
                </Callout>
              ) : (
                <Callout tone="bad" title="A OpenRouter não aceitou essa chave">
                  <p>{result.message}</p>
                  <p className="mt-1">
                    Confira se copiou a chave inteira, incluindo o começo <code>sk-or-</code>.
                  </p>
                </Callout>
              )}
            </div>
          )}
          {error && (
            <div className="mt-3">
              <Callout tone="bad" title="Não deu para testar agora">
                <p>{error}</p>
              </Callout>
            </div>
          )}
        </Step>

        <Step number={3} title="Pronto para o primeiro corte" done={false} last>
          <p>
            Salvamos a chave e você já pode colar um link. Dá para trocar tudo isso depois em
            Configurações.
          </p>
          <Button
            variant="primary"
            className="mt-3 w-full sm:w-auto"
            onClick={() => void save()}
            disabled={!looksValid || saving}
            loading={saving}
          >
            Salvar e começar
          </Button>
          {!looksValid && (
            <p className="mt-2 text-[0.72rem] text-mist-400">
              Cole a chave no passo 2 para liberar este botão.
            </p>
          )}
        </Step>
      </Card>

      <p className="text-center text-[0.75rem] text-mist-400">
        Já tem a chave num arquivo <code>.env</code>? Ela também funciona — esta tela some
        sozinha assim que a ferramenta encontrar uma.
      </p>
    </div>
  );
}

function Step({
  number,
  title,
  children,
  done,
  last = false,
}: {
  number: number;
  title: string;
  children: React.ReactNode;
  done: boolean;
  last?: boolean;
}) {
  return (
    <div className="flex gap-4">
      <div className="flex shrink-0 flex-col items-center">
        <span
          className={cx(
            "grid size-7 place-items-center rounded-full border text-[0.78rem] font-semibold transition-colors",
            done
              ? "border-lime-300/50 bg-lime-300/15 text-lime-300"
              : "border-white/15 bg-white/5 text-mist-300",
          )}
        >
          {done ? "✓" : number}
        </span>
        {!last && <span className="mt-1 w-px flex-1 bg-white/10" aria-hidden />}
      </div>
      <div className={cx("min-w-0 flex-1", !last && "pb-1")}>
        <h2 className="text-[0.92rem] font-semibold text-mist-200">{title}</h2>
        <div className="mt-1 text-[0.82rem] leading-relaxed text-mist-300">{children}</div>
      </div>
    </div>
  );
}
