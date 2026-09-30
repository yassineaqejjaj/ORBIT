/**
 * French, user-facing messages for authentication errors (login, MFA, forced password change,
 * invitation). Lockout and rate limiting include the retry delay when the API provides it.
 */
import { formatRetryDelay, isApiError } from "@/lib/api/client";

export type AuthStep = "credentials" | "mfa" | "password_change" | "invitation";

/** API error codes with a dedicated message (backend `{detail, code}`). */
const CODE_MESSAGES: Record<string, string> = {
  invalid_credentials: "E-mail ou mot de passe incorrect.",
  account_disabled: "Ce compte est désactivé. Contactez votre administrateur ORBIT.",
  account_inactive: "Ce compte est désactivé. Contactez votre administrateur ORBIT.",
  local_login_disabled: "La connexion par mot de passe est désactivée : utilisez l'authentification SSO de votre entreprise.",
  mfa_invalid: "Code de vérification incorrect ou expiré.",
  mfa_token_expired: "L'étape de vérification a expiré. Reconnectez-vous.",
  change_token_expired: "Le délai de changement du mot de passe a expiré. Reconnectez-vous.",
  weak_password: "Ce mot de passe ne respecte pas la politique de sécurité.",
  password_policy: "Ce mot de passe ne respecte pas la politique de sécurité.",
  invitation_invalid: "Cette invitation est invalide, a expiré ou a déjà été utilisée.",
  invitation_expired: "Cette invitation a expiré. Demandez-en une nouvelle à votre administrateur.",
};

/** Seconds until retry for a lockout / rate-limit error, if known. */
export function retryAfterOf(error: unknown): number | null {
  if (!isApiError(error)) return null;
  if (error.status !== 429 && error.status !== 423 && error.code !== "account_locked") return null;
  return error.retryAfter;
}

export function authErrorMessage(error: unknown, step: AuthStep = "credentials"): string {
  if (!isApiError(error)) return "Opération impossible. Réessayez.";
  if (error.isNetwork || error.isServer) {
    return "Le service ORBIT est injoignable pour le moment. Vérifiez que la plateforme est démarrée puis réessayez.";
  }
  if (error.status === 429 || error.status === 423 || error.code === "account_locked") {
    const wait = error.retryAfter && error.retryAfter > 0 ? ` Réessayez dans ${formatRetryDelay(error.retryAfter)}.` : " Patientez quelques instants avant de réessayer.";
    return error.code === "account_locked" || error.status === 423
      ? `Compte temporairement verrouillé après plusieurs échecs.${wait}`
      : `Trop de tentatives.${wait}`;
  }
  const byCode = CODE_MESSAGES[error.code];
  if (byCode) {
    // Keep the server's detail for policy errors: it states which rule failed.
    if ((error.code === "weak_password" || error.code === "password_policy") && error.detail) return error.detail;
    return byCode;
  }
  if (step === "credentials" && (error.status === 401 || error.status === 400)) return CODE_MESSAGES.invalid_credentials!;
  if (step === "mfa" && (error.status === 401 || error.status === 400)) return CODE_MESSAGES.mfa_invalid!;
  if (step === "invitation" && (error.status === 404 || error.status === 410)) return CODE_MESSAGES.invitation_invalid!;
  if (error.status === 403) return error.detail || "Ce compte n'est pas autorisé à se connecter.";
  return error.detail || "Opération impossible. Réessayez.";
}
