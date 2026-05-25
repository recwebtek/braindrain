import { motion, AnimatePresence } from "framer-motion";
import { useEffect, useState, useCallback, createContext, useContext, type ReactNode } from "react";

// Keyboard shortcut definition
interface Shortcut {
  key: string;
  ctrl?: boolean;
  meta?: boolean;
  alt?: boolean;
  shift?: boolean;
  description: string;
  scope?: "global" | "local";
  action: () => void;
}

// Context for keyboard shortcut handling
interface KeyboardContextValue {
  registerShortcut: (shortcut: Shortcut) => () => void;
  isHelpOpen: boolean;
  toggleHelp: () => void;
  shortcuts: Shortcut[];
}

const KeyboardContext = createContext<KeyboardContextValue | undefined>(undefined);

export function useKeyboard() {
  const context = useContext(KeyboardContext);
  if (!context) {
    throw new Error("useKeyboard must be used within KeyboardProvider");
  }
  return context;
}

// Keyboard Provider
export function KeyboardProvider({ children }: { children: ReactNode }) {
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
  const [isHelpOpen, setIsHelpOpen] = useState(false);

  const toggleHelp = useCallback(() => {
    setIsHelpOpen(prev => !prev);
  }, []);

  // Register global shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Skip if input is focused
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLTextAreaElement ||
        e.target instanceof HTMLSelectElement
      ) {
        // Allow Cmd+K even in inputs
        if (!(e.metaKey && e.key === "k")) return;
      }

      // Cmd+K to toggle help
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        toggleHelp();
        return;
      }

      if (e.key === "?" && !e.metaKey && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        toggleHelp();
        return;
      }

      if (e.key === "Escape" && isHelpOpen) {
        e.preventDefault();
        setIsHelpOpen(false);
      }

      // Check registered shortcuts
      shortcuts.forEach(shortcut => {
        const keyMatch = e.key.toLowerCase() === shortcut.key.toLowerCase();
        const ctrlMatch = !!shortcut.ctrl === e.ctrlKey;
        const metaMatch = !!shortcut.meta === e.metaKey;
        const altMatch = !!shortcut.alt === e.altKey;
        const shiftMatch = !!shortcut.shift === e.shiftKey;

        if (keyMatch && ctrlMatch && metaMatch && altMatch && shiftMatch) {
          e.preventDefault();
          shortcut.action();
        }
      });
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [shortcuts, toggleHelp, isHelpOpen]);

  const registerShortcut = useCallback((shortcut: Shortcut) => {
    setShortcuts(prev => [...prev, shortcut]);
    return () => {
      setShortcuts(prev => prev.filter(s => s !== shortcut));
    };
  }, []);

  return (
    <KeyboardContext.Provider value={{ registerShortcut, isHelpOpen, toggleHelp, shortcuts }}>
      {children}
      <ShortcutsHelpOverlay isOpen={isHelpOpen} onClose={() => setIsHelpOpen(false)} shortcuts={shortcuts} />
    </KeyboardContext.Provider>
  );
}

// Shortcuts Help Overlay
function ShortcutsHelpOverlay({
  isOpen,
  onClose,
  shortcuts,
}: {
  isOpen: boolean;
  onClose: () => void;
  shortcuts: Shortcut[];
}) {
  // Default app shortcuts
  const defaultShortcuts: Array<{ keys: string[]; description: string }> = [
    { keys: ["⌘", "K"], description: "Toggle command palette / shortcuts" },
    { keys: ["Esc"], description: "Close overlays and modals" },
    { keys: ["1"], description: "Overview tab" },
    { keys: ["2"], description: "Commands tab" },
    { keys: ["3"], description: "Git tab" },
    { keys: ["4"], description: "Processes tab" },
    { keys: ["5"], description: "Telemetry tab" },
    { keys: ["R"], description: "Refresh workspace data" },
  ];

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            onClick={onClose}
            className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[90]"
          />

          {/* Modal */}
          <motion.div
            initial={{ opacity: 0, scale: 0.95, y: 20 }}
            animate={{ opacity: 1, scale: 1, y: 0 }}
            exit={{ opacity: 0, scale: 0.95, y: 20 }}
            transition={{ duration: 0.2, ease: [0.4, 0, 0.2, 1] }}
            className="fixed inset-0 flex items-center justify-center z-[95] p-4"
          >
            <div className="w-full max-w-2xl max-h-[80vh] overflow-auto ld-panel ld-panel-glow p-6">
              {/* Header */}
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-semibold text-white flex items-center gap-2">
                    <svg className="w-5 h-5 text-[color:var(--ld-brand-400)]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <rect x="3" y="3" width="18" height="18" rx="2" />
                      <path d="M9 3v18M15 3v18" />
                    </svg>
                    Keyboard Shortcuts
                  </h2>
                  <p className="text-sm text-[color:var(--ld-text-muted)] mt-1">
                    Quick navigation and actions
                  </p>
                </div>
                <button
                  onClick={onClose}
                  className="p-2 rounded-lg text-[color:var(--ld-text-muted)] hover:text-white hover:bg-white/10 transition-colors"
                >
                  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M18 6L6 18M6 6l12 12" />
                  </svg>
                </button>
              </div>

              {/* Search input */}
              <div className="relative mb-6">
                <svg
                  className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[color:var(--ld-text-muted)]"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                >
                  <circle cx="11" cy="11" r="8" />
                  <path d="M21 21l-4.35-4.35" />
                </svg>
                <input
                  type="text"
                  placeholder="Search shortcuts..."
                  className="w-full pl-10 pr-4 py-2.5 bg-black/40 border border-white/10 rounded-lg text-sm text-white placeholder:text-[color:var(--ld-text-muted)] focus:border-[color:var(--ld-brand-500)]/50 focus:outline-none transition-colors"
                />
                <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[color:var(--ld-text-muted)] bg-white/10 px-1.5 py-0.5 rounded">
                  ESC to close
                </span>
              </div>

              {/* Shortcuts Grid */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Navigation Section */}
                <div className="space-y-3">
                  <h3 className="text-xs font-semibold text-[color:var(--ld-brand-400)] uppercase tracking-wider">
                    Navigation
                  </h3>
                  <div className="space-y-2">
                    {defaultShortcuts.slice(2, 6).map((shortcut, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03] border border-white/5"
                      >
                        <span className="text-sm text-[color:var(--ld-text-soft)]">{shortcut.description}</span>
                        <div className="flex items-center gap-1">
                          {shortcut.keys.map((key, j) => (
                            <kbd
                              key={j}
                              className="px-2 py-0.5 text-xs font-mono bg-black/50 border border-white/10 rounded text-white min-w-[24px] text-center"
                            >
                              {key}
                            </kbd>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Actions Section */}
                <div className="space-y-3">
                  <h3 className="text-xs font-semibold text-[color:var(--ld-brand-400)] uppercase tracking-wider">
                    Actions
                  </h3>
                  <div className="space-y-2">
                    {defaultShortcuts.slice(6).map((shortcut, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03] border border-white/5"
                      >
                        <span className="text-sm text-[color:var(--ld-text-soft)]">{shortcut.description}</span>
                        <div className="flex items-center gap-1">
                          {shortcut.keys.map((key, j) => (
                            <kbd
                              key={j}
                              className="px-2 py-0.5 text-xs font-mono bg-black/50 border border-white/10 rounded text-white min-w-[24px] text-center"
                            >
                              {key}
                            </kbd>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* System Section */}
                <div className="space-y-3 md:col-span-2">
                  <h3 className="text-xs font-semibold text-[color:var(--ld-brand-400)] uppercase tracking-wider">
                    System
                  </h3>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                    {defaultShortcuts.slice(0, 2).map((shortcut, i) => (
                      <div
                        key={i}
                        className="flex items-center justify-between p-2.5 rounded-lg bg-white/[0.03] border border-white/5"
                      >
                        <span className="text-sm text-[color:var(--ld-text-soft)]">{shortcut.description}</span>
                        <div className="flex items-center gap-1">
                          {shortcut.keys.map((key, j) => (
                            <kbd
                              key={j}
                              className="px-2 py-0.5 text-xs font-mono bg-black/50 border border-white/10 rounded text-white min-w-[24px] text-center"
                            >
                              {key}
                            </kbd>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* Footer */}
              <div className="mt-6 pt-4 border-t border-white/10 flex items-center justify-between text-xs text-[color:var(--ld-text-muted)]">
                <span>Press <kbd className="px-1.5 py-0.5 bg-black/50 border border-white/10 rounded">?</kbd> anytime to show this help</span>
                <span className="text-[color:var(--ld-brand-400)]">LivingDash v1.0</span>
              </div>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}

// Quick command palette button
export function CommandPaletteButton({ onClick }: { onClick?: () => void }) {
  const { toggleHelp } = useKeyboard();

  return (
    <button
      onClick={onClick || toggleHelp}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/[0.05] border border-white/10 text-[color:var(--ld-text-soft)] text-xs hover:bg-white/10 hover:text-white transition-colors"
    >
      <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="11" cy="11" r="8" />
        <path d="M21 21l-4.35-4.35" />
      </svg>
      <span>Command Palette</span>
      <span className="flex items-center gap-0.5">
        <kbd className="px-1 py-0.5 bg-black/40 border border-white/10 rounded text-[10px]">⌘</kbd>
        <kbd className="px-1 py-0.5 bg-black/40 border border-white/10 rounded text-[10px]">K</kbd>
      </span>
    </button>
  );
}
