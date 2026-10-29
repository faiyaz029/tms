import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, downloadCsv } from "../api";
import { useAuth } from "../auth";

interface MethodCollection {
  count: number;
  received_amount: string;
  verified_amount: string;
  unverified_amount: string;
}

interface MethodExpense {
  count: number;
  amount: string;
}

interface MethodPending {
  count: number;
  amount: string;
}

interface ClosingTotals {
  business_date: string;
  calculated_at: string;
  bookings: { created: number; cancelled: number; expired: number };
  collections_by_method: Record<string, MethodCollection>;
  collections_total: {
    count: number;
    received_amount: string;
    verified_amount: string;
    unverified_amount: string;
  };
  expenses_by_method: Record<string, MethodExpense>;
  pending_verifications: {
    count: number;
    amount: string;
    by_method: Record<string, MethodPending>;
  };
  pending_approvals: { count: number; amount: string };
}

interface Closing {
  id: number;
  business_date: string;
  version: number;
  status: "submitted" | "reviewed";
  totals: ClosingTotals;
  notes: string | null;
  difference_notes: string | null;
  submitted_by: number;
  submitted_at: string;
  reviewed_by: number | null;
  reviewed_at: string | null;
  review_notes: string | null;
}

interface PageList<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

const businessDate = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Dhaka",
}).format(new Date());
const money = (amount: string) => `৳${Number(amount).toLocaleString("en-US", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;
const dateTimeLabel = (value: string) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));
const methodLabel = (method: string) => method === "online_simulated"
  ? "SIMULATED PAYMENT"
  : method.replace(/_/g, " ");
const closingStatusLabel: Record<Closing["status"], string> = {
  submitted: "◷ Submitted · awaiting review",
  reviewed: "✓ Reviewed",
};

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function TotalsView({ totals }: { totals: ClosingTotals }) {
  const collections = Object.entries(totals.collections_by_method);
  const expenses = Object.entries(totals.expenses_by_method);
  const pending = Object.entries(totals.pending_verifications.by_method);
  return (
    <div className="space-y-4">
      <section>
        <h3 className="font-bold">Bookings</h3>
        <dl className="grid grid-cols-1 gap-2 text-sm sm:grid-cols-3">
          <div className="rounded border p-2"><dt>Created</dt><dd className="font-semibold">{totals.bookings.created}</dd></div>
          <div className="rounded border p-2"><dt>Cancelled</dt><dd className="font-semibold">{totals.bookings.cancelled}</dd></div>
          <div className="rounded border p-2"><dt>Expired</dt><dd className="font-semibold">{totals.bookings.expired}</dd></div>
        </dl>
      </section>

      <section className="space-y-2">
        <h3 className="font-bold">Collections by received date and method</h3>
        {collections.length ? (
          <div className="space-y-2">
            {collections.map(([method, values]) => <div key={method} className="rounded border p-3 text-sm">
              <p className="font-semibold">{methodLabel(method)} · {values.count} payment(s)</p>
              <p>Recorded received: {money(values.received_amount)} · verified: {money(values.verified_amount)} · awaiting verification: {money(values.unverified_amount)}</p>
            </div>)}
          </div>
        ) : <p className="text-sm">No collections were recorded for this business date.</p>}
        <p className="text-sm font-semibold">Total received: {money(totals.collections_total.received_amount)} · Verified: {money(totals.collections_total.verified_amount)} · Unverified: {money(totals.collections_total.unverified_amount)}</p>
      </section>

      <section className="space-y-2">
        <h3 className="font-bold">Approved expenses by payment method</h3>
        {expenses.length ? expenses.map(([method, values]) => (
          <p key={method} className="rounded border p-3 text-sm">{methodLabel(method)} · {values.count} expense(s) · {money(values.amount)}</p>
        )) : <p className="text-sm">No approved expenses were paid on this business date.</p>}
      </section>

      <section className="space-y-2">
        <h3 className="font-bold">Pending items at calculation time</h3>
        <p className="text-sm font-semibold">Verifications: {totals.pending_verifications.count} · {money(totals.pending_verifications.amount)}</p>
        {pending.map(([method, values]) => <p key={method} className="text-sm">{methodLabel(method)} · {values.count} pending · {money(values.amount)}</p>)}
        <p className="text-sm font-semibold">Expense approvals: {totals.pending_approvals.count} · {money(totals.pending_approvals.amount)}</p>
      </section>
      <p className="text-xs text-slate-500">Calculated {dateTimeLabel(totals.calculated_at)} · all dates use Asia/Dhaka business time.</p>
    </div>
  );
}

export default function Closings() {
  const { can } = useAuth();
  const [businessDay, setBusinessDay] = useState(businessDate);
  const [preview, setPreview] = useState<ClosingTotals | null>(null);
  const [history, setHistory] = useState<PageList<Closing> | null>(null);
  const [notes, setNotes] = useState("");
  const [differenceNotes, setDifferenceNotes] = useState("");
  const [reviewNotes, setReviewNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const canSubmit = can("closing.submit");
  const canReview = can("closing.review");
  const latest = history?.items[0];
  const hasUnreviewedLatest = latest?.status === "submitted";

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [totals, closings] = await Promise.all([
        api<ClosingTotals>(`/closings/totals?business_date=${encodeURIComponent(businessDay)}`),
        api<PageList<Closing>>(`/closings?date=${encodeURIComponent(businessDay)}`),
      ]);
      setPreview(totals);
      setHistory(closings);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [businessDay]);

  useEffect(() => { void refresh(); }, [refresh]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const closing = await api<Closing>("/closings", {
        method: "POST",
        body: { business_date: businessDay, notes, difference_notes: differenceNotes },
      });
      setNotice(`Daily closing for ${closing.business_date}, version ${closing.version}, submitted.`);
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const review = async () => {
    if (!latest || latest.status !== "submitted") return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/closings/${latest.id}/review`, {
        method: "POST",
        body: { review_notes: reviewNotes },
      });
      setNotice(`Daily closing version ${latest.version} reviewed.`);
      setReviewNotes("");
      await refresh();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const historyItems = useMemo(() => history?.items ?? [], [history]);

  const exportClosings = async () => {
    setExporting(true);
    setError("");
    try {
      await downloadCsv(
        `/exports/closings.csv?date=${encodeURIComponent(businessDay)}`,
        `closings-${businessDay}.csv`,
      );
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Daily closing</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Review a business-day snapshot before submitting. Corrections create a new version; prior snapshots are retained.</p>
      </header>
      <ErrorNotice message={error} />
      {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>}

      <section className="card space-y-4">
        <label className="block max-w-sm space-y-1">
          <span className="text-sm font-semibold">Business date (Asia/Dhaka)</span>
          <input className="field" type="date" value={businessDay} onChange={(event) => {
            setBusinessDay(event.target.value);
            setNotes("");
            setDifferenceNotes("");
            setReviewNotes("");
          }} />
        </label>
        <button type="button" className="btn-o" disabled={exporting} onClick={() => void exportClosings()}>
          {exporting ? "Exporting…" : "Export this date"}
        </button>
        {loading ? <p role="status">Calculating daily totals…</p> : preview && <TotalsView totals={preview} />}
        {canSubmit && (
          <form className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-700" onSubmit={(event) => void submit(event)}>
            <label className="block space-y-1">
              <span className="text-sm font-semibold">Closing notes</span>
              <textarea className="field min-h-16" maxLength={2000} value={notes} onChange={(event) => setNotes(event.target.value)} />
            </label>
            <label className="block space-y-1">
              <span className="text-sm font-semibold">Unresolved-difference notes</span>
              <textarea className="field min-h-16" maxLength={2000} value={differenceNotes} onChange={(event) => setDifferenceNotes(event.target.value)} />
            </label>
            <button className="btn" disabled={busy || loading || hasUnreviewedLatest}>
              {hasUnreviewedLatest ? "Await review before submitting a correction" : busy ? "Submitting…" : "Submit closing snapshot"}
            </button>
          </form>
        )}
        {canReview && latest?.status === "submitted" && (
          <div className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-700">
            <label className="block space-y-1">
              <span className="text-sm font-semibold">Review notes</span>
              <textarea className="field min-h-16" maxLength={2000} value={reviewNotes} onChange={(event) => setReviewNotes(event.target.value)} />
            </label>
            <button type="button" className="btn-o" disabled={busy} onClick={() => void review()}>Mark latest closing reviewed</button>
          </div>
        )}
      </section>

      <section className="card space-y-3">
        <h2 className="text-lg font-bold">Version history · {businessDay}</h2>
        {loading ? <p role="status">Loading closing history…</p> : historyItems.length ? (
          <ol className="space-y-3">
            {historyItems.map((closing) => (
              <li key={closing.id} className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex flex-wrap justify-between gap-2">
                  <p className="font-semibold">Version {closing.version} · {closingStatusLabel[closing.status]}</p>
                  <p className="text-sm">Submitted {dateTimeLabel(closing.submitted_at)}</p>
                </div>
                {closing.reviewed_at && <p className="text-sm">Reviewed {dateTimeLabel(closing.reviewed_at)}{closing.review_notes ? ` · ${closing.review_notes}` : ""}</p>}
                {closing.notes && <p className="text-sm">Notes: {closing.notes}</p>}
                {closing.difference_notes && <p className="text-sm">Differences: {closing.difference_notes}</p>}
                <details>
                  <summary className="cursor-pointer text-sm font-semibold">Snapshot totals</summary>
                  <div className="pt-3"><TotalsView totals={closing.totals} /></div>
                </details>
              </li>
            ))}
          </ol>
        ) : <p className="text-sm">No closing has been submitted for this date.</p>}
      </section>
    </div>
  );
}
