import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api, downloadCsv } from "../api";
import { useAuth } from "../auth";

interface ExpenseCategory {
  code: string;
  label: string;
  is_active: boolean;
}

interface PaymentMethod {
  code: string;
  label: string;
}

interface ExpenseEvent {
  at: string;
  actor_id: number | null;
  action: string;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
  reason: string | null;
}

interface Expense {
  id: number;
  ref: string;
  expense_date: string;
  payment_date: string;
  category: string;
  category_label: string;
  description: string;
  amount: string;
  method: string;
  vendor: string | null;
  memo_no: string | null;
  has_physical_memo: boolean;
  trx_id: string | null;
  bank_ref: string | null;
  sms_text: string | null;
  entered_by: number;
  status: "pending" | "approved" | "rejected";
  approved_by: number | null;
  approved_at: string | null;
  rejection_reason: string | null;
  notes: string | null;
  created_at: string;
  events?: ExpenseEvent[];
}

interface ExpenseDraft {
  expense_date: string;
  payment_date: string;
  category: string;
  description: string;
  amount: string;
  method: string;
  vendor: string;
  memo_no: string;
  has_physical_memo: boolean;
  trx_id: string;
  bank_ref: string;
  sms_text: string;
  notes: string;
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
const statusLabel: Record<Expense["status"], string> = {
  pending: "◷ Pending approval",
  approved: "✓ Approved",
  rejected: "⊘ Rejected",
};
const emptyDraft = (): ExpenseDraft => ({
  expense_date: businessDate(),
  payment_date: businessDate(),
  category: "",
  description: "",
  amount: "",
  method: "cash",
  vendor: "",
  memo_no: "",
  has_physical_memo: false,
  trx_id: "",
  bank_ref: "",
  sms_text: "",
  notes: "",
});
const draftFromExpense = (expense: Expense): ExpenseDraft => ({
  expense_date: expense.expense_date,
  payment_date: expense.payment_date,
  category: expense.category,
  description: expense.description,
  amount: expense.amount,
  method: expense.method,
  vendor: expense.vendor ?? "",
  memo_no: expense.memo_no ?? "",
  has_physical_memo: expense.has_physical_memo,
  trx_id: expense.trx_id ?? "",
  bank_ref: expense.bank_ref ?? "",
  sms_text: expense.sms_text ?? "",
  notes: expense.notes ?? "",
});

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function ExpenseFields({
  value,
  onChange,
  categories,
  methods,
  reason,
  onReasonChange,
}: {
  value: ExpenseDraft;
  onChange: (value: ExpenseDraft) => void;
  categories: ExpenseCategory[];
  methods: PaymentMethod[];
  reason?: string;
  onReasonChange?: (value: string) => void;
}) {
  const set = <K extends keyof ExpenseDraft>(key: K, next: ExpenseDraft[K]) => {
    onChange({ ...value, [key]: next });
  };
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
      <label className="space-y-1">
        <span className="text-sm font-semibold">Expense date</span>
        <input className="field" type="date" required value={value.expense_date} onChange={(event) => set("expense_date", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Payment date</span>
        <input className="field" type="date" required value={value.payment_date} onChange={(event) => set("payment_date", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Category</span>
        <select className="field" required value={value.category} onChange={(event) => set("category", event.target.value)}>
          <option value="">Select category</option>
          {categories.filter((category) => category.is_active).map((category) => (
            <option key={category.code} value={category.code}>{category.label}</option>
          ))}
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Payment method</span>
        <select className="field" required value={value.method} onChange={(event) => set("method", event.target.value)}>
          {methods.map((method) => <option key={method.code} value={method.code}>{method.label}</option>)}
        </select>
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Description</span>
        <input className="field" required minLength={2} maxLength={500} value={value.description} onChange={(event) => set("description", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Amount (৳)</span>
        <input className="field" type="number" min="0.01" step="0.01" required value={value.amount} onChange={(event) => set("amount", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Vendor / recipient</span>
        <input className="field" maxLength={160} value={value.vendor} onChange={(event) => set("vendor", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Memo number</span>
        <input className="field" maxLength={120} value={value.memo_no} onChange={(event) => set("memo_no", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">MFS transaction ID</span>
        <input className="field" maxLength={120} value={value.trx_id} onChange={(event) => set("trx_id", event.target.value)} />
      </label>
      <label className="space-y-1">
        <span className="text-sm font-semibold">Bank reference</span>
        <input className="field" maxLength={120} value={value.bank_ref} onChange={(event) => set("bank_ref", event.target.value)} />
      </label>
      <label className="flex min-h-11 items-center gap-2 text-sm sm:col-span-2">
        <input type="checkbox" checked={value.has_physical_memo} onChange={(event) => set("has_physical_memo", event.target.checked)} />
        A physical memo / receipt is on file
      </label>
      <label className="space-y-1 sm:col-span-2">
        <span className="text-sm font-semibold">Pasted SMS (not proof of payment)</span>
        <textarea className="field min-h-20" maxLength={2000} value={value.sms_text} onChange={(event) => set("sms_text", event.target.value)} />
      </label>
      <label className="space-y-1 sm:col-span-2">
        <span className="text-sm font-semibold">Notes</span>
        <textarea className="field min-h-16" maxLength={1000} value={value.notes} onChange={(event) => set("notes", event.target.value)} />
      </label>
      {onReasonChange && (
        <label className="space-y-1 sm:col-span-2">
          <span className="text-sm font-semibold">Correction reason (required)</span>
          <input className="field" minLength={3} maxLength={500} required value={reason ?? ""} onChange={(event) => onReasonChange(event.target.value)} />
        </label>
      )}
    </div>
  );
}

export default function Expenses() {
  const { user, can } = useAuth();
  const [categories, setCategories] = useState<ExpenseCategory[]>([]);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [draft, setDraft] = useState<ExpenseDraft>(emptyDraft);
  const [editDraft, setEditDraft] = useState<ExpenseDraft | null>(null);
  const [editing, setEditing] = useState<Expense | null>(null);
  const [details, setDetails] = useState<Expense | null>(null);
  const [items, setItems] = useState<PageList<Expense> | null>(null);
  const [filters, setFilters] = useState({
    ref: "", date_from: "", date_to: "", amount: "", category: "",
    vendor: "", method: "", trx_id: "", memo_no: "", status: "",
  });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [page, setPage] = useState(1);
  const [newCategoryCode, setNewCategoryCode] = useState("");
  const [newCategoryLabel, setNewCategoryLabel] = useState("");
  const [correctionReason, setCorrectionReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [exporting, setExporting] = useState(false);
  const canEnter = can("expense.enter");
  const canApprove = can("expense.approve");
  const canConfigure = can("expense.configure");

  const loadMetadata = useCallback(async () => {
    try {
      const [categoryResult, methodResult] = await Promise.all([
        api<{ items: ExpenseCategory[] }>("/expense-categories"),
        api<{ items: PaymentMethod[] }>("/payments/methods"),
      ]);
      setCategories(categoryResult.items);
      setMethods(methodResult.items);
      setDraft((current) => ({
        ...current,
        category: current.category || categoryResult.items.find((item) => item.is_active)?.code || "",
        method: current.method || methodResult.items[0]?.code || "cash",
      }));
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  const loadExpenses = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), size: "20" });
      Object.entries(appliedFilters).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      setItems(await api<PageList<Expense>>(`/expenses?${params.toString()}`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [appliedFilters, page]);

  useEffect(() => { void loadMetadata(); }, [loadMetadata]);
  useEffect(() => { void loadExpenses(); }, [loadExpenses]);

  const createExpense = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const created = await api<Expense>("/expenses", { method: "POST", body: draft });
      setNotice(`Saved ${created.ref}. Write this reference on the physical memo for easy matching.`);
      setDraft({ ...emptyDraft(), category: categories.find((item) => item.is_active)?.code ?? "", method: methods[0]?.code ?? "cash" });
      await loadExpenses();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const search = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setAppliedFilters(filters);
  };

  const exportExpenses = async () => {
    setExporting(true);
    setError("");
    try {
      const params = new URLSearchParams();
      Object.entries(appliedFilters).forEach(([key, value]) => {
        if (value) params.set(key, value);
      });
      const query = params.toString();
      await downloadCsv(`/exports/expenses.csv${query ? `?${query}` : ""}`, "expenses.csv");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setExporting(false);
    }
  };

  const openDetails = async (expense: Expense) => {
    setError("");
    try {
      setDetails(await api<Expense>(`/expenses/${encodeURIComponent(expense.ref)}`));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const correct = async (event: FormEvent) => {
    event.preventDefault();
    if (!editing || !editDraft) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const updated = await api<Expense>(`/expenses/${editing.id}`, {
        method: "PATCH",
        body: { ...editDraft, reason: correctionReason },
      });
      setNotice(`${updated.ref} corrected. Its approval was reset; it must be approved again.`);
      setEditing(null);
      setEditDraft(null);
      setCorrectionReason("");
      await loadExpenses();
      if (details?.ref === updated.ref) await openDetails(updated);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const approve = async (expense: Expense) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await api(`/expenses/${expense.id}/approve`, { method: "POST" });
      setNotice(`${expense.ref} approved.`);
      await loadExpenses();
      if (details?.ref === expense.ref) await openDetails(expense);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reject = async (expense: Expense) => {
    const reason = window.prompt("Reason for rejecting this expense?");
    if (!reason?.trim()) return;
    setBusy(true);
    setError("");
    try {
      await api(`/expenses/${expense.id}/reject`, { method: "POST", body: { reason } });
      setNotice(`${expense.ref} rejected. The rejection is recorded in its history.`);
      await loadExpenses();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const addCategory = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setNotice("");
    try {
      await api("/expense-categories", {
        method: "POST",
        body: { code: newCategoryCode, label: newCategoryLabel },
      });
      setNewCategoryCode("");
      setNewCategoryLabel("");
      setNotice("Expense category added.");
      await loadMetadata();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const toggleCategory = async (category: ExpenseCategory) => {
    setError("");
    try {
      await api(`/expense-categories/${encodeURIComponent(category.code)}`, {
        method: "PATCH",
        body: { is_active: !category.is_active },
      });
      await loadMetadata();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const filterFields = useMemo(() => [
    ["ref", "Reference"], ["date_from", "Expense date from"], ["date_to", "Expense date to"],
    ["amount", "Exact amount"], ["vendor", "Vendor / recipient"], ["trx_id", "MFS transaction ID"],
    ["memo_no", "Memo number"],
  ] as const, []);

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Expenses</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Expenses remain pending until independently approved. Corrections are recorded and may require reapproval.</p>
      </header>
      <ErrorNotice message={error} />
      {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>}

      {canEnter && (
        <section className="card space-y-4">
          <h2 className="text-lg font-bold">Record expense</h2>
          <form className="space-y-4" onSubmit={(event) => void createExpense(event)}>
            <ExpenseFields value={draft} onChange={setDraft} categories={categories} methods={methods} />
            <button className="btn w-full sm:w-auto" disabled={busy || !categories.some((item) => item.is_active) || !methods.length}>
              {busy ? "Saving…" : "Save pending expense"}
            </button>
          </form>
        </section>
      )}

      {editing && editDraft && (
        <section className="card space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-bold">Correct {editing.ref}</h2>
            <button type="button" className="btn-o" onClick={() => { setEditing(null); setEditDraft(null); }}>Cancel</button>
          </div>
          <p className="text-sm">The old values will remain in the event history. If previously approved, the corrected expense returns to pending.</p>
          <form className="space-y-4" onSubmit={(event) => void correct(event)}>
            <ExpenseFields
              value={editDraft}
              onChange={setEditDraft}
              categories={categories}
              methods={methods}
              reason={correctionReason}
              onReasonChange={setCorrectionReason}
            />
            <button className="btn" disabled={busy}>{busy ? "Saving…" : "Save correction"}</button>
          </form>
        </section>
      )}

      {canConfigure && (
        <section className="card space-y-3">
          <h2 className="text-lg font-bold">Expense categories</h2>
          <form className="grid grid-cols-1 gap-2 sm:grid-cols-[1fr_2fr_auto]" onSubmit={(event) => void addCategory(event)}>
            <label className="space-y-1"><span className="text-sm font-semibold">Code</span><input className="field" required pattern="[a-z][a-z0-9_]{1,31}" value={newCategoryCode} onChange={(event) => setNewCategoryCode(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Label</span><input className="field" required minLength={2} maxLength={80} value={newCategoryLabel} onChange={(event) => setNewCategoryLabel(event.target.value)} /></label>
            <button className="btn-o self-end">Add</button>
          </form>
          <ul className="space-y-2 text-sm">
            {categories.map((category) => <li key={category.code} className="flex items-center justify-between gap-2">
              <span>{category.label} · {category.is_active ? "✓ Active" : "⊘ Inactive"}</span>
              <button type="button" className="btn-o" onClick={() => void toggleCategory(category)}>{category.is_active ? "Deactivate" : "Activate"}</button>
            </li>)}
          </ul>
        </section>
      )}

      <section className="card space-y-4">
        <h2 className="text-lg font-bold">Search expenses</h2>
        <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={search}>
          {filterFields.map(([key, label]) => (
            <label key={key} className="space-y-1">
              <span className="text-sm font-semibold">{label}</span>
              <input
                className="field"
                type={key.startsWith("date_") ? "date" : key === "amount" ? "number" : "search"}
                min={key === "amount" ? "0.01" : undefined}
                step={key === "amount" ? "0.01" : undefined}
                value={filters[key]}
                onChange={(event) => setFilters({ ...filters, [key]: event.target.value })}
              />
            </label>
          ))}
          <label className="space-y-1">
            <span className="text-sm font-semibold">Category</span>
            <select className="field" value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })}>
              <option value="">All categories</option>
              {categories.map((category) => <option key={category.code} value={category.code}>{category.label}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm font-semibold">Method</span>
            <select className="field" value={filters.method} onChange={(event) => setFilters({ ...filters, method: event.target.value })}>
              <option value="">All methods</option>
              {methods.map((method) => <option key={method.code} value={method.code}>{method.label}</option>)}
            </select>
          </label>
          <label className="space-y-1">
            <span className="text-sm font-semibold">Status</span>
            <select className="field" value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}>
              <option value="">All statuses</option>
              <option value="pending">◷ Pending</option>
              <option value="approved">✓ Approved</option>
              <option value="rejected">⊘ Rejected</option>
            </select>
          </label>
          <button className="btn-o self-end">Search</button>
        </form>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">{items?.total ?? 0} matching expenses</p>
          <button type="button" className="btn-o" disabled={exporting} onClick={() => void exportExpenses()}>
            {exporting ? "Exporting…" : "Export filtered CSV"}
          </button>
        </div>
        {loading ? <p role="status">Loading expenses…</p> : items?.items.length ? (
          <div className="space-y-3">
            {items.items.map((expense) => (
              <article key={expense.id} className="space-y-2 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold">{expense.ref} · {money(expense.amount)} · {statusLabel[expense.status]}</p>
                    <p className="text-sm">{expense.description} · {expense.category_label} · {expense.method.replace(/_/g, " ")}</p>
                    <p className="text-xs text-slate-600 dark:text-slate-300">{expense.expense_date} · paid {expense.payment_date}{expense.vendor ? ` · ${expense.vendor}` : ""}</p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className="btn-o" onClick={() => void openDetails(expense)}>History</button>
                    {canEnter && <button type="button" className="btn-o" onClick={() => {
                      setEditing(expense);
                      setEditDraft(draftFromExpense(expense));
                      setCorrectionReason("");
                    }}>Correct</button>}
                    {canApprove && expense.status === "pending" && (
                      expense.entered_by === user?.id
                        ? <span className="self-center text-xs">Entered by you · cannot approve</span>
                        : <>
                          <button type="button" className="btn-o" disabled={busy} onClick={() => void approve(expense)}>Approve</button>
                          <button type="button" className="btn-o" disabled={busy} onClick={() => void reject(expense)}>Reject</button>
                        </>
                    )}
                  </div>
                </div>
                {expense.memo_no && <p className="text-xs">Memo {expense.memo_no}{expense.has_physical_memo ? " · physical memo on file" : " · no physical memo"}</p>}
                {expense.rejection_reason && <p className="text-xs">Rejection: {expense.rejection_reason}</p>}
              </article>
            ))}
          </div>
        ) : <p className="text-sm">No matching expenses.</p>}
        {items && items.total > items.size && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-700">
            <button type="button" className="btn-o" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}>Previous</button>
            <span className="text-sm">Page {items.page} of {Math.ceil(items.total / items.size)}</span>
            <button type="button" className="btn-o" disabled={page * items.size >= items.total || loading} onClick={() => setPage((value) => value + 1)}>Next</button>
          </div>
        )}
      </section>

      {details && (
        <section className="card space-y-3" aria-label="Expense history">
          <div className="flex items-center justify-between gap-2">
            <h2 className="text-lg font-bold">{details.ref} · Event history</h2>
            <button type="button" className="btn-o" onClick={() => setDetails(null)}>Close</button>
          </div>
          <p>{details.description} · {money(details.amount)} · {statusLabel[details.status]}</p>
          <ol className="space-y-3">
            {details.events?.map((event, index) => (
              <li key={`${event.at}-${index}`} className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700">
                <p className="font-semibold">{event.action} · {event.at}</p>
                {event.reason && <p>Reason: {event.reason}</p>}
                {event.before && <details><summary>Before</summary><pre className="overflow-auto text-xs">{JSON.stringify(event.before, null, 2)}</pre></details>}
                {event.after && <details><summary>After</summary><pre className="overflow-auto text-xs">{JSON.stringify(event.after, null, 2)}</pre></details>}
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}
