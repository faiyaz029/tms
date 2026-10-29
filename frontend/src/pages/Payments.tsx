import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";

interface PaymentMethod {
  code: string;
  label: string;
  requires_reference: boolean;
}

interface Payment {
  id: number;
  ref: string;
  booking_id: number;
  booking_ref: string | null;
  amount: string;
  currency: string;
  method: string;
  status: "pending" | "received" | "verified" | "rejected" | "failed" | "refunded";
  received_at: string | null;
  recorded_at: string;
  verified_at: string | null;
  trx_id: string | null;
  bank_ref: string | null;
  recorded_by: number | null;
  verified_by: number | null;
  rejection_reason: string | null;
}

interface Booking {
  id: number;
  ref: string;
  status: "draft" | "held" | "confirmed" | "cancelled" | "expired";
  total_amount: string;
  currency: string;
  hold_expires_at: string | null;
  customer: { name: string; phone: string };
}

interface PageList<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

interface Receipt extends Payment {
  booking_ref: string;
  customer_name: string;
  label: string | null;
  notice: string;
}

const money = (amount: string) => `৳${Number(amount).toLocaleString("en-US", {
  minimumFractionDigits: 2, maximumFractionDigits: 2,
})}`;
const dateTimeLabel = (value: string | null) => value
  ? new Intl.DateTimeFormat("en-BD", {
    timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value))
  : "—";
const statusLabel: Record<Payment["status"], string> = {
  pending: "◷ Pending",
  received: "⏳ Received · awaiting verification",
  verified: "✓ Verified",
  rejected: "⊘ Rejected",
  failed: "✕ Failed",
  refunded: "↩ Refunded",
};
const bookingStatusLabel: Record<Booking["status"], string> = {
  draft: "◷ Draft",
  held: "⏳ Held",
  confirmed: "✓ Confirmed",
  cancelled: "⊘ Cancelled",
  expired: "⌛ Expired",
};

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

export default function Payments() {
  const { can } = useAuth();
  const [payments, setPayments] = useState<PageList<Payment> | null>(null);
  const [methods, setMethods] = useState<PaymentMethod[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const [bookingRef, setBookingRef] = useState("");
  const [booking, setBooking] = useState<Booking | null>(null);
  const [method, setMethod] = useState("");
  const [amount, setAmount] = useState("");
  const [receivedAt, setReceivedAt] = useState(() => {
    const now = new Date();
    const dhaka = new Date(now.toLocaleString("en-US", { timeZone: "Asia/Dhaka" }));
    return `${dhaka.getFullYear()}-${String(dhaka.getMonth() + 1).padStart(2, "0")}-${String(dhaka.getDate()).padStart(2, "0")}T${String(dhaka.getHours()).padStart(2, "0")}:${String(dhaka.getMinutes()).padStart(2, "0")}`;
  });
  const [trxId, setTrxId] = useState("");
  const [bankRef, setBankRef] = useState("");
  const [senderPhone, setSenderPhone] = useState("");
  const [smsText, setSmsText] = useState("");
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const selectedMethod = methods.find((item) => item.code === method);

  const loadPayments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), size: "20" });
      if (statusFilter) params.set("status", statusFilter);
      const query = `?${params.toString()}`;
      setPayments(await api<PageList<Payment>>(`/payments${query}`));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter]);

  useEffect(() => { void loadPayments(); }, [loadPayments]);
  useEffect(() => {
    api<{ items: PaymentMethod[] }>("/payments/methods")
      .then((response) => {
        setMethods(response.items);
        setMethod(response.items[0]?.code ?? "");
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const findBooking = async (event: FormEvent) => {
    event.preventDefault();
    setBooking(null);
    setReceipt(null);
    setError("");
    setNotice("");
    try {
      setBooking(await api<Booking>(`/bookings/${encodeURIComponent(bookingRef.trim())}`));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const recordPayment = async (event: FormEvent) => {
    event.preventDefault();
    if (!booking) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const received = new Date(`${receivedAt}:00+06:00`).toISOString();
      const result = await api<Payment>(`/bookings/${booking.id}/payments`, {
        method: "POST",
        body: {
          amount,
          method,
          received_at: received,
          trx_id: trxId || undefined,
          bank_ref: bankRef || undefined,
          sender_phone: senderPhone || undefined,
          sms_text: smsText || undefined,
          notes: notes || undefined,
        },
      });
      setNotice(`Payment ${result.ref} recorded as received. It is not verified yet.`);
      setAmount("");
      setTrxId("");
      setBankRef("");
      setSenderPhone("");
      setSmsText("");
      setNotes("");
      await loadPayments();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const updatePayment = async (
    payment: Payment,
    action: "verify" | "reject",
    rejectionReason?: string,
  ) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (action === "reject" && !rejectionReason?.trim()) {
        setError("Enter a reason before rejecting a payment.");
        return;
      }
      await api(`/payments/${payment.id}/${action}`, {
        method: "POST",
        ...(action === "reject" ? { body: { reason: rejectionReason } } : {}),
      });
      setNotice(`Payment ${payment.ref} ${action === "verify" ? "verified" : "rejected"}.`);
      setReason("");
      await loadPayments();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const renewHold = async () => {
    if (!booking || !reason.trim()) {
      setError("Enter a reason before renewing the hold.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const renewed = await api<Booking>(`/bookings/${booking.id}/renew-hold`, {
        method: "POST",
        body: { reason },
      });
      setBooking(renewed);
      setNotice(`Hold for ${renewed.ref} renewed. Capacity was checked again.`);
      setReason("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const openReceipt = async (payment: Payment) => {
    setError("");
    try {
      setReceipt(await api<Receipt>(`/payments/${encodeURIComponent(payment.ref)}/receipt`));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  const requiresReference = selectedMethod?.requires_reference ?? false;
  const canRecord = can("payment.record");
  const canVerify = can("payment.verify");

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Payments</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Record received amounts, independently verify them, and review the payment ledger.</p>
      </header>
      <ErrorNotice message={error} />
      {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>}

      {canRecord && (
        <section className="card space-y-4">
          <h2 className="text-lg font-bold">Record manual payment</h2>
          <form className="flex flex-col gap-3 sm:flex-row" onSubmit={(event) => void findBooking(event)}>
            <label className="min-w-0 flex-1 space-y-1">
              <span className="text-sm font-semibold">Booking reference</span>
              <input className="field" required value={bookingRef} onChange={(event) => setBookingRef(event.target.value)} placeholder="BK-YYMMDD-NNNN" />
            </label>
            <button type="submit" className="btn-o self-end">Find booking</button>
          </form>

          {booking && (
            <div className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
              <div>
                <p className="font-bold">{booking.ref} · {booking.customer.name}</p>
                <p className="text-sm">{booking.customer.phone} · {money(booking.total_amount)} · {bookingStatusLabel[booking.status]}</p>
              </div>
              {booking.status === "expired" && can("booking.manage") && (
                <div className="space-y-2">
                  <label className="block space-y-1">
                    <span className="text-sm font-semibold">Renewal reason</span>
                    <input className="field" value={reason} onChange={(event) => setReason(event.target.value)} />
                  </label>
                  <button type="button" className="btn-o" disabled={busy} onClick={() => void renewHold()}>Recheck availability and renew hold</button>
                </div>
              )}
              {booking.status === "held" ? (
                <form className="grid grid-cols-1 gap-3 sm:grid-cols-2" onSubmit={(event) => void recordPayment(event)}>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Amount (৳)</span>
                    <input className="field" type="number" min="0.01" step="0.01" required value={amount} onChange={(event) => setAmount(event.target.value)} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Method</span>
                    <select className="field" value={method} onChange={(event) => setMethod(event.target.value)}>
                      {methods.map((item) => <option key={item.code} value={item.code}>{item.label}</option>)}
                    </select>
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Received at (Asia/Dhaka)</span>
                    <input className="field" type="datetime-local" required value={receivedAt} onChange={(event) => setReceivedAt(event.target.value)} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Transaction ID</span>
                    <input className="field" required={requiresReference && !bankRef} value={trxId} onChange={(event) => setTrxId(event.target.value)} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Bank reference</span>
                    <input className="field" required={requiresReference && !trxId} value={bankRef} onChange={(event) => setBankRef(event.target.value)} />
                  </label>
                  <label className="space-y-1">
                    <span className="text-sm font-semibold">Sender phone</span>
                    <input className="field" type="tel" value={senderPhone} onChange={(event) => setSenderPhone(event.target.value)} />
                  </label>
                  <label className="space-y-1 sm:col-span-2">
                    <span className="text-sm font-semibold">Pasted SMS (not proof of payment)</span>
                    <textarea className="field min-h-20" maxLength={2000} value={smsText} onChange={(event) => setSmsText(event.target.value)} />
                  </label>
                  <label className="space-y-1 sm:col-span-2">
                    <span className="text-sm font-semibold">Notes</span>
                    <textarea className="field min-h-16" maxLength={1000} value={notes} onChange={(event) => setNotes(event.target.value)} />
                  </label>
                  <button className="btn sm:col-span-2 sm:w-fit" disabled={busy || !methods.length}>
                    {busy ? "Recording…" : "Record received payment"}
                  </button>
                </form>
              ) : (
                <p className="text-sm">Manual payments can be recorded only while the booking is held. Renew an expired hold first if capacity is still available.</p>
              )}
            </div>
          )}
        </section>
      )}

      <section className="card space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-lg font-bold">Payment ledger</h2>
            <p className="text-sm text-slate-600 dark:text-slate-300">{payments?.total ?? 0} records</p>
          </div>
          <label className="min-w-40 space-y-1">
            <span className="text-sm font-semibold">Status</span>
            <select className="field" value={statusFilter} onChange={(event) => {
              setPage(1);
              setStatusFilter(event.target.value);
            }}>
              <option value="">All statuses</option>
              <option value="received">Received · awaiting verification</option>
              <option value="verified">Verified</option>
              <option value="rejected">Rejected</option>
              <option value="failed">Failed</option>
            </select>
          </label>
        </div>
        {loading ? <p role="status">Loading payments…</p> : payments?.items.length ? (
          <div className="space-y-3">
            {payments.items.map((payment) => (
              <article key={payment.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-bold">{payment.ref} · {payment.booking_ref ?? `Booking #${payment.booking_id}`}</p>
                    <p className="text-sm">{money(payment.amount)} · {payment.method === "online_simulated" ? "SIMULATED PAYMENT" : payment.method.replace(/_/g, " ")} · {statusLabel[payment.status]}</p>
                    <p className="text-xs text-slate-600 dark:text-slate-300">Received {dateTimeLabel(payment.received_at)} · recorded {dateTimeLabel(payment.recorded_at)}</p>
                    {payment.trx_id && <p className="text-xs">Transaction ID: {payment.trx_id}</p>}
                    {payment.rejection_reason && <p className="text-xs">Rejection reason: {payment.rejection_reason}</p>}
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {canVerify && payment.status === "received" && <>
                      <button type="button" className="btn-o" disabled={busy} onClick={() => void updatePayment(payment, "verify")}>Verify</button>
                      <button type="button" className="btn-o" disabled={busy} onClick={() => {
                        const message = window.prompt("Reason for rejecting this payment?");
                        if (message?.trim()) void updatePayment(payment, "reject", message.trim());
                      }}>Reject</button>
                    </>}
                    {payment.status === "verified" && <button type="button" className="btn-o" onClick={() => void openReceipt(payment)}>View receipt</button>}
                  </div>
                </div>
              </article>
            ))}
          </div>
        ) : <p className="text-sm">No payments match this filter.</p>}
        {payments && payments.total > payments.size && (
          <div className="flex items-center justify-between gap-3 border-t border-slate-200 pt-3 dark:border-slate-700">
            <button type="button" className="btn-o" disabled={page <= 1 || loading} onClick={() => setPage((value) => value - 1)}>Previous</button>
            <span className="text-sm">Page {payments.page} of {Math.ceil(payments.total / payments.size)}</span>
            <button type="button" className="btn-o" disabled={page * payments.size >= payments.total || loading} onClick={() => setPage((value) => value + 1)}>Next</button>
          </div>
        )}
      </section>

      {receipt && (
        <section className="card space-y-2" aria-label="Payment receipt">
          <h2 className="text-lg font-bold">Receipt {receipt.ref}</h2>
          {receipt.label && <p className="font-semibold">{receipt.label}</p>}
          <p>Booking {receipt.booking_ref} · {receipt.customer_name}</p>
          <p>{money(receipt.amount)} · {receipt.method.replace(/_/g, " ")} · {statusLabel[receipt.status]}</p>
          <p className="text-sm">{receipt.notice}</p>
        </section>
      )}
    </div>
  );
}
