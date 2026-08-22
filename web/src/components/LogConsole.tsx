import { useEffect, useRef, useState } from "react";
import { formatTime } from "../lib/format";
import type { LogEntry } from "../lib/types";
import { cx } from "./ui";

const TONES: Record<string, string> = {
  info: "text-mist-300",
  warn: "text-amber-200",
  error: "text-red-200",
  debug: "text-mist-400",
};

export function LogConsole({ entries }: { entries: LogEntry[] }) {
  const [open, setOpen] = useState(false);
  const [showDebug, setShowDebug] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const visible = entries.filter((entry) => showDebug || entry.level !== "debug");

  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ block: "end" });
  }, [open, visible.length]);

  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center justify-between gap-3 px-4 py-3">
        <button
          onClick={() => setOpen((value) => !value)}
          className="flex items-center gap-2 text-[0.78rem] font-semibold uppercase tracking-[0.12em] text-mist-400 hover:text-mist-200"
          aria-expanded={open}
        >
          <span className={cx("transition-transform", open && "rotate-90")} aria-hidden>
            ▸
          </span>
          Log do job
          <span className="font-mono text-[0.7rem] normal-case tracking-normal text-mist-400">
            ({visible.length})
          </span>
        </button>
        {open && (
          <label className="flex items-center gap-1.5 text-[0.72rem] text-mist-400">
            <input
              type="checkbox"
              checked={showDebug}
              onChange={(event) => setShowDebug(event.target.checked)}
              className="accent-brand-500"
            />
            detalhes (dedupe, traceback)
          </label>
        )}
      </div>
      {open && (
        <div className="max-h-64 overflow-y-auto border-t border-white/8 bg-ink-950/60 px-4 py-3 font-mono text-[0.72rem] leading-relaxed">
          {visible.length === 0 && <p className="text-mist-400">sem eventos ainda</p>}
          {visible.map((entry, index) => (
            <p key={`${entry.t}-${index}`} className={cx("flex gap-2", TONES[entry.level])}>
              <span className="shrink-0 text-mist-400/70">{formatTime(entry.t)}</span>
              <span className="whitespace-pre-wrap">{entry.message}</span>
            </p>
          ))}
          <div ref={endRef} />
        </div>
      )}
    </div>
  );
}
