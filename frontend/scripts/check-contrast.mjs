#!/usr/bin/env node
/**
 * WCAG contrast check of the NOVA text tokens (src/app/globals.css), light and dark.
 * Usage: node scripts/check-contrast.mjs   (exits 1 if a text pair is below 4.5:1)
 */
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/app/globals.css", import.meta.url), "utf8");
const block = (selector) => css.slice(css.indexOf(`${selector} {`), css.indexOf("}", css.indexOf(`${selector} {`)));
const hexTokens = (text) =>
  Object.fromEntries([...text.matchAll(/--([\w-]+):\s*(#[0-9a-f]{6})\b/gi)].map((m) => [m[1], m[2]]));

const light = hexTokens(block(":root"));
const darkOwn = hexTokens(block(".dark"));
const dark = { ...light, ...darkOwn };

const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
const lum = (c) => {
  const [r, g, b] = c.map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
/** `fg` at `alpha` over `bg` (status tints). */
const mix = (fg, bg, alpha) => rgb(fg).map((v, i) => Math.round(v * alpha + rgb(bg)[i] * (1 - alpha)));
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
};

const PAIRS = [
  ["text", "background"],
  ["text-muted", "background"],
  ["text-muted", "surface-2"],
  ["text-subtle", "background"],
  ["text-subtle", "surface"],
  ["text-subtle", "surface-2"],
  ["accent-text", "background"],
  ["accent-text", "surface"],
  ["accent-text", "accent-soft", { soft: true }],
  ["primary-foreground", "primary"],
  ["primary-foreground", "primary-hover"],
  ["success", "surface", { tint: 0.12 }],
  ["warning", "surface", { tint: 0.12 }],
  ["destructive", "surface", { tint: 0.12 }],
  ["info", "surface"],
];

let failed = false;
for (const [name, theme] of [["light", light], ["dark", dark]]) {
  console.log(`\n${name}`);
  for (const [fg, bg, opts = {}] of PAIRS) {
    let bgColor = rgb(theme[bg] ?? "#000000");
    let label = `${fg} on ${bg}`;
    if (opts.tint) {
      bgColor = mix(theme[fg], theme[bg], opts.tint);
      label = `${fg} on ${fg}/${opts.tint * 100}% over ${bg}`;
    } else if (opts.soft && theme === dark && !darkOwn[bg]) {
      bgColor = mix(theme["accent-coral"], theme.surface, 0.14); // dark accent-soft is rgb(248 72 94 / 0.14)
      label = `${fg} on accent-soft (14 % over surface)`;
    }
    const r = ratio(rgb(theme[fg]), bgColor);
    if (r < 4.5) failed = true;
    console.log(`  ${r >= 4.5 ? "AA " : "FAIL"} ${r.toFixed(2).padStart(5)}:1  ${label}`);
  }
}
process.exit(failed ? 1 : 0);
