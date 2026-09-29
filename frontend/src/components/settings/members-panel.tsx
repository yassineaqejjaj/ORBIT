"use client";

import * as React from "react";
import { Trash2, UserPlus, Users } from "lucide-react";
import { toast } from "sonner";

import { RequireRole } from "@/components/auth/require-role";
import { ClassificationBadge } from "@/components/domain/classification-badge";
import { EnumIcon } from "@/components/domain/enum-icon";
import { RoleBadge } from "@/components/domain/enum-badge";
import { UserAvatar } from "@/components/domain/user-avatar";
import { Alert } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Field, fieldDescribedBy } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { SimpleSelect, type SimpleSelectOption } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { useCurrentProject } from "@/hooks/use-current-project";
import { errorMessage } from "@/lib/api/client";
import { useAddMember, useMe, useMembers, useRemoveMember, useUpdateMember } from "@/lib/api/hooks";
import type { Member } from "@/lib/api/types";
import { ROLE_META, ROLES, type Role } from "@/lib/enums";
import { formatDate, plural } from "@/lib/format";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

const ROLE_OPTIONS: SimpleSelectOption<Role>[] = ROLES.map((r) => ({
  value: r,
  label: ROLE_META[r].label,
  description: ROLE_META[r].description,
  icon: <EnumIcon name={ROLE_META[r].icon} />,
}));

function AddMemberDialog({ slug, open, onOpenChange }: { slug: string; open: boolean; onOpenChange: (open: boolean) => void }) {
  const add = useAddMember(slug, { meta: { silentError: true } });
  const [email, setEmail] = React.useState("");
  const [role, setRole] = React.useState<Role>("viewer");
  const [emailError, setEmailError] = React.useState<string | undefined>();
  const [formError, setFormError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (open) return;
    setEmail("");
    setRole("viewer");
    setEmailError(undefined);
    setFormError(null);
    add.reset();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- reset when the dialog closes
  }, [open]);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const value = email.trim().toLowerCase();
    if (!EMAIL_RE.test(value)) {
      setEmailError("Saisissez une adresse e-mail valide.");
      return;
    }
    try {
      const member = await add.mutateAsync({ email: value, role });
      toast.success("Membre ajouté", {
        description: `${member.user.full_name || member.user.email} — ${ROLE_META[member.role].label}`,
      });
      onOpenChange(false);
    } catch (error) {
      setFormError(errorMessage(error));
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !add.isPending && onOpenChange(o)}>
      <DialogContent size="md">
        <form onSubmit={submit} className="grid gap-5" noValidate>
          <DialogHeader>
            <div className="mb-1 flex size-10 items-center justify-center rounded-lg border border-border bg-brand-soft text-brand">
              <UserPlus className="size-5" aria-hidden />
            </div>
            <DialogTitle>Ajouter un membre</DialogTitle>
            <DialogDescription>
              La personne doit disposer d&apos;un compte ORBIT. Son habilitation (C0–C3) reste gérée au niveau de la plateforme.
            </DialogDescription>
          </DialogHeader>
          {formError ? <Alert tone="red">{formError}</Alert> : null}
          <Field id="member-email" label="Adresse e-mail" required error={emailError}>
            <Input
              id="member-email"
              type="email"
              autoComplete="off"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setEmailError(undefined);
              }}
              placeholder="prenom.nom@entreprise.fr"
              invalid={Boolean(emailError)}
              aria-describedby={fieldDescribedBy("member-email", { error: emailError })}
              disabled={add.isPending}
              autoFocus
            />
          </Field>
          <Field id="member-role" label="Rôle" hint={ROLE_META[role].description}>
            <SimpleSelect<Role> id="member-role" value={role} onValueChange={setRole} options={ROLE_OPTIONS} disabled={add.isPending} />
          </Field>
          <DialogFooter>
            <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={add.isPending}>
              Annuler
            </Button>
            <Button type="submit" loading={add.isPending} leftIcon={<UserPlus aria-hidden />}>
              Ajouter
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** "Membres" tab: members with role (editable by owners), clearance, removal and invitation. */
export function MembersPanel() {
  const { slug, isOwner } = useCurrentProject();
  const { data: me } = useMe();
  const members = useMembers(slug);
  const updateMember = useUpdateMember(slug, { meta: { silentError: true } });
  const removeMember = useRemoveMember(slug, { meta: { silentError: true } });
  const [addOpen, setAddOpen] = React.useState(false);
  const [toRemove, setToRemove] = React.useState<Member | null>(null);
  const [pendingRole, setPendingRole] = React.useState<string | null>(null);

  const list = React.useMemo(
    () =>
      [...(members.data ?? [])].sort(
        (a, b) =>
          ROLES.indexOf(a.role) - ROLES.indexOf(b.role) ||
          (a.user.full_name || a.user.email).localeCompare(b.user.full_name || b.user.email, "fr"),
      ),
    [members.data],
  );
  const ownerCount = list.filter((m) => m.role === "owner").length;

  const changeRole = async (member: Member, role: Role) => {
    if (role === member.role) return;
    setPendingRole(member.user.id);
    try {
      await updateMember.mutateAsync({ userId: member.user.id, role });
      toast.success("Rôle mis à jour", { description: `${member.user.full_name || member.user.email} — ${ROLE_META[role].label}` });
    } catch (error) {
      toast.error("Impossible de modifier le rôle", { description: errorMessage(error) });
    } finally {
      setPendingRole(null);
    }
  };

  const confirmRemove = async () => {
    if (!toRemove) return;
    try {
      await removeMember.mutateAsync(toRemove.user.id);
      toast.success("Membre retiré du projet", { description: toRemove.user.full_name || toRemove.user.email });
      setToRemove(null);
    } catch (error) {
      toast.error("Impossible de retirer ce membre", { description: errorMessage(error) });
    }
  };

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {members.data ? plural(members.data.length, "membre") : "Chargement des membres…"} · les contenus sont filtrés selon le
          rôle, les ACL et l&apos;habilitation de chacun.
        </p>
        <RequireRole min="owner">
          <Button size="sm" leftIcon={<UserPlus aria-hidden />} onClick={() => setAddOpen(true)}>
            Ajouter un membre
          </Button>
        </RequireRole>
      </div>

      {members.isError ? (
        <ErrorState error={members.error} onRetry={() => void members.refetch()} />
      ) : !members.isPending && list.length === 0 ? (
        <EmptyState icon={<Users />} title="Aucun membre" description="Ajoutez des membres pour partager ce projet." />
      ) : (
        <Card className="overflow-hidden">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Membre</TableHead>
                <TableHead>Rôle</TableHead>
                <TableHead>Habilitation</TableHead>
                <TableHead>Membre depuis</TableHead>
                {isOwner ? (
                  <TableHead className="w-12">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                ) : null}
              </TableRow>
            </TableHeader>
            <TableBody>
              {members.isPending
                ? Array.from({ length: 4 }, (_, i) => (
                    <TableRow key={i}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Skeleton className="size-8 rounded-full" />
                          <div className="grid gap-1">
                            <Skeleton className="h-3.5 w-32" />
                            <Skeleton className="h-3 w-44" />
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-7 w-32" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-5 w-28" />
                      </TableCell>
                      <TableCell>
                        <Skeleton className="h-3.5 w-20" />
                      </TableCell>
                      {isOwner ? <TableCell /> : null}
                    </TableRow>
                  ))
                : list.map((m) => {
                    const isMe = me?.id === m.user.id;
                    const lastOwner = m.role === "owner" && ownerCount <= 1;
                    return (
                      <TableRow key={m.user.id}>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <UserAvatar user={m.user} showName withEmail />
                            {isMe ? (
                              <Badge tone="teal" variant="outline">
                                Vous
                              </Badge>
                            ) : null}
                            {m.user.is_admin ? (
                              <Badge tone="violet" variant="outline" title="Administrateur de la plateforme">
                                Admin
                              </Badge>
                            ) : null}
                          </div>
                        </TableCell>
                        <TableCell>
                          {isOwner ? (
                            <SimpleTooltip
                              content={lastOwner ? "Le projet doit conserver au moins un propriétaire." : undefined}
                              disabled={!lastOwner}
                            >
                              <span className="inline-flex w-44">
                                <SimpleSelect<Role>
                                  size="sm"
                                  value={m.role}
                                  onValueChange={(r) => void changeRole(m, r)}
                                  options={ROLE_OPTIONS}
                                  disabled={lastOwner || pendingRole === m.user.id}
                                  aria-label={`Rôle de ${m.user.full_name || m.user.email}`}
                                />
                              </span>
                            </SimpleTooltip>
                          ) : (
                            <RoleBadge value={m.role} />
                          )}
                        </TableCell>
                        <TableCell>
                          <ClassificationBadge level={m.user.clearance} prefix="Habilitation" />
                        </TableCell>
                        <TableCell className="whitespace-nowrap text-muted-foreground">{formatDate(m.created_at)}</TableCell>
                        {isOwner ? (
                          <TableCell>
                            <SimpleTooltip content={lastOwner ? "Dernier propriétaire : impossible de le retirer." : "Retirer du projet"}>
                              <span className="inline-flex">
                                <Button
                                  variant="ghost"
                                  size="icon-sm"
                                  onClick={() => setToRemove(m)}
                                  disabled={lastOwner}
                                  aria-label={`Retirer ${m.user.full_name || m.user.email}`}
                                >
                                  <Trash2 aria-hidden />
                                </Button>
                              </span>
                            </SimpleTooltip>
                          </TableCell>
                        ) : null}
                      </TableRow>
                    );
                  })}
            </TableBody>
          </Table>
        </Card>
      )}

      <dl className="grid gap-3 rounded-xl border border-border bg-muted/30 p-4 sm:grid-cols-3">
        {ROLES.map((r) => (
          <div key={r} className="grid gap-1">
            <dt>
              <RoleBadge value={r} />
            </dt>
            <dd className="text-xs leading-relaxed text-muted-foreground">{ROLE_META[r].description}</dd>
          </div>
        ))}
      </dl>

      {isOwner ? <AddMemberDialog slug={slug} open={addOpen} onOpenChange={setAddOpen} /> : null}
      <ConfirmDialog
        open={toRemove !== null}
        onOpenChange={(open) => {
          if (!open) setToRemove(null);
        }}
        title="Retirer ce membre ?"
        description={
          toRemove
            ? `${toRemove.user.full_name || toRemove.user.email} n'aura plus accès au projet, à ses sources ni à sa mémoire. Les agents agissant pour son compte perdront aussi cet accès.`
            : undefined
        }
        destructive
        confirmLabel="Retirer du projet"
        onConfirm={confirmRemove}
        loading={removeMember.isPending}
      />
    </div>
  );
}
