import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: "var(--color-canvas)",
        surface: "var(--color-surface)",
        "surface-elevated": "var(--color-surface-elevated)",
        sidebar: "var(--color-sidebar)",
        primary: "var(--color-primary)",
        "primary-soft": "var(--color-primary-soft)",
        action: "var(--color-action)",
        text: "var(--color-text)",
        "text-secondary": "var(--color-text-secondary)",
        muted: "var(--color-text-muted)",
        border: "var(--color-border)",
        success: "var(--color-success)",
        "success-foreground": "var(--color-success-foreground)",
        warning: "var(--color-warning)",
        "warning-foreground": "var(--color-warning-foreground)",
        danger: "var(--color-danger)",
        "danger-foreground": "var(--color-danger-foreground)",
      },
      fontFamily: {
        sans: ["var(--font-ui)"],
        mono: ["var(--font-mono)"],
      },
      spacing: {
        sidebar: "15rem",
      },
    },
  },
  plugins: [],
};

export default config;
