import { useEffect, useState } from "react";
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

interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

interface StatementContent {
  business_name: string;
  period: string;
  approved_at: string;
  report_reference: string;
  calculation_basis: string;
  collections: string;
  approved_expenses: string;
  final_result: string;
  distribution_pool: string;
  total_eligible_shares: number;
  per_share: string | null;
  shareholder_name: string;
  shareholder_shares: number;
  calculated_allocation: string;
  retained_amount: string;
  payout_status: "calculated" | "declared" | "paid";
  payout_note: string;
  approved_expense_items: {
    ref: string;
    payment_date: string;
    category: string;
    description: string;
    amount: string;
    method: string;
  }[];
  exception_reason: string | null;
}

interface StatementRecord {
  id: number;
  snapshot_id: number;
  generated_at: string;
  content: StatementContent;
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
function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function useShareholderData() {
  const [holding, setHolding] = useState<Shareholding | null>(null);
  const [reports, setReports] = useState<ApprovedReport[]>([]);
  const [reportPage, setReportPage] = useState(1);
  const [reportTotal, setReportTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    Promise.all([
      api<Shareholding>("/my/shareholding"),
      api<PageResult<ApprovedReport>>(`/reports/approved?page=${reportPage}&size=20`),
    ]).then(([ownHolding, approved]) => {
      if (active) {
        setHolding(ownHolding);
        setReports(approved.items);
        setReportTotal(approved.total);
      }
    }).catch((err) => { if (active) setError((err as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reportPage]);

  return { holding, reports, reportPage, reportTotal, setReportPage, loading, error };
}

export function ShareholderOverview() {
  const { holding, reports, reportPage, reportTotal, setReportPage, loading, error } = useShareholderData();
  const reportPageCount = Math.ceil(reportTotal / 20);
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
          {reportPageCount > 1 && (
            <nav aria-label="Approved report pages" className="flex items-center justify-between gap-3 pt-2">
              <button type="button" className="btn-o min-h-11" disabled={reportPage <= 1} onClick={() => setReportPage((page) => page - 1)}>Previous</button>
              <span className="text-sm">Page {reportPage} of {reportPageCount}</span>
              <button type="button" className="btn-o min-h-11" disabled={reportPage >= reportPageCount} onClick={() => setReportPage((page) => page + 1)}>Next</button>
            </nav>
          )}
        </section>
      )}
    </div>
  );
}

export function ShareholderStatement() {
  const [statements, setStatements] = useState<StatementRecord[]>([]);
  const [statementPage, setStatementPage] = useState(1);
  const [statementTotal, setStatementTotal] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError("");
    api<PageResult<StatementRecord>>(`/statements/mine?page=${statementPage}&size=20`)
      .then((result) => {
        if (active) {
          setStatements(result.items);
          setStatementTotal(result.total);
          setSelectedId(null);
        }
      })
      .catch((err) => { if (active) setError((err as Error).message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [statementPage]);

  const selected = statements.find((statement) => statement.id === selectedId) ?? statements[0];
  const content = selected?.content;

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">My shareholder statement</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Your immutable approved statement · management information, not a promise of dividends.</p>
      </header>
      <ErrorNotice message={error} />
      {loading ? <p role="status">Loading statement…</p> : !statements.length ? (
        <section className="card"><p>No approved statement is available yet.</p></section>
      ) : (
        <>
          <div className="no-print flex flex-wrap items-end gap-3">
            <label className="min-w-48 flex-1 space-y-1">
              <span className="text-sm font-semibold">Approved statement</span>
              <select className="field" value={selected?.id ?? ""} onChange={(event) => setSelectedId(Number(event.target.value))}>
                {statements.map((statement) => (
                  <option key={statement.id} value={statement.id}>
                    {statement.content.period} · {statement.content.report_reference}
                  </option>
                ))}
              </select>
            </label>
            <button type="button" className="btn-o" onClick={() => window.print()}>Print statement</button>
          </div>
          {content && (
            <>
              <section className="card space-y-3">
                <h2 className="text-xl font-bold">{content.business_name}</h2>
                <p className="font-semibold">{content.report_reference} · {content.period}</p>
                <p className="text-sm">Approved {dateTimeLabel(content.approved_at)} · statement generated {dateTimeLabel(selected.generated_at)}</p>
                <p className="text-sm">{content.calculation_basis}</p>
                <dl className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  <div className="rounded border p-3"><dt className="text-sm">Verified collections</dt><dd className="font-semibold">{money(content.collections)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Approved expenses</dt><dd className="font-semibold">{money(content.approved_expenses)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Final result</dt><dd className="font-semibold">{money(content.final_result)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Distribution pool</dt><dd className="font-semibold">{money(content.distribution_pool)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Total eligible shares</dt><dd className="font-semibold">{content.total_eligible_shares.toLocaleString()}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Amount per share</dt><dd className="font-semibold">{money(content.per_share)}</dd></div>
                  <div className="rounded border p-3"><dt className="text-sm">Retained amount</dt><dd className="font-semibold">{money(content.retained_amount)}</dd></div>
                </dl>
                <div className="rounded-lg bg-emerald-50 p-4 dark:bg-emerald-950/30">
                  <h3 className="font-bold">Your allocation</h3>
                  <p>{content.shareholder_name} · {content.shareholder_shares.toLocaleString()} share(s) × {money(content.per_share)} = {money(content.calculated_allocation)}</p>
                  <p className="text-sm">Payout status: {content.payout_status === "calculated" ? "Calculated · not paid" : content.payout_status}</p>
                  <p className="text-sm">{content.payout_note}</p>
                </div>
                {content.exception_reason && <p className="text-sm">Documented approval exception: {content.exception_reason}</p>}
              </section>
              <section className="card space-y-3">
                <h2 className="text-lg font-bold">Approved expenses in this snapshot</h2>
                {content.approved_expense_items.length ? (
                  <div className="space-y-2">
                    {content.approved_expense_items.map((expense) => (
                      <article key={expense.ref} className="rounded border p-3 text-sm">
                        <p className="font-semibold">{expense.ref} · {money(expense.amount)} · ✓ Approved</p>
                        <p>{expense.payment_date} · {expense.category} · {expense.method.replace(/_/g, " ")}</p>
                        <p>{expense.description}</p>
                      </article>
                    ))}
                  </div>
                ) : <p className="text-sm">No approved expense details were recorded in this snapshot.</p>}
              </section>
            </>
          )}
          {statementTotal > 20 && (
            <nav aria-label="Statement pages" className="no-print flex items-center justify-between gap-3">
              <button type="button" className="btn-o min-h-11" disabled={statementPage <= 1} onClick={() => setStatementPage((page) => page - 1)}>Previous</button>
              <span className="text-sm">Page {statementPage} of {Math.ceil(statementTotal / 20)}</span>
              <button type="button" className="btn-o min-h-11" disabled={statementPage >= Math.ceil(statementTotal / 20)} onClick={() => setStatementPage((page) => page + 1)}>Next</button>
            </nav>
          )}
        </>
      )}
    </div>
  );
}
