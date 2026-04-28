import { Loader2, Sparkles, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";

export function EmptyShortlist({
  title,
  description,
  ctaLabel,
  onBuild,
  isLoading,
  isError,
  errorMessage,
}: {
  title: string;
  description: string;
  ctaLabel: string;
  onBuild: () => void;
  isLoading: boolean;
  isError?: boolean;
  errorMessage?: string;
}) {
  return (
    <div className="rounded-3xl border-2 border-dashed border-foreground/20 bg-muted/20 p-12 flex flex-col items-center text-center gap-4">
      <div className="h-16 w-16 rounded-2xl bg-gradient-sunset border-2 border-foreground shadow-sticker flex items-center justify-center">
        {isLoading ? (
          <Loader2 className="h-8 w-8 text-primary-foreground animate-spin" />
        ) : (
          <Sparkles className="h-8 w-8 text-primary-foreground" />
        )}
      </div>
      <div>
        <h3 className="font-[Fredoka] text-2xl font-bold">{title}</h3>
        <p className="text-muted-foreground text-sm mt-2 max-w-md">{description}</p>
      </div>
      <Button
        onClick={onBuild}
        disabled={isLoading}
        className="h-12 rounded-2xl bg-gradient-sunset text-primary-foreground font-bold border-2 border-foreground shadow-sticker hover:translate-y-[-2px] transition-bounce px-8"
      >
        {isLoading ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" /> Hermes is researching…
          </>
        ) : (
          ctaLabel
        )}
      </Button>
      {isError && errorMessage && (
        <div className="flex items-start gap-2 text-sm text-destructive max-w-md">
          <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{errorMessage}</span>
        </div>
      )}
    </div>
  );
}
