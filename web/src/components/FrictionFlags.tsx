import { AlertTriangle } from "lucide-react";

export function FrictionFlags({ flags }: { flags: string[] }) {
  if (!flags || flags.length === 0) return null;
  return (
    <div className="rounded-xl border-2 border-coral/40 bg-coral/10 p-3 space-y-1">
      {flags.map((f) => (
        <div key={f} className="flex items-start gap-2 text-xs">
          <AlertTriangle className="h-3.5 w-3.5 text-primary shrink-0 mt-0.5" />
          <span className="font-medium text-foreground/85 leading-snug">{f}</span>
        </div>
      ))}
    </div>
  );
}

export function GradeBadge({ grade }: { grade: string }) {
  const cls =
    grade === "strong"
      ? "bg-palm/30 border-palm/50 text-foreground"
      : grade === "good"
        ? "bg-sunshine/40 border-foreground/20"
        : grade === "conditional"
          ? "bg-coral/30 border-foreground/20"
          : "bg-muted text-muted-foreground border-foreground/15";
  return (
    <span
      className={`px-2 py-0.5 rounded-full text-xs font-bold border-2 capitalize ${cls}`}
    >
      {grade}
    </span>
  );
}
