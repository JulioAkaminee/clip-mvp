import { useEffect, useRef, useState } from "react";
import { formatTime } from "../lib/format";
import type { LogLine } from "../lib/types";
import { cx } from "./ui";

/** Histórico das mensagens que passaram pelo stream de progresso. */
export function LogConsole({ entries }: { entries: LogLine[] }) {
  const [open, setOpen] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [open, entries.length]);

  return (
    <div className="panel overflow-hidden">
      <button
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2 px-4 py-3 text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400 hover:text-mist-200"
        aria-expanded={open}
      >
        <span className={cx("transition-transform", open && "rotate-90")} aria-hidden>
          ▸
        </span>
        Log do job
        <span className="font-mono text-[0.7rem] normal-case tracking-normal text-mist-400">
          ({entries.length})
        </span>
      </button>
      {open && (
        <div className="max-h-64 overflow-y-auto border-t border-white/8 bg-ink-950/60 px-4 py-3 font-mono text-[0.72rem] leading-relaxed">
          {entries.length === 0 && <p className="text-mist-400">sem eventos ainda</p>}
          {entries.map((entry, index) => (
            <p key={`${entry.t}-${index}`} className="flex gap-2 text-mist-300">
              <span className="shrink-0 text-mist-400/70">{formatTime(entry.t)}</span>
              <span className="shrink-0 text-brand-400/70">{entry.stage}</span>
              <span className="whitespace-pre-wrap">{entry.message}</span>
            </p>
          ))}
          <div ref={endRef} />
        </div>
      )}
    </div>
  );
}
