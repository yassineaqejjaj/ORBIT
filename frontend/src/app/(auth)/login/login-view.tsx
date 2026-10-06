"use client";

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Eye, EyeOff, Fingerprint, History, Lock, Mail, ShieldCheck, Sparkles } from "lucide-react";

import { ConstellationDots, OrbitLogo, OrbitWordmark } from "@/components/brand/orbit-logo";
import { OrbitHero } from "@/components/brand/orbit-hero";
import { ThemeToggle } from "@/components/layout/theme-toggle";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { isApiError } from "@/lib/api/client";
import { useLogin, useMe } from "@/lib/api/hooks";
import { safeNextPath } from "@/lib/utils";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const FEATURES = [
  {
    icon: ShieldCheck,
    title: "Contexte gouverné",
    text: "ACL, habilitations C0–C3 et données personnelles caviardées avant chaque réponse.",
  },
  {
    icon: History,
    title: "Mémoire versionnée",
    text: "Décisions, besoins et contraintes historisés, remplacements détectés, oubli sélectif.",
  },
  {
    icon: Sparkles,
    title: "Explicabilité totale",
    text: "Ce qui a été retenu, pourquoi, d’où cela provient — et ce qui a été exclu.",
  },
] as const;

function loginErrorMessage(error: unknown): string {
  if (isApiError(error)) {
    if (error.status === 401 || error.status === 400) return "E-mail ou mot de passe incorrect.";
    if (error.status === 403) return error.detail || "Ce compte n’est pas autorisé à se connecter.";
    if (error.status === 429) return "Trop de tentatives de connexion. Patientez quelques instants avant de réessayer.";
    if (error.isNetwork || error.isServer) {
      return "Le service ORBIT est injoignable pour le moment. Vérifiez que la plateforme est démarrée puis réessayez.";
    }
    return error.detail;
  }
  return "Connexion impossible. Réessayez.";
}

export function LoginView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const rawNext = searchParams.get("next");
  const next = safeNextPath(rawNext);

  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [showPassword, setShowPassword] = React.useState(false);
  const [fieldErrors, setFieldErrors] = React.useState<{ email?: string; password?: string }>({});
  const [formError, setFormError] = React.useState<string | null>(null);
  const [redirecting, setRedirecting] = React.useState(false);

  const emailRef = React.useRef<HTMLInputElement>(null);
  const passwordRef = React.useRef<HTMLInputElement>(null);

  // Already signed in? Go straight to the destination.
  const me = useMe({ redirectOnUnauthorized: false, staleTime: 0 });
  React.useEffect(() => {
    if (me.isSuccess) {
      setRedirecting(true);
      router.replace(next);
    }
  }, [me.isSuccess, next, router]);

  const login = useLogin();

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setFormError(null);
    const errors: { email?: string; password?: string } = {};
    const trimmed = email.trim();
    if (!trimmed) errors.email = "Saisissez votre adresse e-mail.";
    else if (!EMAIL_RE.test(trimmed)) errors.email = "Adresse e-mail invalide.";
    if (!password) errors.password = "Saisissez votre mot de passe.";
    setFieldErrors(errors);
    if (errors.email) {
      emailRef.current?.focus();
      return;
    }
    if (errors.password) {
      passwordRef.current?.focus();
      return;
    }

    try {
      await login.mutateAsync({ email: trimmed, password });
      setRedirecting(true);
      router.replace(next);
    } catch (error) {
      setFormError(loginErrorMessage(error));
      setPassword("");
      passwordRef.current?.focus();
    }
  };

  const busy = login.isPending || redirecting;

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.08fr)_minmax(0,1fr)]">
      {/* Brand panel */}
      {/* Always dark: the panel scopes the NOVA dark tokens with the `dark` class. */}
      <aside className="dark relative hidden overflow-hidden bg-background text-foreground lg:flex lg:flex-col">
        <div
          className="bg-grid pointer-events-none absolute inset-0 opacity-[0.14] [mask-image:radial-gradient(ellipse_at_50%_40%,black_10%,transparent_70%)]"
          aria-hidden
        />
        <div className="pointer-events-none absolute -left-32 -top-32 size-[520px] rounded-full bg-glow opacity-60 blur-3xl" aria-hidden />
        <div className="pointer-events-none absolute -bottom-40 right-0 size-[420px] rounded-full bg-violet-500/10 blur-3xl" aria-hidden />

        <div className="relative grid justify-items-start gap-1.5 px-10 pt-10 leading-none">
          <OrbitWordmark height={30} tone="on-dark" />
          <span className="text-[11px] font-medium tracking-wide text-muted-foreground">Contexte & mémoire pour agents IA</span>
        </div>

        <div className="relative flex flex-1 flex-col justify-center px-10 py-8 xl:px-16">
          <div className="mx-auto w-full max-w-xl">
            <OrbitHero className="mx-auto max-h-[34vh] max-w-lg" />
            <h2 className="mt-2 text-balance text-3xl font-semibold leading-[1.1] tracking-tight text-foreground xl:text-[36px]">
              Le bon contexte, au bon agent, au bon moment.
            </h2>
            <p className="mt-3 max-w-lg text-[15px] leading-relaxed text-muted-foreground">
              ORBIT sélectionne pour chaque agent les informations utiles à sa tâche selon leur pertinence, leur
              fraîcheur, leur provenance et les droits d’accès.
            </p>
            <ul className="mt-8 grid gap-4">
              {FEATURES.map(({ icon: Icon, title, text }) => (
                <li key={title} className="flex items-start gap-3">
                  <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-lg border border-border-strong bg-surface-2 text-accent-text">
                    <Icon className="size-4" aria-hidden />
                  </span>
                  <span className="grid gap-0.5">
                    <span className="text-sm font-medium text-foreground">{title}</span>
                    <span className="text-[13px] leading-relaxed text-muted-foreground">{text}</span>
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <div className="relative flex items-center justify-between px-10 pb-8 text-xs text-subtle-foreground">
          <span className="flex items-center gap-2">
            <ConstellationDots />
            <span>
              <span className="text-muted-foreground">NOVA Core</span> · <span className="text-accent-text">ORBIT</span> ·{" "}
              <span className="text-muted-foreground">FORGE</span>
            </span>
          </span>
          <span>Devoteam — Programme NOVA</span>
        </div>
      </aside>

      {/* Form panel */}
      <main className="relative flex flex-col bg-background">
        <div className="flex items-center justify-between px-5 pt-5 sm:px-8 sm:pt-6">
          <span className="lg:hidden">
            <OrbitLogo />
          </span>
          <span className="hidden lg:block" />
          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8">
          <div className="w-full max-w-[380px]">
            <div className="grid gap-2">
              <span className="flex size-11 items-center justify-center rounded-xl border border-border bg-card text-brand shadow-panel">
                <Fingerprint className="size-5" aria-hidden />
              </span>
              <h1 className="mt-3 text-[28px] font-semibold leading-tight tracking-tight">Connexion à ORBIT</h1>
              <p className="text-sm leading-relaxed text-muted-foreground">
                Accédez à la plateforme de contexte et de mémoire de vos agents IA.
              </p>
            </div>

            {rawNext && !formError ? (
              <Alert tone="blue" className="mt-6" icon={<Lock aria-hidden />}>
                Connectez-vous pour accéder à la page demandée.
              </Alert>
            ) : null}

            {formError ? (
              <Alert id="login-error" tone="red" className="mt-6" title="Connexion refusée">
                {formError}
              </Alert>
            ) : null}

            <form onSubmit={submit} noValidate className="mt-6 grid gap-4" aria-describedby={formError ? "login-error" : undefined}>
              <Field id="login-email" label="Adresse e-mail" error={fieldErrors.email}>
                <Input
                  ref={emailRef}
                  id="login-email"
                  name="email"
                  type="email"
                  inputMode="email"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck={false}
                  autoFocus
                  size="lg"
                  placeholder="prenom.nom@entreprise.fr"
                  leftIcon={<Mail aria-hidden />}
                  value={email}
                  onChange={(e) => {
                    setEmail(e.target.value);
                    if (fieldErrors.email) setFieldErrors((p) => ({ ...p, email: undefined }));
                  }}
                  invalid={Boolean(fieldErrors.email)}
                  aria-describedby={fieldDescribedBy("login-email", { error: fieldErrors.email })}
                  disabled={busy}
                  required
                />
              </Field>

              <Field id="login-password" label="Mot de passe" error={fieldErrors.password}>
                <Input
                  ref={passwordRef}
                  id="login-password"
                  name="password"
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  size="lg"
                  placeholder="••••••••••"
                  leftIcon={<Lock aria-hidden />}
                  value={password}
                  onChange={(e) => {
                    setPassword(e.target.value);
                    if (fieldErrors.password) setFieldErrors((p) => ({ ...p, password: undefined }));
                  }}
                  invalid={Boolean(fieldErrors.password)}
                  aria-describedby={fieldDescribedBy("login-password", { error: fieldErrors.password })}
                  disabled={busy}
                  required
                  rightSlot={
                    <button
                      type="button"
                      onClick={() => setShowPassword((s) => !s)}
                      className="flex size-7 items-center justify-center rounded-md text-subtle-foreground transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
                      aria-label={showPassword ? "Masquer le mot de passe" : "Afficher le mot de passe"}
                      aria-pressed={showPassword}
                    >
                      {showPassword ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
                    </button>
                  }
                />
              </Field>

              <Button type="submit" size="lg" className="mt-2 w-full" loading={busy} rightIcon={!busy ? <ArrowRight aria-hidden /> : undefined}>
                {redirecting ? "Redirection…" : "Se connecter"}
              </Button>
            </form>

            <p className="mt-8 flex items-start gap-2 text-xs leading-relaxed text-subtle-foreground">
              <ShieldCheck className="mt-px size-3.5 shrink-0" aria-hidden />
              Accès réservé aux collaborateurs habilités. Chaque connexion et chaque contexte servi sont journalisés
              dans l’audit.
            </p>
          </div>
        </div>

        <div className="px-5 pb-5 text-center text-[11px] text-subtle-foreground sm:px-8 lg:hidden">
          <span className="inline-flex items-center gap-2">
            <ConstellationDots /> Programme NOVA · Devoteam
          </span>
        </div>
      </main>
    </div>
  );
}
