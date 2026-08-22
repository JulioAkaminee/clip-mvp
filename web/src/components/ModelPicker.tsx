import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import type { ModelRoleState, OpenRouterModel } from "../lib/types";
import { Badge, Button, Field, TextInput, cx } from "./ui";

const MODALITY_LABEL: Record<string, string> = {
  text: "texto",
  image: "visão",
  audio: "áudio",
};

function matchesRole(model: OpenRouterModel, requires: string[]): boolean {
  const needed = requires.filter((item) => item !== "text");
  return needed.every((item) => model.input_modalities.includes(item));
}

function formatPrice(usd: number | null): string | null {
  if (usd == null) return null;
  if (usd === 0) return "grátis";
  if (usd < 0.01) return `US$ ${usd.toFixed(4)}/M`;
  return `US$ ${usd.toFixed(2)}/M`;
}

function sourceTone(source: ModelRoleState["source"]): "brand" | "neutral" | "good" {
  if (source === "ui") return "brand";
  if (source === "inherited") return "neutral";
  return "good";
}

function sourceLabel(source: ModelRoleState["source"]): string {
  if (source === "ui") return "pela interface";
  if (source === "inherited") return "herda o STT";
  return "padrão do .env";
}

export function ModelPicker({
  role,
  value,
  catalog,
  catalogError,
  loadingCatalog,
  onChange,
  onRestore,
}: {
  role: ModelRoleState;
  value: string;
  catalog: OpenRouterModel[];
  catalogError: string | null;
  loadingCatalog: boolean;
  onChange: (value: string) => void;
  onRestore: () => void;
}) {
  const inputId = useId();
  const listId = useId();
  const boxRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);

  const query = value.trim().toLowerCase();
  const options = useMemo(() => {
    const matching = catalog.filter((model) => matchesRole(model, role.requires));
    if (!query) return matching.slice(0, 20);
    return matching
      .filter((model) => `${model.id} ${model.name}`.toLowerCase().includes(query))
      .slice(0, 20);
  }, [catalog, query, role.requires]);

  const exact = options.some((model) => model.id === value.trim());
  const dirty = value.trim() !== (role.env_default || "");
  const canRestore = dirty && (Boolean(role.env_default) || role.optional);

  useEffect(() => {
    const onDocClick = (event: MouseEvent) => {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  useEffect(() => {
    setHighlight(0);
  }, [query, open]);

  const pick = (id: string) => {
    onChange(id);
    setOpen(false);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
      setOpen(true);
      event.preventDefault();
      return;
    }
    if (!open) return;
    if (event.key === "ArrowDown") {
      setHighlight((current) => Math.min(current + 1, Math.max(0, options.length - 1)));
      event.preventDefault();
    } else if (event.key === "ArrowUp") {
      setHighlight((current) => Math.max(current - 1, 0));
      event.preventDefault();
    } else if (event.key === "Enter" && options[highlight]) {
      pick(options[highlight].id);
      event.preventDefault();
    } else if (event.key === "Escape") {
      setOpen(false);
    }
  };

  return (
    <Field
      label={role.label}
      hint={
        <span className="flex items-center gap-2">
          <Badge tone={sourceTone(role.source)}>{sourceLabel(role.source)}</Badge>
          {canRestore && (
            <Button type="button" size="sm" variant="ghost" onClick={onRestore} className="!px-1.5 !py-0">
              restaurar padrão
            </Button>
          )}
        </span>
      }
      htmlFor={inputId}
    >
      <p className="-mt-0.5 mb-1.5 text-[0.72rem] leading-snug text-mist-400">{role.description}</p>
      <div ref={boxRef} className="relative">
        <TextInput
          id={inputId}
          role="combobox"
          aria-expanded={open}
          aria-controls={listId}
          aria-autocomplete="list"
          value={value}
          onChange={(event) => {
            onChange(event.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={
            role.optional
              ? `vazio = ${role.env_default || "mesmo modelo de STT"}`
              : role.env_default || "autor/modelo"
          }
          spellCheck={false}
          autoComplete="off"
        />
        {open && (
          <ul
            id={listId}
            role="listbox"
            className="absolute z-20 mt-1 max-h-64 w-full overflow-y-auto rounded-xl border border-white/12 bg-ink-900/95 p-1 shadow-xl shadow-black/40 backdrop-blur-xl"
          >
            {loadingCatalog && (
              <li className="px-3 py-2 text-[0.75rem] text-mist-400">Carregando catálogo da OpenRouter…</li>
            )}
            {catalogError && !loadingCatalog && (
              <li className="px-3 py-2 text-[0.75rem] text-amber-200">{catalogError}</li>
            )}
            {!loadingCatalog && !catalogError && catalog.length === 0 && (
              <li className="px-3 py-2 text-[0.75rem] text-mist-400">
                Digite qualquer id da OpenRouter (ex. <code>google/gemini-2.5-flash</code>). Com a
                chave configurada, o catálogo aparece aqui para busca.
              </li>
            )}
            {value.trim() && !exact && (
              <li>
                <button
                  type="button"
                  role="option"
                  aria-selected={false}
                  onClick={() => pick(value.trim())}
                  className="flex w-full flex-col items-start rounded-lg px-3 py-2 text-left text-[0.78rem] text-mist-200 hover:bg-white/8"
                >
                  <span>Usar exatamente</span>
                  <span className="font-mono text-[0.72rem] text-brand-400">{value.trim()}</span>
                </button>
              </li>
            )}
            {options.map((model, index) => (
              <li key={model.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={highlight === index}
                  onMouseEnter={() => setHighlight(index)}
                  onClick={() => pick(model.id)}
                  className={cx(
                    "flex w-full flex-col gap-0.5 rounded-lg px-3 py-2 text-left",
                    highlight === index ? "bg-brand-500/15" : "hover:bg-white/6",
                  )}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-[0.8rem] font-medium text-mist-200">
                      {model.name}
                    </span>
                    {model.free && <Badge tone="good">grátis</Badge>}
                  </span>
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5 font-mono text-[0.68rem] text-mist-400">
                    <span>{model.id}</span>
                    {model.input_modalities.map((modality) => (
                      <span key={modality}>{MODALITY_LABEL[modality] ?? modality}</span>
                    ))}
                    {formatPrice(model.prompt_usd_per_mtok) && (
                      <span>{formatPrice(model.prompt_usd_per_mtok)}</span>
                    )}
                  </span>
                </button>
              </li>
            ))}
            {!loadingCatalog && catalog.length > 0 && options.length === 0 && (
              <li className="px-3 py-2 text-[0.75rem] text-mist-400">
                Nenhum modelo do catálogo combina. O id digitado ainda vale — qualquer slug da
                OpenRouter é aceito.
              </li>
            )}
          </ul>
        )}
      </div>
    </Field>
  );
}
