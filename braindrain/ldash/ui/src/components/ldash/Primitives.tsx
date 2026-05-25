import type { PropsWithChildren, ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChipTone } from "@/data";
import { toneClass } from "@/theme";

export function Panel({
  children,
  className = "",
  glow = false,
}: PropsWithChildren<{ className?: string; glow?: boolean }>) {
  return <section className={`ld-panel ${glow ? "ld-panel-glow" : ""} ${className}`.trim()}>{children}</section>;
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
}: {
  label: string;
  value: string;
  tone: ChipTone;
  detail?: string;
}) {
  return (
    <div className="ld-soft-block p-3.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] text-[color:var(--ld-text-soft)]">{label}</span>
        <ToneChip label={value} tone={tone} />
      </div>
      {detail ? <p className="ld-copy mt-2.5">{detail}</p> : null}
    </div>
  );
}

export function ActionButton({
  label,
  detail,
  tone,
  onClick,
  busy,
  disabled,
}: {
  label: string;
  detail?: string;
  tone: ChipTone;
  onClick?: () => void;
  busy?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      className={`ld-action ${toneClass(tone)} ${busy ? "opacity-70" : ""}`}
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
