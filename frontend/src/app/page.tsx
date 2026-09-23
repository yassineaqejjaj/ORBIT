import { redirect } from "next/navigation";

/** Root → projects list (the (app) layout handles authentication). */
export default function HomePage() {
  redirect("/projects");
}
