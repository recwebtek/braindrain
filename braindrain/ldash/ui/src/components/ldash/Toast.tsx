import { motion, AnimatePresence } from "framer-motion";
import { createContext, useContext, useState, useCallback, type ReactNode, useEffect } from "react";

// Toast types
type ToastType = "success" | "error" | "info" | "warning" | "action";

interface Toast {
  id: string;
  type: ToastType;
  title: string;
  message?: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

// Toast Context
interface ToastContextValue {
  toasts: Toast[];
  addToast: (toast: Omit<Toast, "id">) => void;
  removeToast: (id: string) => void;
  success: (title: string, message?: string) => void;
  error: (title: string, message?: string) => void;
  info: (title: string, message?: string) => void;
  warning: (title: string, message?: string) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within ToastProvider");
  }
  return context;
}

// Toast Provider
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback((toast: Omit<Toast, "id">) => {
    const id = `toast-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
    const newToast: Toast = { ...toast, id };
    setToasts((prev) => [...prev, newToast]);

    // Auto-dismiss if duration is set
    if (toast.duration && toast.duration > 0) {
      setTimeout(() => removeToast(id), toast.duration);
    }
  }, [removeToast]);

  // Helper methods
  const success = useCallback((title: string, message?: string) => {
    addToast({ type: "success", title, message, duration: 4000 });
  }, [addToast]);

  const error = useCallback((title: string, message?: string) => {
    addToast({ type: "error", title, message, duration: 6000 });
  }, [addToast]);

  const info = useCallback((title: string, message?: string) => {
    addToast({ type: "info", title, message, duration: 4000 });
  }, [addToast]);

  const warning = useCallback((title: string, message?: string) => {
    addToast({ type: "warning", title, message, duration: 5000 });
  }, [addToast]);

  return (
    <ToastContext.Provider value={{ toasts, addToast, removeToast, success, error, info, warning }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={removeToast} />
    </ToastContext.Provider>
  );
}

// Toast Icon component
function ToastIcon({ type }: { type: ToastType }) {
  const iconClasses = "w-5 h-5";

  switch (type) {
    case "success":
      return (
        <svg className={iconClasses} viewBox="0 0 24 24" fill="none" stroke="#10b981" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M9 12l2 2 4-4" />
        </svg>
      );
    case "error":
      return (
        <svg className={iconClasses} viewBox="0 0 24 24" fill="none" stroke="#f43f5e" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M15 9l-6 6M9 9l6 6" />
        </svg>
      );
    case "warning":
      return (
        <svg className={iconClasses} viewBox="0 0 24 24" fill="none" stroke="#f59e0b" strokeWidth="2">
          <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
          <line x1="12" y1="9" x2="12" y2="13" />
          <line x1="12" y1="17" x2="12.01" y2="17" />
        </svg>
      );
    case "action":
      return (
        <svg className={iconClasses} viewBox="0 0 24 24" fill="none" stroke="#a855f7" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <path d="M12 8v8M8 12h8" />
        </svg>
      );
    default:
      return (
        <svg className={iconClasses} viewBox="0 0 24 24" fill="none" stroke="#06b6d4" strokeWidth="2">
          <circle cx="12" cy="12" r="10" />
          <line x1="12" y1="16" x2="12" y2="12" />
          <line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
      );
  }
}

// Individual Toast component
function ToastItem({
  toast,
  onDismiss,
}: {
  toast: Toast;
  onDismiss: (id: string) => void;
}) {
  // Color scheme based on type
  const colorSchemes = {
    success: {
      border: "border-emerald-500/30",
      bg: "bg-emerald-950/30",
      iconBg: "bg-emerald-500/15",
      shadow: "shadow-[0_0_15px_rgba(16,185,129,0.15)]",
    },
    error: {
      border: "border-rose-500/30",
      bg: "bg-rose-950/30",
      iconBg: "bg-rose-500/15",
      shadow: "shadow-[0_0_15px_rgba(244,63,94,0.15)]",
    },
    warning: {
      border: "border-amber-500/30",
      bg: "bg-amber-950/30",
      iconBg: "bg-amber-500/15",
      shadow: "shadow-[0_0_15px_rgba(245,158,11,0.15)]",
    },
    info: {
      border: "border-cyan-500/30",
      bg: "bg-cyan-950/30",
      iconBg: "bg-cyan-500/15",
      shadow: "shadow-[0_0_15px_rgba(6,182,212,0.15)]",
    },
    action: {
      border: "border-[color:var(--ld-brand-500)]/30",
      bg: "bg-[color:var(--ld-brand-950)]/30",
      iconBg: "bg-[color:var(--ld-brand-500)]/15",
      shadow: "shadow-[0_0_15px_rgba(168,85,247,0.2)]",
    },
  };

  const colors = colorSchemes[toast.type];
  const hasDuration = toast.duration && toast.duration > 0;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: -20, scale: 0.95 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, x: 100, scale: 0.95 }}
      transition={{ duration: 0.3, ease: [0.4, 0, 0.2, 1] }}
      className={`relative flex items-start gap-3 p-4 rounded-xl border ${colors.border} ${colors.bg} ${colors.shadow} backdrop-blur-sm min-w-[320px] max-w-[440px]`}
    >
      {/* Icon */}
      <div className={`flex-shrink-0 w-10 h-10 rounded-lg ${colors.iconBg} flex items-center justify-center`}>
        <ToastIcon type={toast.type} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <h4 className="font-semibold text-sm text-white">{toast.title}</h4>
        {toast.message && (
          <p className="mt-1 text-xs text-[color:var(--ld-text-soft)] leading-relaxed">{toast.message}</p>
        )}
        {toast.action && (
          <button
            onClick={() => {
              toast.action?.onClick();
              onDismiss(toast.id);
            }}
            className="mt-2 text-xs font-medium text-[color:var(--ld-brand-400)] hover:text-[color:var(--ld-brand-300)] transition-colors"
          >
            {toast.action.label} →
          </button>
        )}
      </div>

      {/* Close button */}
      <button
        onClick={() => onDismiss(toast.id)}
        className="flex-shrink-0 p-1 rounded-md text-[color:var(--ld-text-muted)] hover:text-white hover:bg-white/10 transition-colors"
      >
        <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>

      {/* Progress bar for auto-dismiss */}
      {hasDuration && (
        <motion.div
          className="absolute bottom-0 left-0 right-0 h-0.5 bg-white/20 rounded-b-xl overflow-hidden"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.3 }}
        >
          <motion.div
            className="h-full bg-white/40"
            initial={{ width: "100%" }}
            animate={{ width: "0%" }}
            transition={{ duration: (toast.duration || 4000) / 1000, ease: "linear" }}
          />
        </motion.div>
      )}
    </motion.div>
  );
}

// Toast Container component
function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  return (
    <div className="fixed top-4 right-4 z-[100] flex flex-col gap-3 pointer-events-none">
      <AnimatePresence mode="popLayout">
        {toasts.map((toast) => (
          <div key={toast.id} className="pointer-events-auto">
            <ToastItem toast={toast} onDismiss={onDismiss} />
          </div>
        ))}
      </AnimatePresence>
    </div>
  );
}

// Hook for integration with mutations/actions
export function useActionToasts() {
  const { success, error, info } = useToast();

  const showCommandResult = useCallback((
    commandName: string,
    status: "success" | "error",
    message?: string
  ) => {
    if (status === "success") {
      success(`${commandName} completed`, message || "The command executed successfully.");
    } else {
      error(`${commandName} failed`, message || "The command encountered an error.");
    }
  }, [success, error]);

  const showGitAction = useCallback((
    action: "fetch" | "pull" | "push",
    status: "success" | "error"
  ) => {
    const actionLabels = {
      fetch: "Git fetch",
      pull: "Git pull",
      push: "Git push",
    };

    if (status === "success") {
      success(`${actionLabels[action]} completed`, `Repository is now up to date.`);
    } else {
      error(`${actionLabels[action]} failed`, `Please check your connection and try again.`);
    }
  }, [success, error]);

  const showProcessAction = useCallback((
    serviceName: string,
    action: "start" | "stop" | "open",
    status: "success" | "error"
  ) => {
    const actionLabels = {
      start: "started",
      stop: "stopped",
      open: "opened",
    };

    if (status === "success") {
      success(`${serviceName} ${actionLabels[action]}`, `The service has been ${actionLabels[action]}.`);
    } else {
      error(`Failed to ${action} ${serviceName}`, `Please check the service configuration.`);
    }
  }, [success, error]);

  const showRefresh = useCallback((status: "success" | "error") => {
    if (status === "success") {
      info("Workspace refreshed", "All data has been updated.");
    } else {
      error("Refresh failed", "Unable to update workspace data.");
    }
  }, [info, error]);

  return {
    showCommandResult,
    showGitAction,
    showProcessAction,
    showRefresh,
  };
}
