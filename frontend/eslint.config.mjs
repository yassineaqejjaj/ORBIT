import { dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { FlatCompat } from "@eslint/eslintrc";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({ baseDirectory: __dirname });

const eslintConfig = [
  {
    ignores: ["node_modules/**", ".next/**", "out/**", "build/**", "next-env.d.ts"],
  },
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/consistent-type-imports": ["error", { fixStyle: "inline-type-imports" }],
      "react/jsx-no-target-blank": "error",
      "no-console": ["warn", { allow: ["warn", "error"] }],
      // Fonts are self-hosted (src/lib/fonts.ts): next/font/google would make `next build` need the network.
      "no-restricted-imports": [
        "error",
        { paths: [{ name: "next/font/google", message: "Self-host the font with next/font/local (src/lib/fonts.ts)." }] },
      ],
    },
  },
];

export default eslintConfig;
