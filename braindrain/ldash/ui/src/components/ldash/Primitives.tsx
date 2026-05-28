import type { PropsWithChildren, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChipTone } from "@/data";
import { toneClass } from "@/theme";

export function Panel({
  children,
  className = "",
  glow = false,
  lift = false,
}: PropsWithChildren<{ className?: string; glow?: boolean; lift?: boolean }>) {
  const baseClasses = "ld-panel";
  const glowClass = glow ? "ld-panel-glow" : "";
  const liftClass = lift ? "ld-panel-lift" : "";
  const glowHoverClass = glow ? "ld-panel-glow-hover" : "";
  return (
    <section className={`${baseClasses} ${glowClass} ${liftClass} ${glowHoverClass} ${className}`.trim()}>
      {children}
    </section>
  );
}

export function SectionHeader({
  eyebrow,
  title,
  detail,
  action,
}: {
  eyebrow: string;
  title: string;
  detail?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div className="max-w-[42rem]">
        <p className="ld-eyebrow">{eyebrow}</p>
        <h2 className="mt-2 text-[clamp(1.55rem,2vw,2.4rem)] font-semibold leading-[1.2] tracking-tight text-white">{title}</h2>
        {detail ? <p className="ld-copy mt-3 max-w-2xl">{detail}</p> : null}
      </div>
      {action}
    </div>
  );
}

export function ToneChip({ label, tone }: { label: string; tone: ChipTone }) {
  return <span className={`inline-flex items-center rounded-md px-2.5 py-1 text-[11px] font-semibold ${toneClass(tone)}`}>{label}</span>;
}

export function MetricCard({
  label,
  value,
  tone,
  detail,
  loading = false,
  trend,
}: {
  label: string;
  value: string;
  tone: ChipTone;
  detail?: string;
  loading?: boolean;
  trend?: "up" | "down" | "neutral";
}) {
  if (loading) {
    return (
      <div className="ld-soft-block p-3.5">
        <div className="flex items-center justify-between gap-3">
          <div className="h-4 w-20 rounded bg-white/5 ld-shimmer" />
          <div className="h-5 w-14 rounded bg-white/5 ld-shimmer" />
        </div>
        {detail ? <div className="mt-2.5 h-4 w-full rounded bg-white/5 ld-shimmer" /> : null}
      </div>
    );
  }

  return (
    <div className="ld-soft-block p-3.5 glow-border transition-all duration-200 hover:border-white/10">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] text-[color:var(--ld-text-soft)]">{label}</span>
        <div className="flex items-center gap-1.5">
          {trend && trend !== "neutral" && (
            <TrendIndicator direction={trend} />
          )}
          <ToneChip label={value} tone={tone} />
        </div>
      </div>
      {detail ? <p className="ld-copy mt-2.5">{detail}</p> : null}
    </div>
  );
}

export function TrendIndicator({ direction, size = "sm" }: { direction: "up" | "down"; size?: "sm" | "md" }) {
  const sizeClasses = size === "sm" ? "w-3 h-3" : "w-4 h-4";
  const colorClass = direction === "up" ? "text-emerald-400" : "text-rose-400";
  return (
    <svg
      className={`${sizeClasses} ${colorClass}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {direction === "up" ? (
        <path d="M12 19V5M5 12l7-7 7 7" />
      ) : (
        <path d="M12 5v14M19 12l-7 7-7-7" />
      )}
    </svg>
  );
}

export function ActionButton({
  label,
  detail,
  tone,
  onClick,
  busy,
  disabled,
  glowOnHover = true,
}: {
  label: string;
  detail?: string;
  tone: ChipTone;
  onClick?: () => void;
  busy?: boolean;
  disabled?: boolean;
  glowOnHover?: boolean;
}) {
  const glowClass = glowOnHover && !disabled ? "glow-border" : "";
  return (
    <button
      className={`ld-action ${toneClass(tone)} ${busy ? "opacity-70" : ""} ${glowClass}`}
      type="button"
      onClick={onClick}
      disabled={disabled || busy}
    >
      <span className="text-sm font-semibold">{busy ? `${label}...` : label}</span>
      {detail ? <span className="mt-1 text-left text-[11px] leading-5 opacity-80">{detail}</span> : null}
    </button>
  );
}

export function StateBlock({
  title,
  detail,
  tone = "violet",
}: {
  title: string;
  detail: string;
  tone?: ChipTone;
}) {
  return (
    <div className={`rounded-[8px] px-4 py-3.5 ${toneClass(tone)}`}>
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-2 text-[13px] leading-6 opacity-80">{detail}</div>
    </div>
  );
}

export function MarkdownPanel({ title, content }: { title: string; content: string }) {
  const text = content?.trim() || "";
  return (
    <div className="ld-surface p-4">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      {text ? (
        <div className="ld-markdown mt-3 max-h-[32rem] overflow-auto">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{text}</ReactMarkdown>
        </div>
      ) : (
        <p className="ld-copy mt-3 text-xs">(empty)</p>
      )}
    </div>
  );
}

export function OutputViewer({
  stdout,
  stderr,
}: {
  stdout?: string;
  stderr?: string;
}) {
  const text = [stdout?.trim(), stderr?.trim()].filter(Boolean).join("\n\n");
  return (
    <div className="ld-console">
      <pre className="whitespace-pre-wrap break-words text-xs leading-6 text-[color:var(--ld-console-fg)]">
        {text || "No output captured yet."}
      </pre>
    </div>
  );
}

// Status Orb - Animated status indicator with glow
export function StatusOrb({
  status,
  size = "md",
  pulse = false,
  label,
}: {
  status: "active" | "idle" | "warning" | "error";
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
  label?: string;
}) {
  const sizeMap = {
    sm: "w-2 h-2",
    md: "w-3 h-3",
    lg: "w-4 h-4",
  };

  const colorMap = {
    active: "bg-emerald-400 shadow-[0_0_10px_rgba(52,211,153,0.6)]",
    idle: "bg-zinc-500",
    warning: "bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.5)]",
    error: "bg-rose-400 shadow-[0_0_10px_rgba(251,113,133,0.5)]",
  };

  const pulseClass = pulse ? "animate-pulse" : "";

  return (
    <div className="inline-flex items-center gap-2">
      <span className={`${sizeMap[size]} rounded-full ${colorMap[status]} ${pulseClass}`} />
      {label && <span className="text-xs text-[color:var(--ld-text-soft)]">{label}</span>}
    </div>
  );
}

// Progress indicators
export function LinearProgress({
  value,
  max = 100,
  color = "violet",
  showLabel = false,
  size = "md",
}: {
  value: number;
  max?: number;
  color?: "violet" | "cyan" | "emerald" | "amber" | "rose";
  showLabel?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  const heightClass = size === "sm" ? "h-1" : size === "md" ? "h-1.5" : "h-2";

  const colorMap = {
    violet: "from-violet-900 via-violet-500 to-fuchsia-400",
    cyan: "from-cyan-900 via-cyan-500 to-sky-400",
    emerald: "from-emerald-900 via-emerald-500 to-teal-400",
    amber: "from-amber-900 via-amber-500 to-orange-400",
    rose: "from-rose-900 via-rose-500 to-pink-400",
  };

  return (
    <div className="w-full">
      {showLabel && (
        <div className="flex justify-between text-xs mb-1.5 text-[color:var(--ld-text-soft)]">
          <span>Progress</span>
          <span>{Math.round(percentage)}%</span>
        </div>
      )}
      <div className={`w-full ${heightClass} bg-black/50 rounded-full overflow-hidden border border-white/5`}>
        <div
          className={`h-full bg-gradient-to-r ${colorMap[color]} transition-all duration-500 ease-out relative`}
          style={{ width: `${percentage}%` }}
        >
          <div className="absolute inset-0 bg-white/10 animate-[shimmer_2s_infinite]" />
        </div>
      </div>
    </div>
  );
}

export function CircularProgress({
  value,
  max = 100,
  size = 48,
  strokeWidth = 4,
  color = "violet",
  label,
}: {
  value: number;
  max?: number;
  size?: number;
  strokeWidth?: number;
  color?: "violet" | "cyan" | "emerald" | "amber" | "rose";
  label?: string;
}) {
  const percentage = Math.min(100, Math.max(0, (value / max) * 100));
  const radius = (size - strokeWidth) / 2;
  const circumference = radius * 2 * Math.PI;
  const offset = circumference - (percentage / 100) * circumference;

  const colorMap = {
    violet: "#a855f7",
    cyan: "#06b6d4",
    emerald: "#10b981",
    amber: "#f59e0b",
    rose: "#f43f5e",
  };

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="rgba(255,255,255,0.1)"
          strokeWidth={strokeWidth}
          fill="transparent"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke={colorMap[color]}
          strokeWidth={strokeWidth}
          fill="transparent"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          strokeLinecap="round"
          style={{ filter: `drop-shadow(0 0 4px ${colorMap[color]})` }}
          className="transition-all duration-500 ease-out"
        />
      </svg>
      {label && (
        <span className="absolute text-xs font-semibold text-white">{label}</span>
      )}
    </div>
  );
}
