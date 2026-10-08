import { Layers } from "lucide-react";

import type { MetricsCache } from "@/lib/api/types";
import { formatNumber, formatPercent } from "@/lib/format";
import { ChartCard } from "./chart-card";

function Tile({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint: string;
}) {
  return (
    <div className="grid content-start gap-1 rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-[12.5px] font-medium text-muted-foreground">{label}</p>
      <p className="text-2xl font-semibold tracking-tight text-foreground tabular-nums">
        {value}
      </p>
      <p className="text-[11.5px] text-subtle-foreground">{hint}</p>
    </div>
  );
}

/** §C1 prompt cache: how often the stable prefix of a package was already served in the cache window. */
export function CacheStats({
  cache,
  loading,
}: {
  cache: MetricsCache | undefined;
  loading?: boolean;
}) {
  const packages = cache?.packages ?? 0;
  return (
    <ChartCard
      title="Cache de prompt"
      description="Préfixe stable (consignes, décisions en vigueur, contraintes, snapshot) réutilisé d'une requête à l'autre."
      icon={<Layers aria-hidden />}
      loading={loading}
      empty={!loading && packages === 0}
      emptyText="Aucun contexte avec préfixe stable sur la période."
      height={110}
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile
          label="Taux de réutilisation"
          value={formatPercent(cache?.reuse_rate ?? 0)}
          hint={`${formatNumber(cache?.reused ?? 0, 0)} sur ${formatNumber(packages, 0)} contextes`}
        />
        <Tile
          label="Préfixe moyen"
          value={formatNumber(cache?.avg_prefix_tokens ?? 0, 0)}
          hint="tokens par contexte"
        />
        <Tile
          label="Tokens réutilisables"
          value={formatNumber(cache?.reused_prefix_tokens ?? 0, 0)}
          hint="servis depuis un préfixe déjà vu"
        />
        <Tile
          label="Contextes"
          value={formatNumber(packages, 0)}
          hint="avec empreinte cache_prefix_hash"
        />
      </div>
    </ChartCard>
  );
}
