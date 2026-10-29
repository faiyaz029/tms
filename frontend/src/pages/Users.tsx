import { FormEvent, useCallback, useEffect, useState } from "react";
import { api, Role, User } from "../api";

const ROLES: Role[] = ["admin", "staff", "accountant", "shareholder", "owner"];

export default function Users() {
  const [items, setItems] = useState<User[]>([]);
  const [f, setF] = useState({ full_name: "", email: "", password: "", role: "staff" as Role });
  const [msg, setMsg] = useState("");

  const load = useCallback(() => api<{ items: User[] }>("/users").then((r) => setItems(r.items)), []);
  useEffect(() => { load(); }, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault(); setMsg("");
    try { await api("/users", { method: "POST", body: f }); setF({ ...f, full_name: "", email: "", password: "" }); setMsg("User created"); load(); }
    catch (err) { setMsg((err as Error).message); }
  };
  const toggle = (u: User) => api(`/users/${u.id}/active?active=${!u.is_active}`, { method: "PATCH" }).then(load).catch((e) => setMsg(e.message));

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-bold">Users</h2>
      <form onSubmit={create} className="card space-y-3">
        <h3 className="font-semibold">Add a staff, accountant or shareholder account</h3>
        <input className="field" placeholder="Full name" required value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} />
        <input className="field" type="email" placeholder="Email" required value={f.email} onChange={(e) => setF({ ...f, email: e.target.value })} />
        <input className="field" type="password" placeholder="Temporary password (8+ characters)" minLength={8} required value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} />
        <select className="field" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
        {msg && <p role="status" className="text-sm">{msg}</p>}
        <button className="btn">Create user</button>
      </form>
      {items.map((u) => (
        <div key={u.id} className="card flex items-center gap-3">
          <div className="flex-1"><b>{u.full_name}</b><br /><small className="text-slate-500">{u.email} · {u.role}{u.is_active ? "" : " · disabled"}</small></div>
          <button className="btn-o" onClick={() => toggle(u)}>{u.is_active ? "Disable" : "Enable"}</button>
        </div>
      ))}
    </div>
  );
}
