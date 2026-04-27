import { Check } from "lucide-react";

export type Stage = {
  id: number;
  label: string;
  status: "done" | "current" | "todo";
};

export const StageNav = ({ stages }: { stages: Stage[] }) => {
  return (
    <div className="flex items-center gap-1 overflow-x-auto pb-1 -mx-1 px-1">
      {stages.map((s, i) => {
        const isLast = i === stages.length - 1;
        const tone =
          s.status === "done"
            ? "bg-palm text-primary-foreground border-foreground"
            : s.status === "current"
              ? "bg-gradient-sunset text-primary-foreground border-foreground shadow-sticker"
              : "bg-card text-muted-foreground border-foreground/15";
        const labelTone =
          s.status === "todo" ? "text-muted-foreground" : "text-foreground";
        return (
          <div key={s.id} className="flex items-center shrink-0">
            <div className="flex items-center gap-2 pr-2">
              <div
                className={`h-7 w-7 rounded-full border-2 flex items-center justify-center text-xs font-bold ${tone}`}
              >
                {s.status === "done" ? <Check className="h-3.5 w-3.5" /> : s.id}
              </div>
              <span className={`text-sm font-bold ${labelTone}`}>{s.label}</span>
            </div>
            {!isLast && (
              <div className="w-6 md:w-10 h-[3px] rounded-full bg-foreground/10 mr-1" />
            )}
          </div>
        );
      })}
    </div>
  );
};
