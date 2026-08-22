import { useEffect, useRef, useState } from "react";

/**
 * Quais itens acabaram de chegar, para só eles animarem a entrada.
 *
 * Sem isso, a grade inteira reanima a cada atualização do progresso — a lista
 * é reconstruída de dois em dois segundos, e "animar tudo que renderiza" vira
 * um piscar contínuo. Movimento tem de corresponder a um fato, e o fato aqui é
 * "este corte não existia no quadro anterior".
 *
 * A marca de novidade expira sozinha: um corte que chegou há dez segundos não
 * é mais novidade, e se ele reaparecer numa remontagem da lista não deve
 * animar de novo.
 */
export function useArrivals<T>(
  items: T[],
  keyOf: (item: T) => string,
  isReady: (item: T) => boolean,
  { ttlMs = 900 }: { ttlMs?: number } = {},
): Set<string> {
  const seen = useRef<Set<string>>(new Set());
  const first = useRef(true);
  const [fresh, setFresh] = useState<Set<string>>(new Set());

  useEffect(() => {
    const ready = items.filter(isReady).map(keyOf);
    const novos = ready.filter((key) => !seen.current.has(key));
    ready.forEach((key) => seen.current.add(key));

    // Abrir um job já terminado não é chegada: os cortes estavam lá antes de a
    // tela existir. Animar os quinze de uma vez seria fogos de artifício.
    if (first.current) {
      first.current = false;
      return;
    }
    if (novos.length === 0) return;

    setFresh((atual) => new Set([...atual, ...novos]));
    const timer = window.setTimeout(() => {
      setFresh((atual) => {
        const restante = new Set(atual);
        novos.forEach((key) => restante.delete(key));
        return restante;
      });
    }, ttlMs);
    return () => window.clearTimeout(timer);
  }, [items, keyOf, isReady, ttlMs]);

  return fresh;
}
