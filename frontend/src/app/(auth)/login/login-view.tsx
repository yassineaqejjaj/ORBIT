"use client";

import * as React from "react";
import Image from "next/image";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowRight, Eye, EyeOff, Lock, Mail } from "lucide-react";

import { OrbitLogo } from "@/components/brand/orbit-logo";
import { Alert } from "@/components/ui/alert";
import { isApiError } from "@/lib/api/client";
import { useLogin, useMe } from "@/lib/api/hooks";
import { cn, safeNextPath } from "@/lib/utils";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const LANG_KEY = "orbit-login-lang";

type Lang = "fr" | "en";

const COPY = {
  fr: {
    headline: "Le moteur de contexte gouverné pour vos agents IA",
    subline: "Orchestrez, structurez et activez le bon contexte pour des systèmes IA fiables.",
    poweredBy: "Powered by Devoteam",
    tagline: ["Tech for People.", "AI for Impact."],
    signIn: "Connexion",
    signUp: "Inscription",
    email: "E-mail professionnel",
    emailPlaceholder: "prenom.nom@devoteam.com",
    password: "Mot de passe",
    showPassword: "Afficher le mot de passe",
    hidePassword: "Masquer le mot de passe",
    remember: "Rester connecté",
    submit: "Connexion",
    submitting: "Connexion…",
    or: "ou continuer avec",
    soon: "Bientôt",
    googleSoon: "Connexion avec Google — bientôt disponible",
    signUpTitle: "Accès sur invitation",
    signUpText:
      "Les comptes ORBIT sont créés par l’administrateur de votre organisation, afin d’appliquer vos habilitations (C0 à C3) et vos droits sur chaque projet.",
    signUpHint: "Demandez une invitation à votre administrateur ORBIT, puis revenez vous connecter.",
    backToSignIn: "J’ai déjà un compte",
    errEmailMissing: "Saisissez votre adresse e-mail.",
    errEmailInvalid: "Adresse e-mail invalide.",
    errPasswordMissing: "Saisissez votre mot de passe.",
    errCredentials: "E-mail ou mot de passe incorrect.",
    errForbidden: "Ce compte n’est pas autorisé à se connecter.",
    errRate: "Trop de tentatives de connexion. Patientez quelques instants avant de réessayer.",
    errNetwork: "Le service ORBIT est injoignable pour le moment. Réessayez dans quelques instants.",
    errGeneric: "Connexion impossible. Réessayez.",
    langLabel: "Langue",
  },
  en: {
    headline: "The governed context engine for your AI agents",
    subline: "Orchestrate, structure and activate the right context for reliable AI systems.",
    poweredBy: "Powered by Devoteam",
    tagline: ["Tech for People.", "AI for Impact."],
    signIn: "Sign in",
    signUp: "Sign up",
    email: "Work e-mail",
    emailPlaceholder: "firstname.lastname@devoteam.com",
    password: "Password",
    showPassword: "Show password",
    hidePassword: "Hide password",
    remember: "Keep me signed in",
    submit: "Sign in",
    submitting: "Signing in…",
    or: "or continue with",
    soon: "Soon",
    googleSoon: "Sign in with Google — coming soon",
    signUpTitle: "Invitation-only access",
    signUpText:
      "ORBIT accounts are created by your organisation’s administrator so that your clearance (C0 to C3) and project rights apply from day one.",
    signUpHint: "Ask your ORBIT administrator for an invitation, then come back to sign in.",
    backToSignIn: "I already have an account",
    errEmailMissing: "Enter your e-mail address.",
    errEmailInvalid: "Invalid e-mail address.",
    errPasswordMissing: "Enter your password.",
    errCredentials: "Incorrect e-mail or password.",
    errForbidden: "This account is not allowed to sign in.",
    errRate: "Too many sign-in attempts. Please wait a moment and try again.",
    errNetwork: "The ORBIT service is unreachable right now. Please try again shortly.",
    errGeneric: "Sign-in failed. Please try again.",
    langLabel: "Language",
  },
} as const;

type Copy = (typeof COPY)[Lang];

function loginErrorMessage(error: unknown, t: Copy): string {
  if (isApiError(error)) {
    if (error.status === 401 || error.status === 400) return t.errCredentials;
    if (error.status === 403) return error.detail || t.errForbidden;
    if (error.status === 429) return t.errRate;
    if (error.isNetwork || error.isServer) return t.errNetwork;
    return error.detail || t.errGeneric;
  }
  return t.errGeneric;
}

/** Per-viewer convenience only (never required): the page renders in French when storage is unavailable. */
function useLoginLang(): [Lang, (lang: Lang) => void] {
  const [lang, setLang] = React.useState<Lang>("fr");
  React.useEffect(() => {
    try {
      const stored = window.localStorage.getItem(LANG_KEY);
      if (stored === "en" || stored === "fr") setLang(stored);
    } catch {
      /* storage blocked: keep French */
    }
  }, []);
  const update = React.useCallback((next: Lang) => {
    setLang(next);
    try {
      window.localStorage.setItem(LANG_KEY, next);
    } catch {
      /* ignore */
    }
  }, []);
  return [lang, update];
}

function LangSwitch({ lang, onChange, label }: { lang: Lang; onChange: (lang: Lang) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-full border border-border bg-surface p-1 shadow-xs">
      {(["en", "fr"] as const).map((value) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={lang === value}
          onClick={() => onChange(value)}
          className={cn(
            "h-8 min-w-11 rounded-full px-3 text-[13px] font-semibold uppercase transition-colors duration-150 motion-reduce:transition-none",
            "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
            lang === value ? "bg-foreground text-background" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {value}
        </button>
      ))}
    </div>
  );
}

type FloatingFieldProps = React.InputHTMLAttributes<HTMLInputElement> & {
  id: string;
  label: string;
  icon: React.ComponentType<{ className?: string; "aria-hidden"?: boolean }>;
  error?: string;
  trailing?: React.ReactNode;
};

const FloatingField = React.forwardRef<HTMLInputElement, FloatingFieldProps>(function FloatingField(
  { id, label, icon: Icon, error, trailing, ...input },
  ref,
) {
  const errorId = `${id}-error`;
  return (
    <div className="grid gap-1.5">
      <div
        className={cn(
          "flex items-center gap-3 rounded-[14px] border bg-surface px-4 transition-[border-color,box-shadow] duration-150",
          "focus-within:border-accent-coral/50 focus-within:ring-4 focus-within:ring-accent-coral/10",
          error ? "border-danger/60" : "border-border-strong",
        )}
      >
        <Icon className="size-5 shrink-0 text-subtle-foreground" aria-hidden />
        <div className="grid min-w-0 flex-1 py-2">
          <label htmlFor={id} className="text-[12px] font-medium text-subtle-foreground">
            {label}
          </label>
          <input
            ref={ref}
            id={id}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? errorId : undefined}
            className="h-7 w-full bg-transparent text-[15px] text-foreground outline-none placeholder:text-subtle-foreground/80"
            {...input}
          />
        </div>
        {trailing}
      </div>
      {error ? (
        <p id={errorId} className="text-[12.5px] text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
});

function GoogleMark() {
  return (
    <svg viewBox="0 0 48 48" className="size-5" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.2-.1-2.3-.4-3.5z" />
      <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3 0 5.8 1.1 7.9 3l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.2-.1-2.3-.4-3.5z" />
    </svg>
  );
}

function BrandPanel({ t }: { t: Copy }) {
  return (
    <aside className="relative hidden overflow-hidden bg-[#050106] text-white lg:flex lg:flex-col" aria-label="ORBIT">
      <Image src="/brand/login-nebula.jpg" alt="" fill priority sizes="55vw" className="object-cover" />
      <Image
        src="/brand/orbit-ring.webp"
        alt=""
        width={1100}
        height={701}
        priority
        className="pointer-events-none absolute left-[2%] top-[12%] w-[96%] max-w-none select-none motion-safe:animate-[orbit-float_9s_ease-in-out_infinite]"
      />
      <div className="relative flex h-full flex-col px-12 pb-10 pt-12 xl:px-16">
        <Image
          src="/brand/devoteam-orbit-light.png"
          alt="Devoteam | ORBIT"
          width={900}
          height={172}
          priority
          className="h-auto w-[300px] xl:w-[340px]"
        />
        <div className="mt-auto max-w-[560px]">
          <h1 className="[font-family:var(--font-brand)] text-balance text-[40px] font-medium leading-[1.08] tracking-[-0.01em] xl:text-[46px]">
            {t.headline}
          </h1>
          <p className="[font-family:var(--font-brand)] mt-4 max-w-[440px] text-[17px] leading-snug text-white/85">{t.subline}</p>
        </div>
        <div className="mt-10 flex items-end justify-between gap-6">
          <div className="grid justify-items-center gap-1">
            <Image src="/brand/devoteam-orbit-light.png" alt="" width={900} height={172} className="h-auto w-[176px]" />
            <span className="[font-family:var(--font-brand)] text-[13px] text-white/80">{t.poweredBy}</span>
          </div>
          <p className="[font-family:var(--font-brand)] text-right text-[14px] leading-snug text-white/80">
            {t.tagline[0]}
            <br />
            {t.tagline[1]}
          </p>
        </div>
      </div>
    </aside>
  );
}

export function LoginView() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const next = safeNextPath(searchParams.get("next"));
  const [lang, setLang] = useLoginLang();
  const t = COPY[lang];

  const [tab, setTab] = React.useState<"signin" | "signup">("signin");
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [remember, setRemember] = React.useState(true);
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
    if (!trimmed) errors.email = t.errEmailMissing;
    else if (!EMAIL_RE.test(trimmed)) errors.email = t.errEmailInvalid;
    if (!password) errors.password = t.errPasswordMissing;
    setFieldErrors(errors);
    if (errors.email) return emailRef.current?.focus();
    if (errors.password) return passwordRef.current?.focus();
    try {
      await login.mutateAsync({ email: trimmed, password, remember });
      setRedirecting(true);
      router.replace(next);
    } catch (error) {
      setFormError(loginErrorMessage(error, t));
      setPassword("");
      passwordRef.current?.focus();
    }
  };

  const busy = login.isPending || redirecting;
  const tabs = [
    { value: "signin" as const, label: t.signIn },
    { value: "signup" as const, label: t.signUp },
  ];

  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]" lang={lang}>
      <BrandPanel t={t} />

      <main className="relative flex flex-col bg-background">
        <div className="flex items-center justify-between px-5 pt-5 sm:px-8 sm:pt-6">
          <span className="lg:hidden">
            <OrbitLogo />
          </span>
          <span className="hidden lg:block" />
          <LangSwitch lang={lang} onChange={setLang} label={t.langLabel} />
        </div>

        <div className="flex flex-1 items-center justify-center px-5 py-10 sm:px-8">
          <div className="w-full max-w-[520px] rounded-[26px] border border-border bg-surface p-6 shadow-panel sm:p-8">
            <div role="tablist" aria-label={t.signIn} className="grid grid-cols-2 border-b border-border">
              {tabs.map((item) => (
                <button
                  key={item.value}
                  type="button"
                  role="tab"
                  id={`login-tab-${item.value}`}
                  aria-selected={tab === item.value}
                  aria-controls={`login-panel-${item.value}`}
                  onClick={() => setTab(item.value)}
                  className={cn(
                    "-mb-px h-12 border-b-2 text-[17px] transition-colors duration-150 motion-reduce:transition-none",
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    tab === item.value
                      ? "border-accent-coral font-semibold text-foreground"
                      : "border-transparent text-muted-foreground hover:text-foreground",
                  )}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {tab === "signin" ? (
              <form
                id="login-panel-signin"
                role="tabpanel"
                aria-labelledby="login-tab-signin"
                onSubmit={submit}
                noValidate
                className="mt-6 grid gap-4"
              >
                {formError ? (
                  <Alert tone="red" role="alert">
                    {formError}
                  </Alert>
                ) : null}
                <FloatingField
                  ref={emailRef}
                  id="email"
                  label={t.email}
                  icon={Mail}
                  type="email"
                  autoComplete="username"
                  inputMode="email"
                  placeholder={t.emailPlaceholder}
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  error={fieldErrors.email}
                  disabled={busy}
                  autoFocus
                />
                <FloatingField
                  ref={passwordRef}
                  id="password"
                  label={t.password}
                  icon={Lock}
                  type={showPassword ? "text" : "password"}
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  error={fieldErrors.password}
                  disabled={busy}
                  trailing={
                    <button
                      type="button"
                      onClick={() => setShowPassword((v) => !v)}
                      aria-label={showPassword ? t.hidePassword : t.showPassword}
                      aria-pressed={showPassword}
                      className="flex size-9 shrink-0 items-center justify-center rounded-full text-subtle-foreground transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {showPassword ? <EyeOff className="size-5" aria-hidden /> : <Eye className="size-5" aria-hidden />}
                    </button>
                  }
                />
                <label className="flex w-fit cursor-pointer items-center gap-3 text-[15px] text-foreground">
                  <input
                    type="checkbox"
                    checked={remember}
                    onChange={(e) => setRemember(e.target.checked)}
                    className="size-5 cursor-pointer rounded-md accent-[var(--accent-coral)]"
                  />
                  {t.remember}
                </label>
                <button
                  type="submit"
                  disabled={busy}
                  className={cn(
                    "mt-1 flex h-14 items-center justify-center gap-2 rounded-[14px] bg-primary text-[17px] font-medium text-primary-foreground transition-colors duration-150",
                    "hover:bg-primary-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
                    "disabled:cursor-not-allowed disabled:opacity-60 motion-reduce:transition-none",
                  )}
                >
                  {busy ? t.submitting : t.submit}
                  {!busy ? <ArrowRight className="size-5" aria-hidden /> : null}
                </button>

                <div className="my-2 flex items-center gap-4 text-[14px] text-muted-foreground">
                  <span className="h-px flex-1 bg-border" aria-hidden />
                  {t.or}
                  <span className="h-px flex-1 bg-border" aria-hidden />
                </div>
                <button
                  type="button"
                  disabled
                  aria-label={t.googleSoon}
                  className="flex h-14 items-center justify-center gap-3 rounded-[14px] border border-border-strong bg-surface text-[17px] font-medium text-foreground disabled:cursor-not-allowed"
                >
                  <GoogleMark />
                  Google
                  <span className="rounded-full bg-accent-soft px-2.5 py-0.5 text-[13px] font-medium text-accent-text">
                    {t.soon}
                  </span>
                </button>
              </form>
            ) : (
              <div id="login-panel-signup" role="tabpanel" aria-labelledby="login-tab-signup" className="mt-6 grid gap-3">
                <h2 className="text-[17px] font-semibold text-foreground">{t.signUpTitle}</h2>
                <p className="text-[14.5px] leading-relaxed text-muted-foreground">{t.signUpText}</p>
                <p className="text-[14.5px] leading-relaxed text-muted-foreground">{t.signUpHint}</p>
                <button
                  type="button"
                  onClick={() => setTab("signin")}
                  className="mt-2 flex h-12 items-center justify-center gap-2 rounded-[14px] border border-border-strong text-[15px] font-medium text-foreground transition-colors hover:bg-surface-2 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                >
                  {t.backToSignIn}
                  <ArrowRight className="size-4" aria-hidden />
                </button>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}
