import type { Metadata } from "next";

import { OverviewView } from "@/components/overview/overview-view";

export const metadata: Metadata = { title: "Vue projet" };

export default function ProjectOverviewPage() {
  return <OverviewView />;
}
