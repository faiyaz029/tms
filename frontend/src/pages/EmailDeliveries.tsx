import { useCallback, useEffect, useState } from "react";
import { api } from "../api";

interface Delivery {
  id: number;
  statement_id: number | null;
  recipient: string;
  subject: string;
  kind: string;
  status: "pending" | "sent" | "failed" | "previewed";
  attempts: number;
  last_error: string | null;
  provider_id: string | null;
  created_at: string;
  updated_at: string;
}

interface PageList<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

const statusText = (delivery: Delivery) => {
  if (delivery.status === "previewed") return "◷ Previewed · not sent";
  if (delivery.status === "sent" && delivery.provider_id === "console-log") {
    return "ℹ Logged only · not delivered";
  }
  if (delivery.status === "sent") return "✓ Sent to email provider";
  if (delivery.status === "failed") return "✕ Failed";
  return "◷ Pending";
};

export default function EmailDeliveries() {
  const [page, setPage] = useState<PageList<Delivery> | null>(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [previewId, setPreviewId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<number | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setPage(await api<PageList<Delivery>>(`/emails?page=${pageNumber}&size=50`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [pageNumber]);

  useEffect(() => { void refresh(); }, [refresh]);

  const retry = async (delivery: Delivery) => {
    setBusy(delivery.id);
    setError("");
    try {
      await api(`/emails/${delivery.id}/retry`, { method: "POST" });
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Email deliveries</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">A preview or console log is not a delivered email. SMTP status means accepted by the configured provider.</p>
      </header>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{error}</p>}
      <section className="card space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-bold">Delivery status · {page?.total ?? 0}</h2>
          <button type="button" className="btn-o" disabled={loading} onClick={() => void refresh()}>Refresh</button>
        </div>
        {loading ? <p role="status">Loading email deliveries…</p> : page?.items.length ? (
          <div className="space-y-3">
            {page.items.map((delivery) => (
              <article key={delivery.id} className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <p className="font-semibold">{delivery.subject}</p>
                <p className="text-sm">{delivery.recipient} · {delivery.kind.replace(/_/g, " ")}</p>
                <p className="text-sm">{statusText(delivery)} · attempts: {delivery.attempts}</p>
                {delivery.last_error && <p role="alert" className="text-sm text-red-700 dark:text-red-300">{delivery.last_error}</p>}
                <div className="flex flex-wrap gap-2">
                  {delivery.status === "failed" && (
                    <button type="button" className="btn-o" disabled={busy !== null} onClick={() => void retry(delivery)}>
                      {busy === delivery.id ? "Retrying…" : "Retry"}
                    </button>
                  )}
                  <button type="button" className="btn-o" onClick={() => setPreviewId(
                    previewId === delivery.id ? null : delivery.id,
                  )}>
                    {previewId === delivery.id ? "Hide preview" : "Preview email"}
                  </button>
                </div>
                {previewId === delivery.id && (
                  <iframe
                    title={`Email preview ${delivery.id}`}
                    src={`/api/emails/${delivery.id}/preview`}
                    sandbox=""
                    className="h-96 w-full rounded border border-slate-300 bg-white"
                  />
                )}
              </article>
            ))}
          </div>
        ) : <p className="text-sm">No email deliveries have been queued.</p>}
        {page && page.total > page.size && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-700">
            <button type="button" className="btn-o" disabled={pageNumber <= 1 || loading} onClick={() => setPageNumber((value) => value - 1)}>Previous</button>
            <span className="text-sm">Page {page.page} of {Math.ceil(page.total / page.size)}</span>
            <button type="button" className="btn-o" disabled={pageNumber * page.size >= page.total || loading} onClick={() => setPageNumber((value) => value + 1)}>Next</button>
          </div>
        )}
      </section>
    </div>
  );
}
