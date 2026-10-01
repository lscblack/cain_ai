import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Intelligence-dark palette (sourced from CSS custom properties).
        base: "var(--kai-bg)",
        panel: "var(--kai-panel)",
        "panel-2": "var(--kai-panel-2)",
        line: "var(--kai-border)",
        accent: "var(--kai-accent)",
        verified: "var(--kai-verified)",
        warn: "var(--kai-warn)",
        ink: "var(--kai-text)",
        muted: "var(--kai-muted)",
      },
      fontFamily: {
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      boxShadow: {
        glow: "0 0 0 1px var(--kai-border), 0 8px 30px rgba(0,0,0,0.5)",
      },
    },
  },
  plugins: [],
} satisfies Config;
