import { Link, NavLink, Outlet } from "react-router-dom";
import {
  Github,
  LayoutDashboard,
  ListChecks,
  Moon,
  Radar,
  Settings as SettingsIcon,
  Sun,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/components/ThemeProvider";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/targets", label: "Targets", icon: ListChecks },
  { to: "/modules", label: "Modules", icon: Radar },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Layout() {
  const { theme, toggle } = useTheme();
  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border bg-card/40 backdrop-blur sticky top-0 z-40">
        <div className="container flex h-14 items-center gap-6">
          <Link
            to="/"
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <Radar className="h-5 w-5 text-primary" />
            <span>Reconator</span>
            <span className="text-xs text-muted-foreground font-normal">v3</span>
          </Link>
          <nav className="flex items-center gap-1 text-sm">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  cn(
                    "px-3 py-1.5 rounded-md transition-colors flex items-center gap-2",
                    isActive
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/60",
                  )
                }
              >
                <n.icon className="h-4 w-4" />
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-1">
            <Button
              size="icon"
              variant="ghost"
              onClick={toggle}
              aria-label="Toggle theme"
            >
              {theme === "dark" ? <Sun /> : <Moon />}
            </Button>
            <a
              href="https://github.com/gokulapap/Reconator"
              target="_blank"
              rel="noreferrer"
              className="text-muted-foreground hover:text-foreground p-2"
              aria-label="GitHub"
            >
              <Github className="h-5 w-5" />
            </a>
          </div>
        </div>
      </header>
      <main className="flex-1 container py-8">
        <Outlet />
      </main>
      <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground">
        Reconator — automated reconnaissance framework
      </footer>
    </div>
  );
}
