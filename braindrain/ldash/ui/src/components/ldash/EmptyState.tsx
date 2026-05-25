import { motion } from "framer-motion";
import type { ChipTone } from "@/data";
import { ToneChip } from "./Primitives";

interface EmptyStateProps {
  icon?: React.ReactNode;
  title: string;
  description: string;
  action?: {
    label: string;
    onClick: () => void;
  };
  tone?: ChipTone;
  decorative?: boolean;
}

// Pre-built icon components
const EmptyStateIcons = {
  agents: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 4-6 8-6s8 2 8 6" />
      <circle cx="18" cy="10" r="2" className="opacity-40" />
    </svg>
  ),
  skills: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  ),
  plans: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 11l3 3L22 4" />
      <path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11" />
    </svg>
  ),
  commands: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <path d="M9 10l4 4-4 4" />
      <path d="M13 14h4" />
    </svg>
  ),
  git: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6" cy="6" r="3" />
      <circle cx="18" cy="18" r="3" />
      <circle cx="18" cy="6" r="3" />
      <path d="M6 9v7a3 3 0 003 3h3" />
      <path d="M9 6h9" />
    </svg>
  ),
  processes: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="3" width="20" height="8" rx="2" />
      <rect x="2" y="13" width="20" height="8" rx="2" />
      <path d="M6 7h4" />
      <path d="M6 17h4" />
    </svg>
  ),
  logs: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" />
      <path d="M14 2v6h6" />
      <path d="M16 13H8" />
      <path d="M16 17H8" />
      <path d="M10 9H8" />
    </svg>
  ),
  config: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 20a8 8 0 100-16 8 8 0 000 16z" />
      <path d="M12 14a2 2 0 100-4 2 2 0 000 4z" />
    </svg>
  ),
  primer: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
      <circle cx="12" cy="12" r="3" className="opacity-60" />
    </svg>
  ),
  telemetry: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 3v18h18" />
      <path d="M7 16l4-4 4 4 5-5" />
    </svg>
  ),
  tests: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M9 12l2 2 4-4" />
      <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  default: (
    <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16v-4" />
      <path d="M12 8h.01" />
    </svg>
  ),
};

// Decorative background pattern
function DecorativePattern() {
  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      <div className="absolute inset-0 opacity-[0.02]">
        <svg width="100%" height="100%" xmlns="http://www.w3.org/2000/svg">
          <defs>
            <pattern id="grid" width="40" height="40" patternUnits="userSpaceOnUse">
              <circle cx="20" cy="20" r="1" fill="currentColor" />
            </pattern>
          </defs>
          <rect width="100%" height="100%" fill="url(#grid)" />
        </svg>
      </div>
      {/* Ambient glow */}
      <div 
        className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-32 h-32 rounded-full opacity-10"
        style={{ background: 'radial-gradient(circle, var(--ld-brand-500), transparent 70%)' }}
      />
    </div>
  );
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  tone = "violet",
  decorative = true,
}: EmptyStateProps) {
  const iconContent = icon || EmptyStateIcons.default;
  const iconColorClass = `text-[color:var(--ld-tone-${tone}-fg)]`;

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="relative flex flex-col items-center justify-center py-12 px-6 text-center"
    >
      {decorative && <DecorativePattern />}
      
      {/* Icon container with glow */}
      <div className={`relative mb-4 p-4 rounded-2xl bg-[color:var(--ld-tone-${tone}-bg)] border border-[color:var(--ld-tone-${tone}-ring)]/30 ${iconColorClass}`}>
        <div className={`opacity-60 ${iconColorClass}`}>
          {iconContent}
        </div>
        {/* Subtle glow effect */}
        <div 
          className="absolute inset-0 rounded-2xl blur-xl opacity-30 -z-10"
          style={{ background: `var(--neon-${tone === 'violet' ? 'purple' : tone === 'cyan' ? 'cyan' : 'purple'})` }}
        />
      </div>

      {/* Title */}
      <h3 className="text-lg font-semibold text-white mb-2">
        {title}
      </h3>

      {/* Description */}
      <p className="text-sm text-[color:var(--ld-text-soft)] max-w-xs mb-4">
        {description}
      </p>

      {/* Optional action */}
      {action && (
        <button
          onClick={action.onClick}
          className="mt-2 inline-flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 hover:scale-[1.02]"
          style={{
            background: `linear-gradient(180deg, rgba(168, 85, 247, 0.15), rgba(168, 85, 247, 0.05))`,
            border: '1px solid rgba(168, 85, 247, 0.3)',
            color: 'var(--ld-brand-300)',
            boxShadow: '0 0 15px rgba(168, 85, 247, 0.1)',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.boxShadow = '0 0 20px rgba(168, 85, 247, 0.25)';
            e.currentTarget.style.borderColor = 'rgba(168, 85, 247, 0.5)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.boxShadow = '0 0 15px rgba(168, 85, 247, 0.1)';
            e.currentTarget.style.borderColor = 'rgba(168, 85, 247, 0.3)';
          }}
        >
          {action.label}
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M5 12h14M12 5l7 7-7 7" />
          </svg>
        </button>
      )}
    </motion.div>
  );
}

// Pre-configured empty states for common scenarios
export function EmptyAgentsState({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <EmptyState
      icon={EmptyStateIcons.agents}
      title="No Agents Found"
      description="No Cursor agents are currently installed. Run the primer to set up your workspace agents."
      action={onRefresh ? { label: "Refresh Workspace", onClick: onRefresh } : undefined}
      tone="cyan"
    />
  );
}

export function EmptySkillsState({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <EmptyState
      icon={EmptyStateIcons.skills}
      title="No Skills Installed"
      description="No skills are currently configured. Skills help extend agent capabilities for specific tasks."
      action={onRefresh ? { label: "Refresh Workspace", onClick: onRefresh } : undefined}
      tone="emerald"
    />
  );
}

export function EmptyPlansState({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <EmptyState
      icon={EmptyStateIcons.plans}
      title="No Plans Available"
      description="No active plans found in .cursor/plans. Create a plan to track your work."
      action={onRefresh ? { label: "Refresh Workspace", onClick: onRefresh } : undefined}
      tone="violet"
    />
  );
}

export function EmptyLogsState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.logs}
      title="No Logs Available"
      description="Observer or session logs are not available. This might indicate the observer is not running."
      tone="amber"
    />
  );
}

export function EmptyConfigState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.config}
      title="Configuration Not Loaded"
      description="The hub configuration could not be loaded. Check that config/hub_config.yaml exists."
      tone="amber"
    />
  );
}

export function EmptyPrimerState({ onRunPrimer }: { onRunPrimer?: () => void }) {
  return (
    <EmptyState
      icon={EmptyStateIcons.primer}
      title="Workspace Not Primed"
      description="This workspace hasn't been primed yet. Run prime_workspace() to set up the environment."
      action={onRunPrimer ? { label: "Run Primer", onClick: onRunPrimer } : undefined}
      tone="violet"
    />
  );
}

export function EmptyTestsState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.tests}
      title="No Tests Found"
      description="No Python tests were discovered. Add test files in the tests/ directory."
      tone="cyan"
    />
  );
}

export function EmptyCommandsState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.commands}
      title="No Commands Available"
      description="No approved commands are configured. Add commands to .braindrain/ldash/config/commands.json."
      tone="violet"
    />
  );
}

export function EmptyProcessesState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.processes}
      title="No Services Configured"
      description="No services are configured for monitoring. Add services to track their status."
      tone="amber"
    />
  );
}

export function EmptyTelemetryState() {
  return (
    <EmptyState
      icon={EmptyStateIcons.telemetry}
      title="No Telemetry Data"
      description="No telemetry events have been recorded yet. Events will appear after actions are completed."
      tone="emerald"
    />
  );
}

export function EmptyGitState({ onFetch }: { onFetch?: () => void }) {
  return (
    <EmptyState
      icon={EmptyStateIcons.git}
      title="Git Status Unavailable"
      description="Unable to retrieve git status. This may not be a git repository or git is not configured."
      action={onFetch ? { label: "Try Fetch", onClick: onFetch } : undefined}
      tone="rose"
    />
  );
}

// Loading state
export function LoadingState({ message = "Loading..." }: { message?: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-12">
      <div className="relative w-10 h-10 mb-4">
        <div className="absolute inset-0 rounded-full border-2 border-[color:var(--ld-brand-500)]/20" />
        <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-[color:var(--ld-brand-500)] animate-spin" />
      </div>
      <p className="text-sm text-[color:var(--ld-text-soft)]">{message}</p>
    </div>
  );
}

// Error state
export function ErrorState({ 
  title = "Something went wrong", 
  message,
  onRetry 
}: { 
  title?: string;
  message: string;
  onRetry?: () => void;
}) {
  return (
    <EmptyState
      icon={
        <svg className="w-12 h-12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="10" />
          <path d="M8 15l8-8M8 7l8 8" />
        </svg>
      }
      title={title}
      description={message}
      action={onRetry ? { label: "Try Again", onClick: onRetry } : undefined}
      tone="rose"
    />
  );
}
