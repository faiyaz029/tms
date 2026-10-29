import { FormEvent, useCallback, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import GoogleButton from "../components/GoogleButton";

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-md p-4 pt-10">
      <div className="card space-y-4">
        <h1 className="text-2xl font-bold">{title}</h1>
        {children}
      </div>
    </div>
  );
}

const Err = ({ msg }: { msg: string }) => msg ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{msg}</p> : null;

function useSubmit(fn: () => Promise<void>) {
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError(""); setBusy(true);
    try { await fn(); } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  };
  return { error, busy, submit, setError };
}

export function Login() {
  const { user, login, google } = useAuth();
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const { error, busy, submit, setError } = useSubmit(() => login(email, password));
  const onGoogle = useCallback((c: string) => { google(c).catch((e) => setError(e.message)); }, [google, setError]);
  if (user) return <Navigate to="/" replace />;
  return (
    <Shell title="Sign in">
      <GoogleButton onCredential={onGoogle} />
      <p className="text-center text-sm text-slate-500">or use your email</p>
      <form onSubmit={submit} className="space-y-3">
        <input className="field" type="email" placeholder="Email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="field" type="password" placeholder="Password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Err msg={error} />
        <button className="btn w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
      </form>
      <p className="text-center text-sm">New customer? <Link className="font-semibold underline" to="/register">Create an account</Link></p>
    </Shell>
  );
}

export function Register() {
  const { user, register } = useAuth();
  const [f, setF] = useState({ full_name: "", email: "", password: "", phone: "", address: "" });
  const { error, busy, submit } = useSubmit(() => register(f));
  if (user) return <Navigate to="/" replace />;
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <Shell title="Create account">
      <form onSubmit={submit} className="space-y-3">
        <input className="field" placeholder="Full name" required value={f.full_name} onChange={set("full_name")} />
        <input className="field" type="email" placeholder="Email" required value={f.email} onChange={set("email")} />
        <input className="field" type="password" placeholder="Password (8+ characters)" minLength={8} required value={f.password} onChange={set("password")} />
        <input className="field" type="tel" inputMode="tel" placeholder="Mobile number, like 01712345678" required value={f.phone} onChange={set("phone")} />
        <textarea className="field" rows={2} placeholder="Full address" required minLength={8} value={f.address} onChange={set("address")} />
        <Err msg={error} />
        <button className="btn w-full" disabled={busy}>{busy ? "Creating…" : "Create account"}</button>
      </form>
      <p className="text-center text-sm">Have an account? <Link className="font-semibold underline" to="/login">Sign in</Link></p>
    </Shell>
  );
}

export function CompleteProfile() {
  const { user, saveProfile } = useAuth();
  const nav = useNavigate();
  const [f, setF] = useState({ phone: user?.phone ?? "", address: user?.address ?? "" });
  const { error, busy, submit } = useSubmit(async () => { await saveProfile(f); nav("/", { replace: true }); });
  return (
    <Shell title="Complete your profile">
      <p className="text-slate-600 dark:text-slate-300">Add your phone number and address before you book.</p>
      <form onSubmit={submit} className="space-y-3">
        <input className="field" type="tel" inputMode="tel" placeholder="01712345678" required value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />
        <textarea className="field" rows={2} placeholder="Full address" required minLength={8} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />
        <Err msg={error} />
        <button className="btn w-full" disabled={busy}>Save and continue</button>
      </form>
    </Shell>
  );
}
