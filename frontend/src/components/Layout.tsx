import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
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
import { api, apiKeyStore } from "@/lib/api";

const nav = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/targets", label: "Targets", icon: ListChecks },
  { to: "/modules", label: "Modules", icon: Radar },
  { to: "/settings", label: "Settings", icon: SettingsIcon },
];

export function Layout() {
  const { theme, toggle } = useTheme();
  const [hasApiKey, setHasApiKey] = useState(() => Boolean(apiKeyStore.get()));
  const system = useQuery({ queryKey: ["system-info"], queryFn: api.systemInfo });
  useEffect(() => {
    const refresh = () => setHasApiKey(Boolean(apiKeyStore.get()));
    window.addEventListener("reconator-api-key-change", refresh);
    return () => window.removeEventListener("reconator-api-key-change", refresh);
  }, []);
  const accessLocked = system.data?.auth_required && !hasApiKey;
  return (
    <div className="min-h-screen flex flex-col app-shell">
      <a href="#main-content" className="sr-only z-[100] rounded-md bg-background px-4 py-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:ring-2 focus:ring-primary">Skip to main content</a>
      <header className="sticky top-0 z-40 border-b border-border/70 bg-background/80 backdrop-blur-xl">
        <div className="container flex h-16 items-center gap-3 sm:gap-6">
          <Link
            to="/"
            className="flex items-center gap-2 font-semibold tracking-tight"
          >
            <span className="grid h-8 w-8 place-items-center rounded-lg border border-primary/20 bg-primary/10"><Radar className="h-4 w-4 text-primary" /></span>
            <span className="hidden sm:inline">Reconator</span>
            <span className="hidden text-xs font-normal text-muted-foreground lg:inline">intelligence OS</span>
          </Link>
          <nav className="flex min-w-0 items-center gap-0.5 overflow-x-auto text-sm sm:gap-1">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  cn(
                    "px-2.5 py-2 rounded-lg transition-colors flex items-center gap-2 whitespace-nowrap sm:px-3",
                    isActive
                      ? "bg-secondary text-foreground"
                      : "text-muted-foreground hover:text-foreground hover:bg-secondary/60",
                  )
                }
              >
                <n.icon className="h-4 w-4" />
                <span className="hidden md:inline">{n.label}</span>
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
              className="hidden p-2 text-muted-foreground hover:text-foreground sm:block"
              aria-label="GitHub"
            >
              <Github className="h-5 w-5" />
            </a>
          </div>
        </div>
      </header>
      {accessLocked && (
        <div className="border-b border-amber-500/20 bg-amber-500/10 px-4 py-2 text-center text-xs text-amber-700 dark:text-amber-300">
          Read access is protected. Add the deployment API key in{" "}
          <Link to="/settings" className="font-semibold underline underline-offset-2">
            Settings
          </Link>{" "}
          to load reconnaissance intelligence.
        </div>
      )}
      <main id="main-content" tabIndex={-1} className="container flex-1 py-6 sm:py-8">
        <Outlet />
      </main>
      <footer className="border-t border-border py-4 text-center text-xs text-muted-foreground">
        Reconator · authorized reconnaissance intelligence framework
      </footer>
    </div>
  );
}
