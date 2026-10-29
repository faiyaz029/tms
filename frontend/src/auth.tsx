import { createContext, ReactNode, useCallback, useContext, useEffect, useState } from "react";
import { api, User } from "./api";

interface Ctx {
  user: User | null; loading: boolean;
  login(email: string, password: string): Promise<void>;
  register(b: { email: string; password: string; full_name: string; phone: string; address: string }): Promise<void>;
  google(credential: string): Promise<void>;
  saveProfile(b: { full_name?: string; phone: string; address: string }): Promise<void>;
  logout(): Promise<void>;
  can(permission: string): boolean;
}

const AuthCtx = createContext<Ctx>(null!);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<User>("/auth/me").then(setUser).catch(() => setUser(null)).finally(() => setLoading(false));
  }, []);

  const set = useCallback((p: Promise<User>) => p.then(setUser), []);
  const value: Ctx = {
    user, loading,
    login: (email, password) => set(api<User>("/auth/login", { method: "POST", body: { email, password } })),
    register: (b) => set(api<User>("/auth/register", { method: "POST", body: b })),
    google: (credential) => set(api<User>("/auth/google", { method: "POST", body: { credential } })),
    saveProfile: (b) => set(api<User>("/auth/profile", { method: "PATCH", body: b })),
    logout: async () => { await api("/auth/logout", { method: "POST" }); setUser(null); },
    can: (p) => !!user?.permissions.includes(p),
  };
  return <AuthCtx.Provider value={value}>{children}</AuthCtx.Provider>;
}
