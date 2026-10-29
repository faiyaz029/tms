import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface MethodTotal {
  count: number;
  amount: string;
}

interface ReportTotals {
  verified_collections: { amount: string; by_method: Record<string, MethodTotal> };
  payments_by_status: Record<string, Record<string, MethodTotal>>;
  unverified_payments: { amount: string; count: number };
  approved_expenses: { amount: string; by_method: Record<string, MethodTotal> };
  expenses_by_status: Record<string, Record<string, MethodTotal>>;
  pending_expenses: { amount: string; count: number };
  operating_result: string;
  eligible_shares: number;
  shareholder_shares_allocated: number;
  allocation_error: boolean;
  per_share: string | null;
  pool: string | null;
  retained_amount: string | null;
  remainder: string | null;
}

interface ChecklistItem {
  key: string;
  label: string;
  is_done: boolean;
  done_by: number | null;
  done_at: string | null;
  note: string | null;
}

interface Allocation {
  shareholder_id: number;
  name: string;
  shares: number;
  amount: string;
}

interface ReportInput {
  ref?: string;
  amount: string;
  method?: string;
  status?: string;
  received_at?: string | null;
  payment_date?: string;
  category?: string;
  description?: string;
}

interface ReportSnapshot {
  id: number;
  version: number;
  created_at: string;
  approver_name: string;
  calculation_basis: string;
  inputs: { payments: ReportInput[]; expenses: ReportInput[] };
  totals: ReportTotals;
  allocations: Allocation[];
  total_shares: number;
  pool: string;
  remainder: string;
  exception_reason: string | null;
}

interface Report {
  year: number;
  month: number;
  status: "preliminary" | "under_review" | "approved" | "reopened";
  stage: string;
  version: number;
  review_note: string | null;
  calculation_basis: string;
  inputs: {
    period_start: string;
    period_end: string;
    payments: ReportInput[];
    expenses: ReportInput[];
    shareholders: { shareholder_id: number; name: string; shares: number }[];
  };
  totals: ReportTotals;
  allocations: Allocation[];
  checklist: ChecklistItem[];
  distribution: {
    pool_amount: string;
    retained_amount: string;
    reason: string;
  } | null;
  unresolved: {
    received_payments: number;
    pending_expenses: number;
    daily_closings: { business_date: string; version: number }[];
    register_confirmed: boolean;
  };
  history: ReportSnapshot[];
  reopenings: {
    previous_version: number;
    new_version: number;
    reason: string;
    authorized_by: number;
    at: string;
  }[];
}

interface Shareholder {
  id: number;
  name: string;
  email: string;
  user_id: number | null;
  linked_user_name: string | null;
  is_active: boolean;
  notes: string | null;
  acquisition_amount: string | null;
  holdings: { id: number; shares: number; effective_from: string; effective_to: string | null }[];
}

const businessMonth = () => new Intl.DateTimeFormat("sv-SE", {
  timeZone: "Asia/Dhaka", year: "numeric", month: "2-digit",
}).format(new Date()).slice(0, 7);
const money = (amount: string | null | undefined) => amount === null || amount === undefined
  ? "—"
  : `৳${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const dateTimeLabel = (value: string) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));
const methodLabel = (value: string) => value === "online_simulated"
  ? "SIMULATED PAYMENT"
  : value.replace(/_/g, " ");
const reportUrl = (period: string) => {
  const [year, month] = period.split("-");
  return `/reports/${year}/${Number(month)}`;
};

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function MethodRows({ items }: { items: Record<string, MethodTotal> }) {
  const methods = Object.entries(items);
  return methods.length ? (
    <ul className="space-y-1 text-sm">
      {methods.map(([method, total]) => (
        <li key={method} className="flex justify-between gap-2">
          <span>{methodLabel(method)} · {total.count} record(s)</span><b>{money(total.amount)}</b>
        </li>
      ))}
    </ul>
  ) : <p className="text-sm text-slate-500">None recorded.</p>;
}

function ReportTotalsView({ report }: { report: Report }) {
  const totals = report.totals;
  return (
    <div className="space-y-4">
      <p className="rounded-lg bg-slate-100 p-3 text-sm dark:bg-slate-800">{report.calculation_basis}</p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <h3 className="font-bold">Verified collections · received date basis</h3>
          <p className="my-2 text-xl font-bold">{money(totals.verified_collections.amount)}</p>
          <MethodRows items={totals.verified_collections.by_method} />
        </section>
        <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
          <h3 className="font-bold">Approved expenses · payment date basis</h3>
          <p className="my-2 text-xl font-bold">{money(totals.approved_expenses.amount)}</p>
          <MethodRows items={totals.approved_expenses.by_method} />
        </section>
      </div>
      <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <h3 className="font-bold">Operating result</h3>
        <p className="text-2xl font-bold">{money(totals.operating_result)}</p>
        <p className="text-sm">Verified collections minus approved expenses.</p>
      </section>
      <section className="rounded-lg border border-amber-300 bg-amber-50 p-3 dark:bg-amber-950/30">
        <h3 className="font-bold">Pending and excluded items</h3>
        <p className="text-sm">Payments awaiting verification: {totals.unverified_payments.count} · {money(totals.unverified_payments.amount)}</p>
        <p className="text-sm">Pending expenses: {totals.pending_expenses.count} · {money(totals.pending_expenses.amount)}</p>
        {Object.entries(totals.payments_by_status)
          .filter(([status]) => status !== "verified")
          .map(([status, methods]) => (
            <div key={status} className="mt-2 text-sm">
              <b>Payments · {status}</b><MethodRows items={methods} />
            </div>
          ))}
        {Object.entries(totals.expenses_by_status)
          .filter(([status]) => status !== "approved")
          .map(([status, methods]) => (
            <div key={status} className="mt-2 text-sm">
              <b>Expenses · {status}</b><MethodRows items={methods} />
            </div>
          ))}
      </section>
      <section className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <h3 className="font-bold">Distribution and allocations</h3>
        <p className="text-sm">Eligible shares: {totals.eligible_shares.toLocaleString()} · Registered at month end: {totals.shareholder_shares_allocated.toLocaleString()}</p>
        {totals.allocation_error && <p role="alert" className="text-sm font-bold text-red-700">Shareholdings exceed the eligible share count.</p>}
        <p className="text-sm">Distribution pool: {money(totals.pool)} · Retained: {money(totals.retained_amount)}</p>
        <p className="text-sm">Per share: {money(totals.per_share)} · Rounding / unallocated remainder: {money(totals.remainder)}</p>
        {report.allocations.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[400px] text-left text-sm">
              <thead><tr><th className="p-2">Shareholder</th><th className="p-2">Shares</th><th className="p-2">Allocation</th></tr></thead>
              <tbody>{report.allocations.map((allocation) => (
                <tr key={allocation.shareholder_id} className="border-t border-slate-200 dark:border-slate-700">
                  <td className="p-2">{allocation.name}</td><td className="p-2">{allocation.shares}</td><td className="p-2">{money(allocation.amount)}</td>
                </tr>
              ))}</tbody>
              <tfoot><tr className="border-t font-semibold"><td className="p-2" colSpan={2}>Rounding / unallocated remainder</td><td className="p-2">{money(totals.remainder)}</td></tr></tfoot>
            </table>
          </div>
        ) : <p className="mt-2 text-sm">No month-end shareholdings are registered.</p>}
      </section>
      <details className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
        <summary className="cursor-pointer font-semibold">Calculation inputs and source records</summary>
        <p className="mt-2 text-sm">Period: {report.inputs.period_start} through {report.inputs.period_end}; holdings as of {report.inputs.period_end}.</p>
        <h4 className="mt-3 font-semibold">Payments</h4>
        {report.inputs.payments.length ? report.inputs.payments.map((payment) => (
          <p key={payment.ref} className="text-sm">{payment.ref} · {payment.status} · {methodLabel(payment.method ?? "")} · {money(payment.amount)} · received {payment.received_at}</p>
        )) : <p className="text-sm">No payments received in this period.</p>}
        <h4 className="mt-3 font-semibold">Expenses</h4>
        {report.inputs.expenses.length ? report.inputs.expenses.map((expense) => (
          <p key={expense.ref} className="text-sm">{expense.ref} · {expense.status} · {expense.category} · {expense.description} · {money(expense.amount)} · paid {expense.payment_date}</p>
        )) : <p className="text-sm">No expenses paid in this period.</p>}
      </details>
    </div>
  );
}

export default function Reports() {
  const { can } = useAuth();
  const [period, setPeriod] = useState(businessMonth);
  const [report, setReport] = useState<Report | null>(null);
  const [shareholders, setShareholders] = useState<Shareholder[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [eligibleShares, setEligibleShares] = useState("50");
  const [eligibleReason, setEligibleReason] = useState("");
  const [poolAmount, setPoolAmount] = useState("");
  const [distributionReason, setDistributionReason] = useState("");
  const [exceptionReason, setExceptionReason] = useState("");
  const [reopenReason, setReopenReason] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [holderName, setHolderName] = useState("");
  const [holderEmail, setHolderEmail] = useState("");
  const [holderUserId, setHolderUserId] = useState("");
  const [holderShares, setHolderShares] = useState("");
  const [holderEffectiveFrom, setHolderEffectiveFrom] = useState("");
  const [holderReason, setHolderReason] = useState("");
  const canPrepare = can("report.prepare");
  const canApprove = can("report.approve");
  const canManageShareholders = can("shareholder.manage");

  const loadShareholders = useCallback(async () => {
    if (!canManageShareholders) return;
    try {
      const result = await api<{ items: Shareholder[] }>("/shareholders");
      setShareholders(result.items);
    } catch (err) {
      setError((err as Error).message);
    }
  }, [canManageShareholders]);

  const loadReport = useCallback(async () => {
    if (!/^\d{4}-\d{2}$/.test(period)) return;
    setLoading(true);
    setError("");
    try {
      const result = await api<Report>(reportUrl(period));
      setReport(result);
      setEligibleShares(String(result.totals.eligible_shares));
      setPoolAmount(result.distribution?.pool_amount ?? "");
      setReviewNote(result.review_note ?? "");
    } catch (err) {
      setError((err as Error).message);
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, [period]);

  useEffect(() => { void loadReport(); }, [loadReport]);
  useEffect(() => { void loadShareholders(); }, [loadShareholders]);

  const run = async (operation: () => Promise<unknown>, success: string) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await operation();
      setNotice(success);
      await loadReport();
      await loadShareholders();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const setChecklist = (item: ChecklistItem, isDone: boolean, note = item.note ?? "") => run(
    () => api(reportUrl(period) + `/checklist/${encodeURIComponent(item.key)}`, {
      method: "PATCH",
      body: { is_done: isDone, note },
    }),
    `${item.label} ${isDone ? "confirmed" : "reopened"}.`,
  );

  const saveEligibleShares = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => api(reportUrl(period) + "/eligible-shares", {
        method: "POST",
        body: { total_shares: Number(eligibleShares), reason: eligibleReason },
      }),
      "Eligible share count confirmed.",
    );
    setEligibleReason("");
  };

  const saveDistribution = (event: FormEvent) => {
    event.preventDefault();
    const [year, month] = period.split("-");
    void run(
      () => api("/distribution", {
        method: "POST",
        body: {
          year: Number(year),
          month: Number(month),
          pool_amount: poolAmount,
          reason: distributionReason,
        },
      }),
      "Distribution pool saved.",
    );
    setDistributionReason("");
  };

  const submitReview = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => api(reportUrl(period) + "/submit-review", {
        method: "POST",
        body: { note: reviewNote },
      }),
      "Report submitted for review.",
    );
  };

  const approve = () => run(
    () => api(reportUrl(period) + "/approve", {
      method: "POST",
      body: { exception_reason: exceptionReason || null },
    }),
    "Report approved. Its snapshot is immutable.",
  );

  const reopen = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => api(reportUrl(period) + "/reopen", {
        method: "POST",
        body: { reason: reopenReason },
      }),
      "Report reopened as a new version; the prior snapshot remains unchanged.",
    );
    setReopenReason("");
  };

  const addShareholder = (event: FormEvent) => {
    event.preventDefault();
    void run(
      () => api("/shareholders", {
        method: "POST",
        body: {
          name: holderName,
          email: holderEmail,
          user_id: holderUserId ? Number(holderUserId) : null,
          shares: Number(holderShares),
          effective_from: holderEffectiveFrom,
          reason: holderReason,
        },
      }),
      "Shareholder and initial holding added.",
    );
    setHolderName("");
    setHolderEmail("");
    setHolderUserId("");
    setHolderShares("");
    setHolderEffectiveFrom("");
    setHolderReason("");
  };

  const addHolding = (holder: Shareholder, shares: string, effectiveFrom: string, reason: string) => run(
    () => api(`/shareholders/${holder.id}/holdings`, {
      method: "POST",
      body: { shares: Number(shares), effective_from: effectiveFrom, reason },
    }),
    `New effective-dated holding recorded for ${holder.name}.`,
  );

  const toggleHolder = (holder: Shareholder) => run(
    () => api(`/shareholders/${holder.id}`, {
      method: "PATCH",
      body: { is_active: !holder.is_active, reason: "Owner updated register activity state" },
    }),
    `${holder.name} ${holder.is_active ? "deactivated" : "activated"}.`,
  );

  const [year, month] = useMemo(() => period.split("-"), [period]);
  const isApproved = report?.status === "approved";

  return (
    <div className="space-y-5">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">Monthly financial report</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Cash-receipt basis · amounts in BDT · all business dates use Asia/Dhaka.</p>
        <label className="block max-w-xs space-y-1">
          <span className="text-sm font-semibold">Reporting month</span>
          <input className="field" type="month" value={period} onChange={(event) => setPeriod(event.target.value)} />
        </label>
      </header>
      <ErrorNotice message={error} />
      {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>}

      {loading ? <p role="status">Calculating report…</p> : report && (
        <>
          <section className="card space-y-4">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Version {report.version} · {year}-{month}</p>
                <h2 className="text-xl font-bold">{report.stage}</h2>
                {report.review_note && <p className="text-sm">Review notes: {report.review_note}</p>}
              </div>
              {report.status === "approved" && report.history[0] && (
                <p className="text-sm">Approved {dateTimeLabel(report.history[0].created_at)} by {report.history[0].approver_name}</p>
              )}
            </div>

            <ReportTotalsView report={report} />
            <div className="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700">
              <h3 className="text-lg font-bold">Preparation checklist</h3>
              <ul className="space-y-2">
                {report.checklist.map((item) => (
                  <li key={item.key} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                    <label className="flex min-h-11 items-center gap-3">
                      <input type="checkbox" checked={item.is_done} disabled={!canPrepare || isApproved || busy} onChange={(event) => void setChecklist(item, event.target.checked)} />
                      <span className="text-sm font-semibold">{item.is_done ? "✓ " : "◷ "}{item.label}</span>
                    </label>
                    {item.note && <p className="pl-8 text-sm">Note: {item.note}</p>}
                    {item.done_at && <p className="pl-8 text-xs text-slate-500">Confirmed {dateTimeLabel(item.done_at)}</p>}
                  </li>
                ))}
              </ul>
              {report.unresolved.received_payments > 0 && <p className="text-sm text-red-700">Received payments awaiting verification: {report.unresolved.received_payments}</p>}
              {report.unresolved.pending_expenses > 0 && <p className="text-sm text-red-700">Pending expenses: {report.unresolved.pending_expenses}</p>}
              {report.unresolved.daily_closings.length > 0 && <p className="text-sm text-red-700">Daily closings awaiting review: {report.unresolved.daily_closings.length}</p>}
            </div>

            {canPrepare && !isApproved && (
              <div className="grid grid-cols-1 gap-4 border-t border-slate-200 pt-4 dark:border-slate-700">
                <form className="space-y-2" onSubmit={saveEligibleShares}>
                  <h3 className="font-bold">Confirm total eligible shares</h3>
                  <label className="block max-w-xs space-y-1">
                    <span className="text-sm">Total eligible shares for {period}</span>
                    <input className="field" type="number" min="1" step="1" required value={eligibleShares} onChange={(event) => setEligibleShares(event.target.value)} />
                  </label>
                  <label className="block space-y-1">
                    <span className="text-sm">Reason / confirmation note</span>
                    <input className="field" minLength={3} maxLength={500} required value={eligibleReason} onChange={(event) => setEligibleReason(event.target.value)} />
                  </label>
                  <button className="btn-o" disabled={busy}>Confirm shares</button>
                </form>

                <form className="space-y-2" onSubmit={saveDistribution}>
                  <h3 className="font-bold">Distribution pool</h3>
                  <label className="block max-w-xs space-y-1">
                    <span className="text-sm">Pool amount (৳)</span>
                    <input className="field" type="number" min="0" step="0.01" required value={poolAmount} onChange={(event) => setPoolAmount(event.target.value)} />
                  </label>
                  <p className="text-sm">Retained amount is calculated as operating result minus the pool; it may be negative if the pool exceeds the result.</p>
                  <label className="block space-y-1">
                    <span className="text-sm">Reason for distribution decision</span>
                    <input className="field" minLength={3} maxLength={1000} required value={distributionReason} onChange={(event) => setDistributionReason(event.target.value)} />
                  </label>
                  <button className="btn-o" disabled={busy}>Save distribution pool</button>
                </form>
              </div>
            )}

            {canPrepare && (report.status === "preliminary" || report.status === "reopened") && (
              <form className="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700" onSubmit={submitReview}>
                <label className="block space-y-1">
                  <span className="text-sm font-semibold">Review notes</span>
                  <textarea className="field min-h-16" maxLength={1000} value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} />
                </label>
                <button className="btn" disabled={busy}>Submit for review</button>
              </form>
            )}

            {canApprove && report.status === "under_review" && (
              <section className="space-y-3 border-t border-slate-200 pt-4 dark:border-slate-700">
                <h3 className="font-bold">Approve report</h3>
                <p className="text-sm">Approval recomputes figures and stores an immutable snapshot. Incomplete checklist items or unresolved payments, expenses, and closings block approval unless this owner records an exception.</p>
                <label className="block space-y-1">
                  <span className="text-sm font-semibold">Documented exception reason (required only to override unresolved items)</span>
                  <textarea className="field min-h-16" maxLength={1000} value={exceptionReason} onChange={(event) => setExceptionReason(event.target.value)} />
                </label>
                <button type="button" className="btn" disabled={busy} onClick={() => void approve()}>Approve and snapshot</button>
              </section>
            )}

            {canApprove && isApproved && (
              <form className="space-y-2 border-t border-slate-200 pt-4 dark:border-slate-700" onSubmit={reopen}>
                <h3 className="font-bold">Reopen approved report</h3>
                <p className="text-sm">Reopening starts version {report.version + 1}; the approved snapshot above remains unchanged.</p>
                <label className="block space-y-1">
                  <span className="text-sm font-semibold">Reason (required)</span>
                  <textarea className="field min-h-16" minLength={3} maxLength={1000} required value={reopenReason} onChange={(event) => setReopenReason(event.target.value)} />
                </label>
                <button className="btn-o" disabled={busy}>Reopen as new version</button>
              </form>
            )}
          </section>

          <section className="card space-y-3">
            <h2 className="text-lg font-bold">Approved snapshot history</h2>
            {report.history.length ? report.history.map((snapshot) => (
              <details key={snapshot.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <summary className="cursor-pointer font-semibold">Version {snapshot.version} · Approved {dateTimeLabel(snapshot.created_at)} by {snapshot.approver_name}</summary>
                <div className="space-y-2 pt-3">
                  <p className="text-sm">Operating result {money(snapshot.totals.operating_result)} · pool {money(snapshot.pool)} · remainder {money(snapshot.remainder)}</p>
                  {snapshot.exception_reason && <p className="text-sm">Exception: {snapshot.exception_reason}</p>}
                  {snapshot.allocations.map((allocation) => <p key={allocation.shareholder_id} className="text-sm">{allocation.name} · {allocation.shares} share(s) · {money(allocation.amount)}</p>)}
                </div>
              </details>
            )) : <p className="text-sm">No approved snapshot exists for this period.</p>}
            {report.reopenings.map((reopening) => (
              <p key={`${reopening.previous_version}-${reopening.new_version}`} className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/30">
                Version {reopening.previous_version} reopened as version {reopening.new_version} by user {reopening.authorized_by} on {dateTimeLabel(reopening.at)}. Reason: {reopening.reason}
              </p>
            ))}
          </section>
        </>
      )}

      {canManageShareholders && (
        <section className="card space-y-4">
          <h2 className="text-lg font-bold">Shareholder register</h2>
          <p className="rounded-lg bg-amber-50 p-3 text-sm dark:bg-amber-950/30">Shares are never assigned automatically, including to developers. Link an existing shareholder-role account by its user ID, or leave it unlinked until the account exists.</p>
          <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={addShareholder}>
            <label className="space-y-1"><span className="text-sm font-semibold">Name</span><input className="field" minLength={2} maxLength={120} required value={holderName} onChange={(event) => setHolderName(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Email</span><input className="field" type="email" required value={holderEmail} onChange={(event) => setHolderEmail(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Existing shareholder user ID (optional)</span><input className="field" type="number" min="1" value={holderUserId} onChange={(event) => setHolderUserId(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Initial shares</span><input className="field" type="number" min="1" step="1" required value={holderShares} onChange={(event) => setHolderShares(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Effective from</span><input className="field" type="date" required value={holderEffectiveFrom} onChange={(event) => setHolderEffectiveFrom(event.target.value)} /></label>
            <label className="space-y-1 sm:col-span-2"><span className="text-sm font-semibold">Reason</span><input className="field" minLength={3} maxLength={500} required value={holderReason} onChange={(event) => setHolderReason(event.target.value)} /></label>
            <button className="btn sm:col-span-2" disabled={busy}>Add shareholder and holding</button>
          </form>
          {shareholders.length ? (
            <ul className="space-y-3">
              {shareholders.map((holder) => (
                <ShareholderRow key={holder.id} holder={holder} busy={busy} onAddHolding={addHolding} onToggle={toggleHolder} />
              ))}
            </ul>
          ) : <p className="text-sm">No shareholders are registered.</p>}
        </section>
      )}
    </div>
  );
}

function ShareholderRow({
  holder,
  busy,
  onAddHolding,
  onToggle,
}: {
  holder: Shareholder;
  busy: boolean;
  onAddHolding: (holder: Shareholder, shares: string, effectiveFrom: string, reason: string) => void;
  onToggle: (holder: Shareholder) => void;
}) {
  const [shares, setShares] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [reason, setReason] = useState("");
  const submit = (event: FormEvent) => {
    event.preventDefault();
    onAddHolding(holder, shares, effectiveFrom, reason);
    setShares("");
    setEffectiveFrom("");
    setReason("");
  };
  return (
    <li className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <div className="flex flex-wrap justify-between gap-2">
        <div>
          <p className="font-semibold">{holder.name} · {holder.is_active ? "✓ Active" : "⊘ Inactive"}</p>
          <p className="text-sm">{holder.email} · {holder.linked_user_name ? `linked to ${holder.linked_user_name}` : "no account linked"}</p>
          {holder.acquisition_amount && <p className="text-sm">Acquisition information only: {money(holder.acquisition_amount)}</p>}
        </div>
        <button type="button" className="btn-o" disabled={busy} onClick={() => onToggle(holder)}>{holder.is_active ? "Deactivate" : "Activate"}</button>
      </div>
      <ul className="space-y-1 text-sm">
        {holder.holdings.map((holding) => <li key={holding.id}>{holding.shares} share(s) · {holding.effective_from} through {holding.effective_to ?? "present"}</li>)}
      </ul>
      <form className="grid grid-cols-1 gap-2 border-t border-slate-200 pt-3 sm:grid-cols-2 dark:border-slate-700" onSubmit={submit}>
        <label className="space-y-1"><span className="text-xs font-semibold">New shares</span><input className="field" type="number" min="1" required value={shares} onChange={(event) => setShares(event.target.value)} /></label>
        <label className="space-y-1"><span className="text-xs font-semibold">Effective from</span><input className="field" type="date" required value={effectiveFrom} onChange={(event) => setEffectiveFrom(event.target.value)} /></label>
        <label className="space-y-1 sm:col-span-2"><span className="text-xs font-semibold">Reason</span><input className="field" minLength={3} required value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        <button className="btn-o sm:col-span-2" disabled={busy}>Record new holding version</button>
      </form>
    </li>
  );
}
