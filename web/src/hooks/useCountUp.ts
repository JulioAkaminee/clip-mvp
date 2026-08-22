import { useEffect, useRef, useState } from "react";

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/**
 * Conta de zero até o valor quando ele aparece.
 *
 * É a única animação puramente expressiva do produto, e existe porque a nota
 * **é** o veredito: o número subindo dá ao olho meio segundo para registrar a
 * escala antes de pousar no resultado. Em qualquer outro lugar isso seria
 * enfeite.
 *
 * Com `prefers-reduced-motion` o valor final aparece direto — o estado nunca
 * depende de a animação ter rodado.
 */
export function useCountUp(target: number | null | undefined, durationMs = 600): number | null {
  const [value, setValue] = useState<number | null>(target ?? null);
  const frame = useRef<number>(0);

  useEffect(() => {
    if (target == null) {
      setValue(null);
      return;
    }
    if (prefersReducedMotion()) {
      setValue(target);
      return;
    }

    const start = performance.now();
    const tick = (now: number) => {
      const progress = Math.min(1, (now - start) / durationMs);
      // Mesma desaceleração exponencial das transições (--ease-out-expo):
      // sobe rápido e pousa devagar no número final.
      const eased = 1 - Math.pow(1 - progress, 4);
      setValue(Math.round(target * eased));
      if (progress < 1) frame.current = requestAnimationFrame(tick);
    };
    frame.current = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame.current);
  }, [target, durationMs]);

  return value;
}
