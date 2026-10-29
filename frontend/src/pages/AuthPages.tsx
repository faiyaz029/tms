import { FormEvent, useCallback, useState } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
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
      <p className="text-center text-sm"><Link className="font-semibold underline" to="/forgot-password">Forgot your password?</Link></p>
    </Shell>
  );
}

export function ForgotPassword() {
  const { user } = useAuth();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/forgot-password", { method: "POST", body: { email } });
      setSubmitted(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title="Reset your password">
      {submitted ? (
        <p role="status">If an account exists for that email, a reset link has been sent.</p>
      ) : (
        <>
          <p className="text-sm">Enter your account email. If it matches an active account, we will send a reset link.</p>
          <form onSubmit={(event) => void submit(event)} className="space-y-3">
            <input className="field" type="email" placeholder="Email" autoComplete="email" required value={email} onChange={(event) => setEmail(event.target.value)} />
            <Err msg={error} />
            <button className="btn w-full" disabled={busy}>{busy ? "Sending…" : "Send reset link"}</button>
          </form>
        </>
      )}
      <p className="text-center text-sm"><Link className="font-semibold underline" to="/login">Back to sign in</Link></p>
    </Shell>
  );
}

export function ResetPassword() {
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const token = searchParams.get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    if (!token) {
      setError("This reset link is invalid or expired.");
      return;
    }
    if (password !== confirm) {
      setError("The passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: { token, password },
      });
      setSubmitted(true);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Shell title="Choose a new password">
      {submitted ? (
        <p role="status">Your password has been updated. <Link className="font-semibold underline" to="/login">Sign in</Link></p>
      ) : (
        <form onSubmit={(event) => void submit(event)} className="space-y-3">
          <input className="field" type="password" placeholder="New password (8+ characters)" autoComplete="new-password" minLength={8} maxLength={72} required value={password} onChange={(event) => setPassword(event.target.value)} />
          <input className="field" type="password" placeholder="Confirm new password" autoComplete="new-password" minLength={8} maxLength={72} required value={confirm} onChange={(event) => setConfirm(event.target.value)} />
          <Err msg={error} />
          <button className="btn w-full" disabled={busy}>{busy ? "Updating…" : "Update password"}</button>
        </form>
      )}
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
