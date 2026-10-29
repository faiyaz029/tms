export type Role = "owner" | "admin" | "staff" | "accountant" | "shareholder" | "customer";

export interface User {
  id: number; email: string; full_name: string; phone: string | null; address: string | null;
  role: Role; is_active: boolean; profile_complete: boolean; permissions: string[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

const csrf = () => document.cookie.split("; ").find((c) => c.startsWith("csrf_token="))?.split("=")[1] ?? "";

export async function api<T>(
  path: string,
  opts: { method?: string; body?: unknown; headers?: Record<string, string> } = {},
): Promise<T> {
  const method = opts.method ?? "GET";
  const res = await fetch(`/api${path}`, {
    method,
    credentials: "include",
    headers: {
      ...(opts.body ? { "Content-Type": "application/json" } : {}),
      ...(method !== "GET" ? { "X-CSRF-Token": csrf() } : {}),
      ...opts.headers,
    },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 204) return undefined as T;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const d = data?.detail;
    const msg = Array.isArray(d) ? d.map((e: { msg: string }) => e.msg.replace("Value error, ", "")).join(". ")
      : typeof d === "string" ? d : "Something went wrong. Please try again";
    throw new ApiError(res.status, msg);
  }
  return data as T;
}
