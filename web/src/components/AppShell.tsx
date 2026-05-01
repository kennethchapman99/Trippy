import { Link, NavLink, useLocation } from "react-router-dom";
import { Home, Plus, Settings, Sun, Palmtree } from "lucide-react";
import logo from "@/assets/trippy-logo.png";
import { AiCostTile } from "@/components/AiCostTile";

const nav = [
  { to: "/", label: "Trips", icon: Home },
  { to: "/new", label: "New trip", icon: Plus },
  { to: "/settings", label: "Settings", icon: Settings },
];

function tripIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/trip\/([^/]+)/);
  return match?.[1] ?? null;
}

export const AppShell = ({ children }: { children: React.ReactNode }) => {
  const { pathname } = useLocation();
  const tripId = tripIdFromPath(pathname);

  return (
    <div className="min-h-screen flex flex-col md:flex-row">
      {/* Sidebar */}
      <aside className="md:w-64 md:min-h-screen md:sticky md:top-0 bg-card/80 backdrop-blur border-b-2 md:border-b-0 md:border-r-2 border-foreground/10 flex md:flex-col items-center md:items-stretch p-4 md:p-6 gap-2 md:gap-1 z-40">
        <Link to="/" className="flex items-center md:mb-8 mr-auto md:mr-0">
          <img src={logo} alt="Trippy" className="h-16 w-auto object-contain" />
        </Link>
        <nav className="flex md:flex-col gap-1 md:gap-2 ml-auto md:ml-0">
          {nav.map((n) => {
            const active = pathname === n.to;
            return (
              <NavLink
                key={n.to}
                to={n.to}
                className={`flex items-center gap-3 px-4 py-2.5 rounded-2xl font-bold transition-bounce border-2 ${
                  active
                    ? "bg-gradient-sunset text-primary-foreground border-foreground shadow-sticker"
                    : "border-transparent text-foreground/70 hover:text-foreground hover:bg-muted"
                }`}
              >
                <n.icon className="h-5 w-5" />
                <span className="hidden md:inline">{n.label}</span>
              </NavLink>
            );
          })}
        </nav>
        <AiCostTile tripId={tripId} />
      </aside>

      {/* Main */}
      <main className="flex-1 relative overflow-hidden">
        <Sun className="absolute -top-8 -right-8 h-40 w-40 opacity-20 animate-float-slow" style={{ color: "hsl(var(--sunshine))" }} />
        <Palmtree className="absolute bottom-10 -left-6 h-32 w-32 opacity-10 hidden lg:block" style={{ color: "hsl(var(--palm))" }} />
        <div className="relative">{children}</div>
      </main>
    </div>
  );
};
