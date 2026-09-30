import animate from "tailwindcss-animate";
import typography from "@tailwindcss/typography";
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}", "../../vendor/nanobot/webui/src/components/**/*.{ts,tsx}"],
  theme: { extend: {
    colors: Object.fromEntries(["background", "foreground", "border", "input", "ring", "brand", "muted", "accent", "primary", "secondary", "popover", "card", "destructive"].map(k =>
      [k, { DEFAULT: `hsl(var(--${k}))`, foreground: `hsl(var(--${k}-foreground))` }])),
    borderRadius: { lg: "var(--radius)", md: "calc(var(--radius) - 2px)", sm: "calc(var(--radius) - 4px)" },
  } },
  plugins: [animate, typography],
};
