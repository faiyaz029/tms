import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { NAV } from "../nav";

export default function Layout() {
  const { user, logout } = useAuth();
  if (!user) return null;
  const items = NAV[user.role];

  return (
    <div className="min-h-screen md:flex">
      <aside className="hidden w-56 shrink-0 bg-pitch-900 p-4 text-white md:block">
        <h1 className="mb-6 text-lg font-bold"> Turf &amp; Pool</h1>
        <nav className="space-y-1">
          {items.map((i) => (
            <NavLink key={i.path} to={i.path}
              className={({ isActive }) => `block rounded-lg px-3 py-2 ${isActive ? "bg-white/20 font-semibold" : "hover:bg-white/10"}`}>
              {i.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <div className="flex-1 pb-20 md:pb-0">
        <header className="flex items-center gap-3 bg-pitch-900 px-4 py-3 text-white md:bg-transparent md:text-inherit">
          <b className="flex-1 md:hidden">Turf &amp; Pool</b>
          <span className="hidden flex-1 text-sm text-slate-500 md:block dark:text-slate-400">Signed in as {user.full_name} ({user.role})</span>
          <button className="rounded-lg border border-white/40 px-3 py-2 text-sm md:border-slate-300" onClick={logout}>Sign out</button>
        </header>
        <main className="mx-auto max-w-3xl p-4"><Outlet /></main>
      </div>
      <nav className="fixed inset-x-0 bottom-0 overflow-x-auto border-t border-slate-200 bg-white md:hidden dark:border-slate-700 dark:bg-slate-800"
        style={{ paddingBottom: "env(safe-area-inset-bottom, 0px)" }}>
        <div className="flex min-w-max">
          {items.map((i) => (
            <NavLink key={i.path} to={i.path}
              className={({ isActive }) => `min-h-[44px] min-w-[76px] px-3 py-3 text-center text-xs ${isActive ? "font-bold text-pitch-700 dark:text-emerald-400" : "text-slate-600 dark:text-slate-300"}`}>
              {i.label}
            </NavLink>
          ))}
        </div>
      </nav>
    </div>
  );
}
