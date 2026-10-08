"use client";

import { Bot, Layers, Lock, Plug, ScrollText, Settings, ShieldCheck, SlidersHorizontal, Users, Webhook } from "lucide-react";

import { RoleBadge } from "@/components/domain/enum-badge";
import { useUrlParams } from "@/components/sources/use-url-params";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useCurrentProject } from "@/hooks/use-current-project";
import { useAgents, useMembers } from "@/lib/api/hooks";
import { AgentsPanel } from "./agents-panel";
import { AuditPanel } from "./audit-panel";
import { CompliancePanel } from "./compliance-panel";
import { ContextProfilesPanel } from "./context-profiles-panel";
import { McpPanel } from "./mcp-panel";
import { MembersPanel } from "./members-panel";
import { ProjectSettingsPanel } from "./project-settings-panel";
import { WebhooksPanel } from "./webhooks-panel";

const TABS = ["project", "members", "agents", "profiles", "mcp", "webhooks", "audit", "compliance"] as const;
type SettingsTab = (typeof TABS)[number];
const DEFAULT_TAB: SettingsTab = "project";

function parseTab(value: string | null): SettingsTab {
  return value !== null && (TABS as readonly string[]).includes(value) ? (value as SettingsTab) : DEFAULT_TAB;
}

/** Project settings: general & policies, members, agents & API keys, MCP integration and audit journal. */
export function SettingsView() {
  const { slug, project, role, isOwner } = useCurrentProject();
  const { get, set } = useUrlParams();
  const tab = parseTab(get("tab"));
  const members = useMembers(slug);
  const agents = useAgents(slug);
  const activeAgents = agents.data?.filter((a) => a.active).length;

  // Audit filters (`action`, `page`) only make sense on the audit tab.
  const goTo = (next: string) => {
    const value = parseTab(next);
    set({ tab: value === DEFAULT_TAB ? null : value, action: null, page: null });
  };

  return (
    <div className="flex min-w-0 flex-col">
      <PageHeader
        icon={<Settings />}
        eyebrow={project.name}
        title="Paramètres"
        description="Configuration du projet, membres et rôles, agents et clés API, connexion MCP, webhooks, journal d'audit et conformité IA."
        meta={
          <>
            <RoleBadge value={role} size="sm" />
            {!isOwner ? (
              <Badge tone="neutral" size="sm" icon={<Lock />}>
                Lecture seule
              </Badge>
            ) : null}
          </>
        }
      />

      <Tabs value={tab} onValueChange={goTo}>
        <TabsList aria-label="Sections des paramètres" className="mb-5">
          <TabsTrigger value="project">
            <SlidersHorizontal aria-hidden />
            Projet & politiques
          </TabsTrigger>
          <TabsTrigger value="members" count={members.data?.length}>
            <Users aria-hidden />
            Membres
          </TabsTrigger>
          <TabsTrigger value="agents" count={activeAgents}>
            <Bot aria-hidden />
            Agents
          </TabsTrigger>
          <TabsTrigger value="profiles">
            <Layers aria-hidden />
            Profils de contexte
          </TabsTrigger>
          <TabsTrigger value="mcp">
            <Plug aria-hidden />
            Intégration MCP
          </TabsTrigger>
          <TabsTrigger value="webhooks">
            <Webhook aria-hidden />
            Webhooks
          </TabsTrigger>
          <TabsTrigger value="audit">
            <ScrollText aria-hidden />
            Audit
          </TabsTrigger>
          <TabsTrigger value="compliance">
            <ShieldCheck aria-hidden />
            Conformité IA
          </TabsTrigger>
        </TabsList>

        <TabsContent value="project">
          <ProjectSettingsPanel />
        </TabsContent>
        <TabsContent value="members">
          <MembersPanel />
        </TabsContent>
        <TabsContent value="agents">
          <AgentsPanel onShowMcp={() => goTo("mcp")} />
        </TabsContent>
        <TabsContent value="profiles">
          <ContextProfilesPanel />
        </TabsContent>
        <TabsContent value="mcp">
          <McpPanel onShowAgents={() => goTo("agents")} />
        </TabsContent>
        <TabsContent value="webhooks">
          <WebhooksPanel />
        </TabsContent>
        <TabsContent value="audit">
          <AuditPanel />
        </TabsContent>
        <TabsContent value="compliance">
          <CompliancePanel />
        </TabsContent>
      </Tabs>
    </div>
  );
}
