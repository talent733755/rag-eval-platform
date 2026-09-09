export const designTokens = {
  light: {
    canvas: "#F8FAFC",
    surface: "#FFFFFF",
    sidebar: "#0F172A",
    primary: "#2563EB",
    primarySoft: "#EFF6FF",
    action: "#F97316",
    text: "#0F172A",
    textSecondary: "#475569",
    muted: "#64748B",
    border: "#E2E8F0",
    success: "#16A34A",
    warning: "#D97706",
    danger: "#DC2626",
  },
  dark: {
    canvas: "#0B1220",
    surface: "#111827",
    surfaceElevated: "#172033",
    sidebar: "#08101D",
    primary: "#60A5FA",
    action: "#F97316",
    text: "#E5E7EB",
    textSecondary: "#CBD5E1",
    muted: "#94A3B8",
    border: "#334155",
    success: "#16A34A",
    warning: "#D97706",
    danger: "#DC2626",
  },
} as const;

export type DesignTokens = typeof designTokens;
