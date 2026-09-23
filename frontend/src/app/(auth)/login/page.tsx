import type { Metadata } from "next";
import { Suspense } from "react";

import { LoginView } from "./login-view";

export const metadata: Metadata = { title: "Connexion" };

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginView />
    </Suspense>
  );
}
