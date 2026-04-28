import { Link } from "react-router-dom";
import { ArrowLeft, AlertTriangle } from "lucide-react";
import type { TripIntake } from "@/lib/api";

export function ShortlistHero({
  intake,
  stageLabel,
  stageNumber,
  flagCount,
}: {
  intake: TripIntake | null | undefined;
  stageLabel: string;
  stageNumber: number;
  flagCount?: number;
}) {
  const tripName = intake?.trip_name ?? "Your trip";
  const destination = intake?.destination_seeds?.join(" · ") ?? "";

  return (
    <div className="bg-gradient-hero border-b-2 border-foreground/10 px-6 md:px-10 pt-8 pb-10 relative">
      <Link
        to="/"
        className="inline-flex items-center gap-1.5 text-sm font-bold text-foreground/70 hover:text-foreground transition-colors mb-4"
      >
        <ArrowLeft className="h-4 w-4" /> Back to trips
      </Link>
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <span className="px-3 py-1 rounded-full bg-card border-2 border-foreground/15 text-xs font-bold uppercase tracking-wider">
          Planning · Stage {stageNumber} of 8 — {stageLabel}
        </span>
        {intake?.duration_days && (
          <span className="px-3 py-1 rounded-full bg-sunshine/40 border-2 border-foreground/15 text-xs font-bold">
            {intake.duration_days} days
          </span>
        )}
        {intake?.party && (
          <span className="px-3 py-1 rounded-full bg-coral/30 border-2 border-foreground/15 text-xs font-bold">
            {intake.party.adults + intake.party.children} travelers
          </span>
        )}
        {flagCount !== undefined && flagCount > 0 && (
          <div className="ml-auto flex items-center gap-2 px-3 py-2 rounded-2xl bg-foreground text-background border-2 border-foreground shadow-sticker">
            <AlertTriangle className="h-4 w-4 text-sunshine" />
            <div className="text-xs leading-tight">
              <div className="font-bold">{flagCount} friction flag{flagCount !== 1 ? "s" : ""}</div>
              <div className="opacity-70">Trippy is watching</div>
            </div>
          </div>
        )}
      </div>
      <h1 className="font-[Fredoka] text-4xl md:text-5xl font-bold leading-[1.05] max-w-3xl">
        {tripName}
      </h1>
      {destination && (
        <p className="text-foreground/70 italic mt-2 font-medium">{destination}</p>
      )}
    </div>
  );
}
