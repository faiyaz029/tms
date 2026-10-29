import { useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { NAV } from "../nav";

export default function Placeholder() {
  const { pathname } = useLocation();
  const { user } = useAuth();
  const item = user && NAV[user.role].find((i) => i.path === pathname);
  return (
    <div className="card">
      <h2 className="mb-1 text-xl font-bold">{item?.label ?? "Page"}</h2>
      <p className="text-slate-600 dark:text-slate-300">
        This screen is built in Phase {item?.phase ?? "?"}. The sign-in, roles and navigation around it already work.
        See <code>demo/turf-pool-demo.html</code> for the intended design.
      </p>
    </div>
  );
}
