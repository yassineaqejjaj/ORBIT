"use client";

import * as React from "react";
import { Crown, PencilLine, Search, UserRoundCheck, Users } from "lucide-react";

import { RoleBadge } from "@/components/domain/enum-badge";
import { UserAvatar } from "@/components/domain/user-avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useMembers } from "@/lib/api/hooks";
import { cn, normalizeText } from "@/lib/utils";
import { ACL_MODE_OPTIONS, type AclMode, type AclValue } from "./acl";

const MODE_ICONS: Record<AclMode, React.ReactNode> = {
  project: <Users aria-hidden />,
  editors: <PencilLine aria-hidden />,
  owners: <Crown aria-hidden />,
  users: <UserRoundCheck aria-hidden />,
};

export interface AclPickerProps {
  slug: string;
  value: AclValue;
  onChange: (value: AclValue) => void;
  disabled?: boolean;
  /** Error shown under the member list (e.g. no member selected). */
  error?: string;
  idPrefix?: string;
}

/** ACL preset picker: project / editors+owners / owners / named members (multi-select). */
export function AclPicker({ slug, value, onChange, disabled, error, idPrefix = "acl" }: AclPickerProps) {
  const members = useMembers(slug, { enabled: value.mode === "users" });
  const [filter, setFilter] = React.useState("");

  const filtered = React.useMemo(() => {
    const q = normalizeText(filter);
    const list = members.data ?? [];
    return q ? list.filter((m) => normalizeText(`${m.user.full_name} ${m.user.email}`).includes(q)) : list;
  }, [members.data, filter]);

  const toggleUser = (userId: string, checked: boolean) => {
    const set = new Set(value.userIds);
    if (checked) set.add(userId);
    else set.delete(userId);
    onChange({ mode: "users", userIds: [...set] });
  };

  return (
    <div className="grid gap-2">
      <div role="radiogroup" aria-label="Accès au contenu" className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {ACL_MODE_OPTIONS.map((option) => {
          const selected = value.mode === option.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={disabled}
              id={`${idPrefix}-${option.value}`}
              onClick={() => onChange({ mode: option.value, userIds: option.value === "users" ? value.userIds : [] })}
              className={cn(
                "flex items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-[border-color,background-color,box-shadow]",
                "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-60",
                selected
                  ? "border-primary bg-brand-soft/60 shadow-xs"
                  : "border-border bg-background hover:border-border-strong hover:bg-muted/40",
              )}
            >
              <span
                className={cn(
                  "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md [&_svg]:size-3.5",
                  selected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground",
                )}
              >
                {MODE_ICONS[option.value]}
              </span>
              <span className="grid min-w-0 gap-0.5">
                <span className="text-[13px] font-medium leading-tight text-foreground">{option.label}</span>
                <span className="text-xs leading-snug text-muted-foreground">{option.description}</span>
              </span>
            </button>
          );
        })}
      </div>

      {value.mode === "users" ? (
        <div
          className={cn(
            "grid gap-2 rounded-lg border bg-muted/30 p-2",
            error ? "border-destructive" : "border-border",
          )}
        >
          <Input
            size="sm"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Rechercher un membre…"
            leftIcon={<Search aria-hidden />}
            aria-label="Rechercher un membre"
            disabled={disabled}
          />
          <div className="max-h-44 overflow-y-auto">
            {members.isPending ? (
              <div className="grid gap-2 p-1">
                {Array.from({ length: 3 }, (_, i) => (
                  <Skeleton key={i} className="h-8" />
                ))}
              </div>
            ) : members.isError ? (
              <p className="px-2 py-3 text-xs text-destructive">Impossible de charger les membres du projet.</p>
            ) : filtered.length === 0 ? (
              <p className="px-2 py-3 text-xs text-muted-foreground">Aucun membre ne correspond.</p>
            ) : (
              <ul className="grid gap-0.5">
                {filtered.map((m) => {
                  const checked = value.userIds.includes(m.user.id);
                  const cid = `${idPrefix}-user-${m.user.id}`;
                  return (
                    <li key={m.user.id}>
                      <label
                        htmlFor={cid}
                        className={cn(
                          "flex cursor-pointer items-center gap-2.5 rounded-md px-2 py-1.5 hover:bg-accent",
                          checked && "bg-accent/70",
                        )}
                      >
                        <Checkbox
                          id={cid}
                          checked={checked}
                          disabled={disabled}
                          onCheckedChange={(c) => toggleUser(m.user.id, c === true)}
                        />
                        <UserAvatar user={m.user} size="sm" showName withEmail className="flex-1" />
                        <RoleBadge value={m.role} withIcon={false} />
                      </label>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <p className={cn("px-1 text-xs", error ? "font-medium text-destructive" : "text-muted-foreground")} role={error ? "alert" : undefined}>
            {error ??
              (value.userIds.length > 0
                ? `${value.userIds.length} membre${value.userIds.length > 1 ? "s" : ""} sélectionné${value.userIds.length > 1 ? "s" : ""}`
                : "Sélectionnez au moins un membre.")}
          </p>
        </div>
      ) : null}
    </div>
  );
}
