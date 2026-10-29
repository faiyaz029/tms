import { useEffect, useMemo, useState } from "react";
import { api } from "../api";

interface Shareholding {
  name: string;
  is_active: boolean;
  current_shares: number;
  holdings: { shares: number; effective_from: string; effective_to: string | null }[];
}

interface ApprovedReport {
  id: number;
  year: number;
  month: number;
  version: number;
  status: "approved" | "previously_approved";
  period_status: string;
  created_at: string;
  approver_name: string;
  calculation_basis: string;
  totals: {
    verified_collections: { amount: string };
    approved_expenses: { amount: string };
    operating_result: string;
    per_share: string | null;
    pool: string | null;
    retained_amount: string | null;
    remainder: string | null;
  };
  total_shares: number;
  pool: string;
  remainder: string;
  exception_reason: string | null;
  my_allocation: { shares: number; amount: string } | null;
}

interface ApprovedExpense {
  ref: string;
  payment_date: string;
  category: string;
  description: string;
  amount: string;
  method: string;
  status: string;
}

const money = (amount: string | null | undefined) => amount === null || amount === undefined
  ? "—"
  : `৳${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const dateTimeLabel = (value: string) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));
const periodLabel = (year: number, month: number) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", month: "long", year: "numeric",
}).format(new Date(Date.UTC(year, month - 1, 1)));
const reportKey = (report: ApprovedReport) => `${report.year}-${String(report.month).padStart(2, "0")}`;

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function useShareholderData() {
  const [holding, setHolding] = useState<Shareholding | null>(null);
  const [reports, setReports] = useState<ApprovedReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([
      api<Shareholding>("/my/shareholding"),
      api<{ items: ApprovedReport[] }>("/reports/approved"),
    ]).then(([ownHolding, approved]) => {
      setHolding(ownHolding);
      setReports(approved.items);
    }).catch((err) => setError((err as Error).message))
      .finally(() => setLoading(false));
  }, []);

  return { holding, reports, loading, error };
}

export function ShareholderOverview() {
  const { holding, reports, loading, error } = useShareholderData();
  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Shareholder overview</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Only approved report snapshots and your own allocation are shown here.</p>
      </header>
      <ErrorNotice message={error} />
      {loading ? <p role="status">Loading approved information…</p> : holding && (
        <section className="card space-y-2">
          <h2 className="text-lg font-bold">Your registered holding</h2>
          <p>{holding.name} · {holding.current_shares.toLocaleString()} share(s) effective today</p>
          {!holding.is_active && <p className="text-sm">Your register entry is inactive. Previous approved statements remain available.</p>}
          <h3 className="pt-2 font-semibold">Ownership history</h3>
          {holding.holdings.length ? holding.holdings.map((row, index) => (
            <p key={`${row.effective_from}-${index}`} className="text-sm">{row.shares} share(s) · {row.effective_from} through {row.effective_to ?? "present"}</p>
          )) : <p className="text-sm">No effective-dated holding is registered.</p>}
        </section>
      )}
      {!loading && (
        <section className="card space-y-3">
          <h2 className="text-lg font-bold">Approved report summaries</h2>
          <p className="text-sm">Cash-receipt basis. Preliminary and under-review figures are not available in the shareholder view.</p>
          {reports.length ? reports.map((report) => (
            <article key={report.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <p className="font-semibold">{periodLabel(report.year, report.month)} · {report.status === "approved" ? "✓ Approved / Final" : "◷ Previously approved · reopened"}</p>
              <p className="text-sm">Version {report.version} · Approved {dateTimeLabel(report.created_at)} by {report.approver_name}</p>
              <p className="text-sm">Operating result {money(report.totals.operating_result)} · distribution pool {money(report.pool)} · retained {money(report.totals.retained_amount)}</p>
              <p className="text-sm font-semibold">Your allocation: {report.my_allocation ? `${report.my_allocation.shares} share(s) · ${money(report.my_allocation.amount)}` : "No allocation in this snapshot"}</p>
              {report.exception_reason && <p className="text-sm">Documented approval exception: {report.exception_reason}</p>}
            </article>
          )) : <p className="text-sm">No approved reports are available yet.</p>}
        </section>
      )}
    </div>
  );
}

export function ShareholderStatement() {
  const { holding, reports, loading, error } = useShareholderData();
  const [selectedPeriod, setSelectedPeriod] = useState("");
  const [expenses, setExpenses] = useState<ApprovedExpense[]>([]);
  const [expenseError, setExpenseError] = useState("");
  const selected = useMemo(
    () => reports.find((report) => reportKey(report) === selectedPeriod) ?? reports[0],
    [reports, selectedPeriod],
  );

  useEffect(() => {
    if (!selected) {
      setExpenses([]);
      return;
    }
    let active = true;
    api<{ items: ApprovedExpense[] }>(`/reports/approved/${selected.year}/${selected.month}/expenses`)
      .then((result) => {
        if (active) {
          setExpenses(result.items);
          setExpenseError("");
        }
      })
      .catch((err) => {
        if (active) setExpenseError((err as Error).message);
      });
    return () => { active = false; };
  }, [selected]);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">My shareholder statement</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Approved snapshot only · cash-receipt basis · figures are management information, not a promise of dividends.</p>
      </header>
      <ErrorNotice message={error || expenseError} />
      {loading ? <p role="status">Loading statement…</p> : !reports.length ? (
        <section className="card"><p>No approved statement is available yet.</p></section>
      ) : (
        <>
          <label className="block max-w-sm space-y-1">
            <span className="text-sm font-semibold">Approved period</span>
            <select className="field" value={selected ? reportKey(selected) : ""} onChange={(event) => setSelectedPeriod(event.target.value)}>
              {reports.map((report) => <option key={report.id} value={reportKey(report)}>{periodLabel(report.year, report.month)} · version {report.version}</option>)}
            </select>
          </label>
          {selected && (
            <>
              <section className="card space-y-3">
                <h2 className="text-lg font-bold">{periodLabel(selected.year, selected.month)} · {selected.status === "approved" ? "Approved / Final" : "Previously approved · reopened"}</h2>
                <p className="text-sm">Approved {dateTimeLabel(selected.created_at)} by {selected.approver_name} · version {selected.version}</p>
                <p className="text-sm">{selected.calculation_basis}</p>
                <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded border p-3"><dt className="text-sm">Verified collections</dt><dd className="font-semibold">{money(selected.totals.verified_collections.amount)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Approved expenses</dt><dd className="font-semibold">{money(selected.totals.approved_expenses.amount)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Operating result</dt><dd className="font-semibold">{money(selected.totals.operating_result)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Distribution pool</dt><dd className="font-semibold">{money(selected.pool)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Amount per eligible share</dt><dd className="font-semibold">{money(selected.totals.per_share)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Rounding / unallocated remainder</dt><dd className="font-semibold">{money(selected.remainder)}</dd></div>
                </dl>
                <div className="rounded-lg bg-emerald-50 p-4 dark:bg-emerald-950/30">
                  <h3 className="font-bold">Your allocation</h3>
                  <p>{selected.my_allocation ? `${selected.my_allocation.shares.toLocaleString()} share(s) × ${money(selected.totals.per_share)} = ${money(selected.my_allocation.amount)}` : "This snapshot has no allocation for your register entry."}</p>
                  <p className="text-sm">Figures are calculated or declared by the business; this statement does not confirm that any amount has been paid.</p>
                </div>
                {holding && <p className="text-xs text-slate-500">Current register holding: {holding.current_shares.toLocaleString()} share(s). This report allocation uses the holding effective at the end of the report month.</p>}
                {selected.exception_reason && <p className="text-sm">Documented approval exception: {selected.exception_reason}</p>}
              </section>
              <section className="card space-y-3">
                <h2 className="text-lg font-bold">Approved expenses in this snapshot</h2>
                {expenses.length ? (
                  <div className="space-y-2">
                    {expenses.map((expense) => <article key={expense.ref} className="rounded border p-3 text-sm">
                      <p className="font-semibold">{expense.ref} · {money(expense.amount)} · ✓ Approved</p>
                      <p>{expense.payment_date} · {expense.category} · {expense.method.replace(/_/g, " ")}</p>
                      <p>{expense.description}</p>
                    </article>)}
                  </div>
                ) : <p className="text-sm">No approved expense details were recorded in this snapshot.</p>}
              </section>
            </>
          )}
        </>
      )}
    </div>
  );
}
