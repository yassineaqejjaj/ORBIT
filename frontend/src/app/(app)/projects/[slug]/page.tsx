import type { Metadata } from "next";

import { OverviewView } from "@/components/overview/overview-view";

export const metadata: Metadata = { title: "Vue d’ensemble" };

export default function ProjectOverviewPage() {
  return <OverviewView />;
}
