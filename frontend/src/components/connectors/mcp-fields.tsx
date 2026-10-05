"use client";

import * as React from "react";
import { ExternalLink, KeyRound, Wrench } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Field } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SimpleSelect } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import type {
  ConnectorTypeInfo,
  PresetField,
} from "@/lib/api/features-connectors";
import { cn } from "@/lib/utils";
import { presetFieldVisible } from "./connector-meta";

function splitList(value: string): string[] {
  return value
    .split(/[,;\n]+/)
    .map((part) => part.trim())
    .filter(Boolean);
}

/** One input of an MCP preset field, by kind (docs/FEATURES.md F6). */
function PresetInput({
  field,
  id,
  value,
  onChange,
  optionalSecret,
}: {
  field: PresetField;
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
  optionalSecret?: boolean;
}) {
  const secret = field.group === "secret";
  if (field.kind === "bool") {
    return (
      <div className="flex items-start gap-3 rounded-lg border border-border px-3.5 py-3 sm:col-span-2">
        <Switch
          id={id}
          checked={Boolean(value)}
          onCheckedChange={(checked) => onChange(checked)}
        />
        <div className="grid gap-0.5">
          <Label htmlFor={id}>{field.label}</Label>
          {field.help ? (
            <p className="text-xs text-muted-foreground">{field.help}</p>
          ) : null}
        </div>
      </div>
    );
  }
  const hint =
    field.help ||
    (secret
      ? "Chiffré au repos, jamais réaffiché."
      : field.kind === "list"
        ? "Séparés par des virgules"
        : undefined);
  const required = field.required && !optionalSecret;
  const wide = field.kind === "textarea" || field.kind === "list";
  return (
    <div className={cn(wide && "sm:col-span-2")}>
      <Field id={id} label={field.label} hint={hint} required={required}>
        {field.kind === "select" ? (
          <SimpleSelect
            id={id}
            value={String(value ?? field.default ?? "")}
            onValueChange={(next) => onChange(next)}
            options={field.options.map((o) => ({
              value: o.value,
              label: o.label,
            }))}
          />
        ) : field.kind === "textarea" ? (
          <Textarea
            id={id}
            rows={4}
            spellCheck={false}
            autoComplete="off"
            placeholder={field.placeholder}
            className={cn(
              "font-mono text-[13px]",
              secret && "[-webkit-text-security:disc]",
            )}
            value={String(value ?? "")}
            onChange={(e) => onChange(e.target.value)}
          />
        ) : (
          <Input
            id={id}
            type={
              field.kind === "password"
                ? "password"
                : field.kind === "number"
                  ? "number"
                  : field.kind === "url"
                    ? "url"
                    : "text"
            }
            inputMode={field.kind === "number" ? "numeric" : undefined}
            autoComplete={secret ? "new-password" : "off"}
            spellCheck={false}
            placeholder={field.placeholder}
            value={
              Array.isArray(value) ? value.join(", ") : String(value ?? "")
            }
            onChange={(e) =>
              onChange(
                field.kind === "list"
                  ? splitList(e.target.value)
                  : field.kind === "number"
                    ? e.target.value === ""
                      ? ""
                      : Number(e.target.value)
                    : e.target.value,
              )
            }
          />
        )}
      </Field>
    </div>
  );
}

/**
 * Dynamic fields of an MCP preset (from ``GET /connectors/types``): secret fields go to ``secrets``,
 * connection and scope fields to ``values`` (the connector config).
 */
export function McpFieldInputs({
  fields,
  groups,
  values,
  secrets,
  onValue,
  onSecret,
  idPrefix = "mcp",
  optionalSecrets = false,
}: {
  fields: PresetField[];
  groups: PresetField["group"][];
  values: Record<string, unknown>;
  secrets: Record<string, string>;
  onValue: (key: string, value: unknown) => void;
  onSecret: (key: string, value: string) => void;
  idPrefix?: string;
  /** Edit dialog: secrets may be left empty (kept). */
  optionalSecrets?: boolean;
}) {
  const visible = fields.filter(
    (f) => groups.includes(f.group) && presetFieldVisible(f, values),
  );
  if (!visible.length) return null;
  // List-like inputs keep the raw text while typing (« a, » must not lose the comma).
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {visible.map((field) => (
        <ListAwareInput
          key={field.key}
          field={field}
          id={`${idPrefix}-${field.key}`}
          value={
            field.group === "secret"
              ? (secrets[field.key] ?? "")
              : values[field.key]
          }
          optionalSecret={optionalSecrets}
          onChange={(value) =>
            field.group === "secret"
              ? onSecret(field.key, String(value ?? ""))
              : onValue(field.key, value)
          }
        />
      ))}
    </div>
  );
}

function ListAwareInput(props: {
  field: PresetField;
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
  optionalSecret?: boolean;
}) {
  const { field, value, onChange } = props;
  const [draft, setDraft] = React.useState(() =>
    Array.isArray(value) ? value.join(", ") : "",
  );
  const joined = Array.isArray(value) ? value.join(", ") : "";
  React.useEffect(() => {
    if (field.kind !== "list") return;
    // External change (scope option toggled): resync the draft.
    if (splitList(draft).join(", ") !== joined) setDraft(joined);
  }, [joined]); // eslint-disable-line react-hooks/exhaustive-deps
  if (field.kind !== "list") return <PresetInput {...props} />;
  return (
    <PresetInput
      {...props}
      field={{ ...field, kind: "text" }}
      value={draft}
      onChange={(next) => {
        setDraft(String(next ?? ""));
        onChange(splitList(String(next ?? "")));
      }}
    />
  );
}

/** « How to get credentials » box of a preset, with the link to the server documentation. */
export function McpPresetHelp({ info }: { info: ConnectorTypeInfo }) {
  return (
    <div className="grid gap-1.5 rounded-lg border border-border bg-muted/40 px-3.5 py-3 text-sm">
      <p className="flex items-center gap-1.5 font-medium">
        <KeyRound className="size-4 text-primary" aria-hidden />
        Obtenir les identifiants
      </p>
      {info.credentials_help ? (
        <p className="text-muted-foreground">{info.credentials_help}</p>
      ) : null}
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span>
          {info.vendor}
          {info.version ? ` · ${info.version}` : ""} ·{" "}
          {info.transport === "http"
            ? "MCP distant (HTTP)"
            : "MCP local (stdio)"}
        </span>
        {info.docs_url ? (
          <a
            href={info.docs_url}
            target="_blank"
            rel="noreferrer noopener"
            className="inline-flex items-center gap-1 text-primary underline-offset-2 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            Documentation du serveur MCP
            <ExternalLink className="size-3" aria-hidden />
            <span className="sr-only">(nouvel onglet)</span>
          </a>
        ) : null}
      </p>
    </div>
  );
}

/** Tools discovered by the credentials test; the ones ORBIT needs are highlighted. */
export function McpToolsList({
  tools,
  required,
}: {
  tools: string[];
  required: string[];
}) {
  if (!tools.length) return null;
  const needed = new Set(required);
  const sorted = [...tools].sort(
    (a, b) =>
      Number(needed.has(b)) - Number(needed.has(a)) || a.localeCompare(b),
  );
  const shown = sorted.slice(0, 40);
  return (
    <div className="grid gap-1.5">
      <p className="flex items-center gap-1.5 text-[13px] font-medium">
        <Wrench className="size-3.5 text-muted-foreground" aria-hidden />
        Outils découverts ({tools.length})
      </p>
      <ul
        className="flex max-h-32 flex-wrap gap-1.5 overflow-y-auto"
        aria-label="Outils exposés par le serveur MCP"
      >
        {shown.map((tool) => (
          <li key={tool}>
            <Badge
              tone={needed.has(tool) ? "teal" : "neutral"}
              size="sm"
              mono
              title={needed.has(tool) ? "Utilisé par ORBIT" : undefined}
            >
              {tool}
              {needed.has(tool) ? (
                <span className="sr-only"> (utilisé par ORBIT)</span>
              ) : null}
            </Badge>
          </li>
        ))}
        {tools.length > shown.length ? (
          <li className="text-xs text-muted-foreground">
            +{tools.length - shown.length} autres
          </li>
        ) : null}
      </ul>
    </div>
  );
}
