/**
 * Helpers for the multi-step login (docs/PRODUCTION.md §3): `POST /auth/login` returns either the
 * signed-in `User`, an MFA challenge or a forced password change challenge.
 */
import type { LoginResult, MfaChallenge, PasswordChangeChallenge, User } from "@/lib/api/types";

export function isMfaChallenge(result: LoginResult | null | undefined): result is MfaChallenge {
  return Boolean(result && typeof result === "object" && "mfa_required" in result && result.mfa_required);
}

export function isPasswordChangeChallenge(result: LoginResult | null | undefined): result is PasswordChangeChallenge {
  return Boolean(
    result && typeof result === "object" && "password_change_required" in result && result.password_change_required,
  );
}

export function isSignedInUser(result: LoginResult | null | undefined): result is User {
  return Boolean(result && typeof result === "object" && "id" in result && "email" in result);
}
