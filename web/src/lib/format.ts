/**
 * Camada de linguagem da interface.
 *
 * O backend fala em `min_score`, `dry_run`, `vertical_facetrack` e
 * `context_exceeds_90s`. Quem usa a ferramenta fala em "só os melhores", "só
 * estimar o custo", "vertical com zoom no rosto" e "esse momento é longo
 * demais para Short". Toda tradução mora aqui, num lugar só, para nenhuma tela
 * precisar inventar a sua.
 */

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "--:--";
  const total = Math.round(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** "1 h 12 min", "8 min", "40 s" — para durações que o usuário lê, não cronometra. */
export function humanDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return "—";
  if (seconds < 60) return `${Math.round(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min`;
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return m === 0 ? `${h} h` : `${h} h ${m} min`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  if (value < 0.01) return "menos de US$ 0,01";
  return `US$ ${value.toFixed(2).replace(".", ",")}`;
}

export function formatClock(timestamp: number | null | undefined): string {
  if (!timestamp) return "";
  return new Date(timestamp * 1000).toLocaleTimeString("pt-BR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "agora", "há 5 min", "ontem" — idade de um job na lista lateral. */
export function timeAgo(timestamp: number | null | undefined): string {
  if (!timestamp) return "";
  const seconds = Date.now() / 1000 - timestamp;
  if (seconds < 90) return "agora";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `há ${minutes} min`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `há ${hours} h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "ontem" : `há ${days} dias`;
}

// --- Formatos de saída -----------------------------------------------------

export interface FormatInfo {
  /** Chave que o backend recebe em `formats`. */
  key: "face" | "9x16" | "16x9";
  /** Nome do arquivo que sai em `out/`. */
  file: string;
  name: string;
  /** Onde a pessoa vai publicar isso. */
  where: string;
  description: string;
  vertical: boolean;
}

export const FORMATS: FormatInfo[] = [
  {
    key: "face",
    file: "vertical_facetrack.mp4",
    name: "Vertical com zoom no rosto",
    where: "TikTok, Reels, Shorts",
    description:
      "A câmera acompanha quem está falando e salta junto na troca de plano. É o que mais segura a atenção — e o mais lento de gerar. Em cena aberta, com várias pessoas, cai sozinho para um enquadramento mais largo.",
    vertical: true,
  },
  {
    key: "9x16",
    file: "vertical_center.mp4",
    name: "Vertical com enquadramento fixo",
    where: "TikTok, Reels, Shorts",
    description:
      "Recorte central preenchendo a tela inteira, sem a câmera acompanhar ninguém. Rápido de gerar e previsível.",
    vertical: true,
  },
  {
    key: "16x9",
    file: "horizontal_16x9.mp4",
    name: "Horizontal",
    where: "YouTube",
    description: "O corte na proporção original, mais longo, para o feed normal do YouTube.",
    vertical: false,
  },
];

export const FORMAT_BY_FILE: Record<string, FormatInfo> = Object.fromEntries(
  FORMATS.map((format) => [format.file, format]),
);

export function formatLabel(file: string): string {
  return FORMAT_BY_FILE[file]?.name ?? file;
}

// --- Etapas do processamento ----------------------------------------------

/** O que está acontecendo agora, em uma frase que não pressupõe nada. */
export const STAGE_STORY: Record<string, string> = {
  queued: "Preparando tudo para começar",
  download: "Baixando o vídeo do link que você colou",
  transcribe: "Ouvindo o áudio e escrevendo tudo o que é dito",
  candidates: "Lendo a transcrição atrás dos momentos que se sustentam sozinhos",
  score: "Dando uma nota de 0 a 100 para cada momento",
  select: "Ficando só com os cortes que valem a pena publicar",
  captions: "Sincronizando a legenda palavra por palavra",
  render: "Montando os arquivos de vídeo",
  meta: "Escrevendo título, descrição e hashtags de cada corte",
  done: "Terminado",
  error: "Algo deu errado",
  canceled: "Cancelado por você",
};

/** Como a etapa aparece no passo a passo. */
export const STAGE_SHORT: Record<string, string> = {
  download: "Baixar",
  transcribe: "Transcrever",
  candidates: "Achar momentos",
  score: "Dar nota",
  select: "Selecionar",
  captions: "Legendar",
  render: "Montar vídeos",
  meta: "Escrever textos",
};

// --- Explicações de decisões do pipeline ----------------------------------

export const SKIP_REASONS: Record<string, string> = {
  context_exceeds_90s:
    "Esse momento só faz sentido inteiro, e inteiro ele passa de 1min30 — o limite de um Short. " +
    "Em vez de cortar a frase no meio, geramos só a versão horizontal.",
  context_below_min:
    "O que dá para aproveitar aqui sem cortar ninguém no meio da frase ficou curto demais para " +
    "um Short. Geramos só a versão horizontal.",
};

export function skipReasonText(reason: string | null | undefined): string | null {
  if (!reason) return null;
  return (
    SKIP_REASONS[reason] ??
    "A versão vertical foi descartada para não cortar a fala no meio. Só a horizontal foi gerada."
  );
}

export const BREAKDOWN_LABELS: Record<string, { name: string; help: string }> = {
  hook: {
    name: "Abertura",
    help: "Os três primeiros segundos prendem quem está passando o dedo pela tela?",
  },
  emocao: { name: "Emoção", help: "Tem graça, tensão ou surpresa suficiente para gerar reação?" },
  citavel: { name: "Citável", help: "Funciona sozinho, fora do episódio, como um recorte?" },
  arco: { name: "História completa", help: "Começa, desenvolve e fecha — sem ficar no meio?" },
};

/** Uma frase honesta sobre o que a nota significa. */
export function scoreVerdict(score: number | null | undefined): string {
  if (score == null) return "Ainda sem nota";
  if (score >= 85) return "Melhor deste vídeo — publique este primeiro";
  if (score >= 70) return "Forte, pronto para publicar";
  if (score >= 60) return "Bom, vale publicar";
  if (score >= 45) return "Mediano — revise antes de publicar";
  return "Fraco — o corte não fecha a ideia";
}

/** Uma palavra só, para caber na tarja do card sem quebrar linha. */
export function scoreWord(score: number | null | undefined): string {
  if (score == null) return "";
  if (score >= 85) return "excelente";
  if (score >= 70) return "forte";
  if (score >= 60) return "bom";
  if (score >= 45) return "mediano";
  return "fraco";
}

export function scoreTone(score: number | null | undefined): string {
  if (score == null) return "text-mist-400";
  if (score >= 85) return "text-lime-300";
  if (score >= 70) return "text-brand-400";
  if (score >= 60) return "text-amber-300";
  return "text-mist-400";
}

/** Só a borda: para emblemas que precisam de fundo sólido sobre uma foto. */
export function scoreBorder(score: number | null | undefined): string {
  if (score == null) return "border-white/20";
  if (score >= 85) return "border-lime-300/60";
  if (score >= 70) return "border-brand-400/60";
  if (score >= 60) return "border-amber-300/50";
  return "border-white/20";
}

export function scoreRing(score: number | null | undefined): string {
  if (score == null) return "border-white/15 bg-white/5";
  if (score >= 85) return "border-lime-300/60 bg-lime-300/10";
  if (score >= 70) return "border-brand-400/60 bg-brand-400/10";
  if (score >= 60) return "border-amber-300/50 bg-amber-300/10";
  return "border-white/15 bg-white/5";
}

// --- Rigor da seleção ------------------------------------------------------

export interface StrictnessOption {
  id: "relaxado" | "equilibrado" | "exigente";
  name: string;
  description: string;
  minScore: number;
}

/**
 * `min_score` vira uma escolha de três, porque "60" não diz nada para quem
 * abriu a ferramenta pela primeira vez — e mexer no número sem entender a
 * escala é a forma mais rápida de receber zero cortes e achar que quebrou.
 */
export const STRICTNESS: StrictnessOption[] = [
  {
    id: "relaxado",
    name: "Me mostre tudo",
    description: "Traz mais cortes, incluindo os medianos. Bom para garimpar você mesmo.",
    minScore: 45,
  },
  {
    id: "equilibrado",
    name: "Equilibrado",
    description: "O padrão. Só o que a nota indica que está pronto para publicar.",
    minScore: 60,
  },
  {
    id: "exigente",
    name: "Só os excelentes",
    description: "Poucos cortes, os melhores. Pode não sobrar nenhum em vídeo fraco.",
    minScore: 78,
  },
];

export function strictnessFor(minScore: number): StrictnessOption {
  return (
    [...STRICTNESS].reverse().find((option) => minScore >= option.minScore) ?? STRICTNESS[1]
  );
}

// --- Erros -----------------------------------------------------------------

/**
 * Um erro técnico vira "o que aconteceu" + "o que fazer agora". O backend já
 * manda uma dica em `error.hint`; aqui cobrimos o que ele não cobre.
 */
export function friendlyError(message: string, hint?: string): { what: string; next: string } {
  const text = (message || "").toLowerCase();
  if (text.includes("openrouter_api_key") || text.includes("401")) {
    return {
      what: "A OpenRouter não aceitou a chave.",
      next: "Abra Configurações, cole a chave de novo e clique em Testar conexão.",
    };
  }
  if (text.includes("429") || text.includes("rate limit")) {
    return {
      what: "A OpenRouter pediu para desacelerar (limite de uso).",
      next: "Espere alguns minutos e clique em Continuar de onde parou. Nada do que já foi feito se perde.",
    };
  }
  if (text.includes("sign in to confirm") || text.includes("bot")) {
    return {
      what: "O YouTube pediu login para liberar esse vídeo.",
      next: "Abra o vídeo no Chrome, faça login e tente de novo — a ferramenta reaproveita os cookies do navegador.",
    };
  }
  if (text.includes("yt-dlp") || text.includes("unavailable") || text.includes("private")) {
    return {
      what: "Não foi possível baixar esse vídeo.",
      next: "Confira se o link abre normalmente numa aba anônima. Vídeo privado ou com restrição de idade não funciona.",
    };
  }
  if (text.includes("ffmpeg") || text.includes("ffprobe")) {
    return {
      what: "O ffmpeg não foi encontrado nesta máquina.",
      next: "Instale com `brew install ffmpeg` no Terminal e reinicie a ferramenta.",
    };
  }
  if (text.includes("whisper") || text.includes("audio/transcriptions")) {
    return {
      what: "O modelo escolhido para transcrever não sabe transcrever áudio.",
      next: "Em Configurações, volte o modelo de transcrição para openai/whisper-1.",
    };
  }
  if (text.includes("espaço") || text.includes("no space")) {
    return {
      what: "O disco encheu no meio do processamento.",
      next: "Libere espaço e clique em Continuar de onde parou.",
    };
  }
  return {
    what: message || "Algo deu errado no meio do processamento.",
    next: hint || "Clique em Continuar de onde parou — o que já foi feito está guardado.",
  };
}

// --- Diversos --------------------------------------------------------------

export function pluralize(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function prettyUrl(url: string | undefined): string {
  if (!url) return "";
  try {
    const parsed = new URL(url);
    return `${parsed.hostname.replace(/^www\./, "")}${parsed.pathname}`.slice(0, 60);
  } catch {
    return url.slice(0, 60);
  }
}
