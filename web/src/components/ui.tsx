import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from "react";

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

export function ProgressBar({ value, active }: { value: number; active?: boolean }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-white/8">
      <div
        className={cx(
          "relative h-full rounded-full bg-gradient-to-r from-brand-600 to-brand-400 transition-[width] duration-300",
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
