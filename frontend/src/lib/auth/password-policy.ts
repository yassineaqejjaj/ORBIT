/**
 * Client-side password policy hints, mirroring the backend policy (docs/PRODUCTION.md §1:
 * `PASSWORD_MIN_LENGTH`, default 12, plus refusal of trivial passwords). The API remains the
 * authority: these checks only guide the user before submission.
 */

export const DEFAULT_PASSWORD_MIN_LENGTH = 12;

/** Short embedded list of trivial passwords (lower-case, compared after normalization). */
const TRIVIAL_PASSWORDS: ReadonlySet<string> = new Set([
  "123456789012",
  "azertyuiop",
  "azertyuiopqs",
  "qwertyuiop",
  "qwertyuiopas",
  "motdepasse",
  "motdepasse123",
  "password",
  "password1234",
  "passwordpassword",
  "orbit-admin",
  "orbitorbit",
  "administrateur",
  "admin1234567",
  "changeme",
  "changemenow",
  "bienvenue",
  "bienvenue123",
  "soleil123456",
  "iloveyou1234",
]);

export interface PasswordRuleResult {
  id: "length" | "not_email" | "not_trivial" | "variety";
  label: string;
  ok: boolean;
}

export interface PasswordEvaluation {
  rules: PasswordRuleResult[];
  /** All rules satisfied. */
  valid: boolean;
}

function normalize(value: string): string {
  return value.normalize("NFKC").trim().toLowerCase();
}

/** True for passwords made of a single repeated character or a straight ascending/descending run. */
function isMonotonous(value: string): boolean {
  if (value.length < 2) return true;
  if (new Set(value).size <= 2) return true;
  const codes = [...value].map((c) => c.codePointAt(0) ?? 0);
  const step = (codes[1] ?? 0) - (codes[0] ?? 0);
  if (Math.abs(step) !== 1) return false;
  return codes.every((code, i) => i === 0 || code - (codes[i - 1] ?? 0) === step);
}

export function isTrivialPassword(password: string, email?: string | null): boolean {
  const p = normalize(password);
  if (!p) return true;
  if (TRIVIAL_PASSWORDS.has(p)) return true;
  if (isMonotonous(p)) return true;
  if (email) {
    const e = normalize(email);
    const local = e.split("@")[0] ?? "";
    if (p === e || (local.length >= 4 && p.includes(local) && p.length - local.length < 4)) return true;
  }
  return false;
}

/** Evaluate `password` against the policy; `email` enables the "different from the e-mail" rule. */
export function evaluatePassword(
  password: string,
  options: { minLength?: number | null; email?: string | null } = {},
): PasswordEvaluation {
  const minLength = Math.max(1, options.minLength ?? DEFAULT_PASSWORD_MIN_LENGTH);
  const length = [...password].length;
  const e = options.email ? normalize(options.email) : "";
  const rules: PasswordRuleResult[] = [
    { id: "length", label: `Au moins ${minLength} caractères`, ok: length >= minLength },
    {
      id: "variety",
      label: "Mélange de lettres et de chiffres ou symboles",
      ok: /\p{L}/u.test(password) && /[^\p{L}\s]/u.test(password),
    },
    {
      id: "not_email",
      label: "Différent de votre adresse e-mail",
      ok: !e || (normalize(password) !== e && !normalize(password).startsWith(e.split("@")[0] + "@")),
    },
    {
      id: "not_trivial",
      label: "Pas un mot de passe courant ou prévisible",
      ok: password.length > 0 && !isTrivialPassword(password, options.email),
    },
  ];
  return { rules, valid: rules.every((r) => r.ok) };
}
