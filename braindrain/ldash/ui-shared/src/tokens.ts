export const livingdashTokens = {
  color: {
    bg: "#0b0611",
    panel: "#141020",
    panelAlt: "#1c152a",
    border: "rgba(183, 153, 255, 0.22)",
    textPrimary: "#f5efff",
    textSecondary: "#bcaed8",
    cyan: "#22d3ee",
    emerald: "#34d399",
    amber: "#f59e0b",
    violet: "#a78bfa",
    rose: "#fb7185",
  },
  radius: {
    sm: "0.5rem",
    md: "0.875rem",
    lg: "1.25rem",
    xl: "1.75rem",
  },
  spacing: {
    xs: "0.375rem",
    sm: "0.625rem",
    md: "1rem",
    lg: "1.5rem",
    xl: "2rem",
  },
  shadow: {
    soft: "0 20px 40px -28px rgba(112, 86, 179, 0.55)",
    glow: "0 0 36px rgba(168, 85, 247, 0.25)",
  },
} as const;

export type LivingDashTokens = typeof livingdashTokens;
