import { useEffect, useState } from "react";
import type {
  AnchorHTMLAttributes,
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
} from "react";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "outline" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({
  variant = "outline",
  size = "md",
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-45";
  const sizes = { sm: "px-3 py-1.5 text-[0.8rem]", md: "px-4 py-2.5 text-sm" };
  const variants = {
    primary:
      "bg-brand-500 text-white shadow-lg shadow-brand-600/25 hover:bg-brand-400 active:scale-[0.985]",
    outline: "border border-white/12 bg-white/4 text-mist-200 hover:border-white/25 hover:bg-white/8",
    ghost: "text-mist-400 hover:bg-white/6 hover:text-mist-200",
    danger: "border border-red-400/25 bg-red-500/10 text-red-200 hover:bg-red-500/20",
  };
  return (
    <button
      className={cx(base, sizes[size], variants[variant], className)}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Spinner />}
      {children}
    </button>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cx(
        "size-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent",
        className,
      )}
      aria-hidden
    />
  );
}

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: "neutral" | "brand" | "good" | "warn" | "bad";
  className?: string;
}) {
  const tones = {
    neutral: "border-white/12 bg-white/6 text-mist-300",
    brand: "border-brand-400/40 bg-brand-500/12 text-brand-400",
    good: "border-lime-300/35 bg-lime-300/10 text-lime-300",
    warn: "border-amber-300/35 bg-amber-300/10 text-amber-200",
    bad: "border-red-400/35 bg-red-500/12 text-red-200",
  };
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[0.7rem] font-medium tracking-wide",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Card({
  children,
  className,
  as: Tag = "section",
}: {
  children: ReactNode;
  className?: string;
  as?: "section" | "div" | "article";
}) {
  return <Tag className={cx("panel p-5", className)}>{children}</Tag>;
}

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label
        htmlFor={htmlFor}
        className="flex items-baseline justify-between text-[0.78rem] font-medium text-mist-300"
      >
        <span>{label}</span>
        {hint && <span className="text-[0.7rem] font-normal text-mist-400">{hint}</span>}
      </label>
      {children}
    </div>
  );
}

export function TextInput({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cx(
        "w-full rounded-xl border border-white/12 bg-ink-950/70 px-3.5 py-2.5 text-sm text-mist-200 placeholder:text-mist-400/60",
        "transition-colors focus:border-brand-400/60 focus:bg-ink-950",
        className,
      )}
      {...rest}
    />
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  size = "md",
}: {
  value: T;
  options: { value: T; label: string; hint?: string }[];
  onChange: (value: T) => void;
  size?: "sm" | "md";
}) {
  return (
    <div
      role="tablist"
      className="inline-flex w-full rounded-xl border border-white/10 bg-ink-950/60 p-1"
    >
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          type="button"
          aria-selected={value === option.value}
          title={option.hint}
          onClick={() => onChange(option.value)}
          className={cx(
            "flex-1 rounded-lg font-medium transition-all",
            size === "sm" ? "px-2 py-1 text-[0.72rem]" : "px-3 py-1.5 text-[0.8rem]",
            value === option.value
              ? "bg-brand-500/90 text-white shadow-sm shadow-brand-600/30"
              : "text-mist-400 hover:bg-white/6 hover:text-mist-200",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  label: string;
  hint?: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex w-full items-center justify-between gap-3 rounded-xl border border-white/10 bg-ink-950/50 px-3.5 py-2.5 text-left transition-colors hover:border-white/20"
    >
      <span>
        <span className="block text-[0.82rem] font-medium text-mist-200">{label}</span>
        {hint && <span className="block text-[0.7rem] text-mist-400">{hint}</span>}
      </span>
      <span
        className={cx(
          "relative h-5 w-9 shrink-0 rounded-full transition-colors",
          checked ? "bg-brand-500" : "bg-ink-600",
        )}
      >
        <span
          className={cx(
            "absolute top-0.5 size-4 rounded-full bg-white transition-transform",
            checked ? "translate-x-4.5" : "translate-x-0.5",
          )}
        />
      </span>
    </button>
  );
}

export function CheckPill({
  checked,
  onChange,
  children,
}: {
  checked: boolean;
  onChange: (value: boolean) => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={cx(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-[0.78rem] font-medium transition-all",
        checked
          ? "border-brand-400/50 bg-brand-500/15 text-brand-400"
          : "border-white/12 bg-white/4 text-mist-400 hover:border-white/25 hover:text-mist-200",
      )}
    >
      <span
        className={cx(
          "grid size-3.5 place-items-center rounded-[0.25rem] border text-[0.6rem]",
          checked ? "border-brand-400 bg-brand-500 text-white" : "border-white/25",
        )}
        aria-hidden
      >
        {checked ? "✓" : ""}
      </span>
      {children}
    </button>
  );
}

export function StatusDot({ status }: { status: string }) {
  const tones: Record<string, string> = {
    running: "bg-brand-400 pulse-ring",
    queued: "bg-amber-300",
    done: "bg-lime-300",
    error: "bg-red-400",
    canceled: "bg-mist-400",
    pending: "bg-ink-600",
    skipped: "bg-ink-600",
  };
  return <span className={cx("size-2 shrink-0 rounded-full", tones[status] ?? "bg-ink-600")} />;
}

export function ProgressBar({
  value,
  active,
  tone = "brand",
  label,
  valueText,
  announce = false,
}: {
  value: number;
  active?: boolean;
  tone?: "brand" | "done" | "error";
  /** Nome acessível da barra (ex. "Progresso do job"). */
  label?: string;
  /** Leitura humana do estado: "71% — Renderizando cortes, ~2 min restantes". */
  valueText?: string;
  /**
   * Anuncia mudanças em leitor de tela. Um job longo emite dezenas de
   * atualizações por minuto, então só a barra global pede isso — e em
   * `polite`, para não interromper o que o usuário está lendo.
   */
  announce?: boolean;
}) {
  const tones = {
    brand: "from-brand-600 to-brand-400",
    done: "from-lime-600 to-lime-300",
    error: "from-red-600 to-red-400",
  };
  return (
    <div
      className="h-1.5 w-full overflow-hidden rounded-full bg-white/8"
      role="progressbar"
      aria-label={label}
      aria-valuenow={Math.round(value * 100)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuetext={valueText}
      aria-live={announce ? "polite" : undefined}
    >
      <div
        className={cx(
          "relative h-full rounded-full bg-gradient-to-r transition-[width] duration-300",
          tones[tone],
          active && "progress-shimmer",
        )}
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  );
}

export function EmptyState({
  title,
  description,
  icon,
  children,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-white/10 px-6 py-12 text-center">
      {icon && <div className="text-2xl opacity-70">{icon}</div>}
      <h3 className="text-sm font-semibold text-mist-200">{title}</h3>
      {description && <p className="max-w-sm text-[0.82rem] text-mist-400">{description}</p>}
      {children}
    </div>
  );
}

/**
 * Aviso com uma ação clara. Um erro sem próximo passo só transfere o problema
 * para quem está lendo, então `action` faz parte do componente.
 */
export function Callout({
  tone = "info",
  title,
  children,
  action,
}: {
  tone?: "info" | "warn" | "bad" | "good";
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  const tones = {
    info: "border-brand-400/25 bg-brand-500/8",
    warn: "border-amber-300/25 bg-amber-300/8",
    bad: "border-red-400/25 bg-red-500/8",
    good: "border-lime-300/25 bg-lime-300/8",
  };
  const icons = { info: "i", warn: "!", bad: "!", good: "✓" };
  const iconTones = {
    info: "bg-brand-500/25 text-brand-400",
    warn: "bg-amber-300/20 text-amber-200",
    bad: "bg-red-500/20 text-red-200",
    good: "bg-lime-300/20 text-lime-300",
  };
  return (
    <div className={cx("flex gap-3 rounded-2xl border p-4", tones[tone])}>
      <span
        className={cx(
          "mt-0.5 grid size-5 shrink-0 place-items-center rounded-full text-[0.7rem] font-bold",
          iconTones[tone],
        )}
        aria-hidden
      >
        {icons[tone]}
      </span>
      <div className="min-w-0 flex-1 space-y-2">
        <p className="text-[0.85rem] font-semibold text-mist-200">{title}</p>
        {children && <div className="text-[0.8rem] leading-relaxed text-mist-300">{children}</div>}
        {action && <div className="flex flex-wrap gap-2 pt-0.5">{action}</div>}
      </div>
    </div>
  );
}

/** Copia um texto e confirma na própria etiqueta do botão. */
export function CopyButton({
  value,
  label = "Copiar",
  className,
  size = "sm",
}: {
  value: string;
  label?: string;
  className?: string;
  size?: "sm" | "md";
}) {
  const [copied, setCopied] = useState(false);
  useEffect(() => {
    if (!copied) return;
    const timer = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timer);
  }, [copied]);

  return (
    <Button
      size={size}
      variant={copied ? "primary" : "outline"}
      className={className}
      disabled={!value}
      onClick={() => {
        void navigator.clipboard
          .writeText(value)
          .then(() => setCopied(true))
          .catch(() => setCopied(false));
      }}
    >
      {copied ? "Copiado" : label}
    </Button>
  );
}

/**
 * Seção que começa fechada. É o mecanismo que deixa a tela inicial com um
 * campo só sem esconder nenhum controle de quem procura por ele.
 */
export function Disclosure({
  summary,
  hint,
  children,
  defaultOpen = false,
}: {
  summary: string;
  hint?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-2xl border border-white/10 bg-ink-950/40">
      <button
        type="button"
        aria-expanded={open}
        aria-label={summary}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <span>
          <span className="block text-[0.85rem] font-medium text-mist-200">{summary}</span>
          {hint && <span className="block text-[0.72rem] text-mist-400">{hint}</span>}
        </span>
        <span
          className={cx(
            "shrink-0 text-mist-400 transition-transform duration-200",
            open && "rotate-180",
          )}
          aria-hidden
        >
          ▾
        </span>
      </button>
      {open && <div className="space-y-4 border-t border-white/8 px-4 py-4 fade-up">{children}</div>}
    </div>
  );
}

/** Opção grande e clicável, com nome e explicação. Usada em vez de select. */
export function ChoiceCard({
  selected,
  onSelect,
  title,
  description,
  badge,
  disabled,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  description?: string;
  badge?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      disabled={disabled}
      onClick={onSelect}
      className={cx(
        "flex w-full items-start gap-3 rounded-xl border p-3 text-left transition-all",
        "disabled:cursor-not-allowed disabled:opacity-45",
        selected
          ? "border-brand-400/60 bg-brand-500/10"
          : "border-white/10 bg-white/3 hover:border-white/25 hover:bg-white/6",
      )}
    >
      <span
        className={cx(
          "mt-0.5 grid size-4 shrink-0 place-items-center rounded-full border-2 transition-colors",
          selected ? "border-brand-400" : "border-white/25",
        )}
        aria-hidden
      >
        {selected && <span className="size-1.5 rounded-full bg-brand-400" />}
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span className="text-[0.85rem] font-medium text-mist-200">{title}</span>
          {badge}
        </span>
        {description && (
          <span className="mt-0.5 block text-[0.75rem] leading-relaxed text-mist-400">
            {description}
          </span>
        )}
      </span>
    </button>
  );
}

/** Barra de abas simples (usada para trocar de formato no player). */
export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string; disabled?: boolean }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="flex flex-wrap gap-1.5">
      {options.map((option) => (
        <button
          key={option.value}
          role="tab"
          type="button"
          disabled={option.disabled}
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={cx(
            "rounded-lg px-3 py-1.5 text-[0.78rem] font-medium transition-all disabled:cursor-not-allowed disabled:opacity-35",
            value === option.value
              ? "bg-white/12 text-mist-200"
              : "text-mist-400 hover:bg-white/6 hover:text-mist-200",
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("animate-pulse rounded-lg bg-white/6", className)} aria-hidden />;
}

/** Rótulo + valor, para os pares de informação que se repetem nas telas. */
export function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: ReactNode;
  tone?: string;
}) {
  return (
    <div className="min-w-0">
      <p className="text-[0.68rem] tracking-wide text-mist-400 uppercase">{label}</p>
      <p className={cx("truncate text-[0.9rem] font-medium text-mist-200", tone)}>{value}</p>
    </div>
  );
}

/**
 * Âncora com aparência de botão. Download é navegação, não ação de script:
 * embrulhar um `<a download>` dentro de `<button>` produz HTML inválido e o
 * teclado passa duas vezes pelo mesmo alvo.
 */
export function LinkButton({
  href,
  children,
  variant = "outline",
  size = "md",
  download,
  className,
  ...rest
}: {
  href: string;
  children: ReactNode;
  variant?: "primary" | "ghost" | "outline";
  size?: "sm" | "md";
  download?: boolean;
  className?: string;
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href" | "className">) {
  const sizes = { sm: "px-3 py-1.5 text-[0.8rem]", md: "px-4 py-2.5 text-sm" };
  const variants = {
    primary: "bg-brand-500 text-white shadow-lg shadow-brand-600/25 hover:bg-brand-400",
    outline: "border border-white/12 bg-white/4 text-mist-200 hover:border-white/25 hover:bg-white/8",
    ghost: "text-mist-400 hover:bg-white/6 hover:text-mist-200",
  };
  return (
    <a
      href={href}
      download={download}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition-all duration-150",
        sizes[size],
        variants[variant],
        className,
      )}
      {...rest}
    >
      {children}
    </a>
  );
}
