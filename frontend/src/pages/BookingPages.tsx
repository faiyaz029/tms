import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, downloadCsv } from "../api";

type Status = "free" | "held" | "confirmed" | "blocked" | "closed" | "outside_hours" | "beyond_horizon" | "full" | "open";

interface TurfSlot {
  date: string;
  facility_id: number;
  start: string;
  end: string;
  status: Status;
  price: string | null;
}

interface PoolSession {
  id: number | null;
  facility_id: number;
  date: string;
  start: string;
  end: string;
  capacity: number;
  reserved: number;
  remaining: number;
  price_per_person: string;
  status: Status;
}

interface BookingEvent {
  at: string;
  from_status: string | null;
  to_status: string;
  reason: string | null;
}

interface Booking {
  id: number;
  ref: string;
  facility_id: number;
  channel: "online" | "phone" | "walk_in";
  status: "draft" | "held" | "confirmed" | "cancelled" | "expired";
  customer: { name: string; phone: string; address: string | null };
  created_at: string | null;
  hold_expires_at: string | null;
  total_amount: string;
  currency: string;
  notes: string | null;
  starts_at: string | null;
  ends_at: string | null;
  pool_session_id: number | null;
  participants: number | null;
  pool_session: { starts_at: string; ends_at: string } | null;
  events?: BookingEvent[];
}

interface PageList<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

const businessDate = () => new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Dhaka" }).format(new Date());
const money = (amount: string) => `৳${Number(amount).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const timeLabel = (value: string) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", hour: "numeric", minute: "2-digit",
}).format(new Date(value));
const dateTimeLabel = (value: string) => new Intl.DateTimeFormat("en-BD", {
  timeZone: "Asia/Dhaka", dateStyle: "medium", timeStyle: "short",
}).format(new Date(value));
const paymentStatusLabel: Record<CustomerPaymentRecord["status"], string> = {
  pending: "◷ Pending",
  received: "⏳ Received · awaiting verification",
  verified: "✓ Verified",
  rejected: "⊘ Rejected",
  failed: "✕ Failed",
  refunded: "↩ Refunded",
};

function StatusText({ status }: { status: Booking["status"] | Status }) {
  const labels: Record<string, string> = {
    draft: "◷ Draft",
    held: "⏳ Held",
    confirmed: "✓ Confirmed",
    cancelled: "⊘ Cancelled",
    expired: "⌛ Expired",
    free: "○ Free",
    open: "○ Open",
    full: "● Full",
    blocked: "⛔ Blocked",
    closed: "○ Closed",
    outside_hours: "○ Outside hours",
    beyond_horizon: "○ Beyond booking window",
  };
  return <span aria-label={`Status: ${status}`}>{labels[status] ?? status}</span>;
}

function ErrorNotice({ message }: { message: string }) {
  return message ? <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950 dark:text-red-300">{message}</p> : null;
}

function useAvailability(date: string) {
  const [turf, setTurf] = useState<TurfSlot[]>([]);
  const [pool, setPool] = useState<PoolSession[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [turfSlots, poolSessions] = await Promise.all([
        api<TurfSlot[]>(`/availability/turf?date=${encodeURIComponent(date)}`),
        api<PoolSession[]>(`/availability/pool?date=${encodeURIComponent(date)}`),
      ]);
      setTurf(turfSlots);
      setPool(poolSessions);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [date]);

  useEffect(() => { void refresh(); }, [refresh]);
  return { turf, pool, loading, error, refresh };
}

export function Book() {
  const [date, setDate] = useState(businessDate);
  const [facility, setFacility] = useState<"turf" | "pool">("turf");
  const [participants, setParticipants] = useState("1");
  const [selectedStart, setSelectedStart] = useState("");
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Booking | null>(null);
  const { turf, pool, loading, error: loadError } = useAvailability(date);
  const selectedPool = useMemo(() => Number.parseInt(participants, 10), [participants]);
  const slotFacilityId = turf[0]?.facility_id;
  const poolFacilityId = pool[0]?.facility_id;

  const selectedSlot = turf.find((slot) => slot.start === selectedStart);
  const selectedSession = selectedSessionId === null
    ? undefined
    : pool.find((session) => session.id === selectedSessionId);

  const submit = async () => {
    setError("");
    setMessage("");
    setBusy(true);
    const body = selectedSlot
      ? { facility_id: slotFacilityId, starts_at: selectedSlot.start }
      : { facility_id: poolFacilityId, pool_session_id: selectedSession!.id, participants: selectedPool };
    try {
      const booking = await api<Booking>("/bookings", { method: "POST", body });
      setCreated(booking);
      setSelectedStart("");
      setSelectedSessionId(null);
      setMessage(`Booking ${booking.ref} is held. Continue to My bookings to use the SIMULATED payment flow.`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <header>
        <h1 className="text-2xl font-bold">Book a facility</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Choose a date and available time. Your booking stays held until the payment workflow is complete.</p>
      </header>
      <section className="card space-y-4">
        <label className="block space-y-1">
          <span className="text-sm font-semibold">Date</span>
          <input className="field" type="date" value={date} onChange={(event) => { setDate(event.target.value); setCreated(null); setSelectedSessionId(null); setSelectedStart(""); }} />
        </label>
        <div className="grid grid-cols-2 gap-2" role="tablist" aria-label="Facility">
          <button type="button" className={`btn-o ${facility === "turf" ? "bg-pitch-700 text-white" : ""}`} onClick={() => { setFacility("turf"); setCreated(null); setSelectedSessionId(null); setSelectedStart(""); }}>⚽ Turf</button>
          <button type="button" className={`btn-o ${facility === "pool" ? "bg-pitch-700 text-white" : ""}`} onClick={() => { setFacility("pool"); setCreated(null); setSelectedSessionId(null); setSelectedStart(""); }}>🏊 Pool</button>
        </div>
        <ErrorNotice message={loadError || error} />
        {message && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{message}</p>}
        {created && (
          <div className="rounded-lg border border-emerald-600 p-3 text-sm">
            <p className="font-bold">{created.ref} · <StatusText status={created.status} /></p>
            <p>Total: {money(created.total_amount)}</p>
            <p>Hold expires: {created.hold_expires_at ? dateTimeLabel(created.hold_expires_at) : "—"}</p>
          </div>
        )}
        {loading ? <p role="status">Loading availability…</p> : facility === "turf" ? (
          <div className="space-y-2">
            <h2 className="font-bold">Turf · configured session duration</h2>
            {turf.length === 0 && <p className="text-sm text-slate-500">No turf slots are configured for this date.</p>}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {turf.map((slot) => (
                <div key={slot.start} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                  <div className="min-w-0">
                    <p className="font-semibold">{timeLabel(slot.start)}–{timeLabel(slot.end)}</p>
                    <p className="text-sm"><StatusText status={slot.status} />{slot.price ? ` · ${money(slot.price)}` : ""}</p>
                  </div>
                  <button type="button" className="btn-o shrink-0" aria-pressed={selectedStart === slot.start}
                    disabled={slot.status !== "free" || !slotFacilityId || !slot.price}
                    onClick={() => setSelectedStart(slot.start)}>
                    {selectedStart === slot.start ? "Selected" : "Select"}
                  </button>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            <h2 className="font-bold">Pool sessions</h2>
            <label className="block space-y-1">
              <span className="text-sm font-semibold">Participants</span>
              <input className="field" type="number" min={1} max={100} value={participants}
                onChange={(event) => setParticipants(event.target.value)} />
            </label>
            {pool.length === 0 && <p className="text-sm text-slate-500">No pool sessions are configured for this date.</p>}
            {pool.map((session) => (
              <div key={session.id} className="flex items-center justify-between gap-3 rounded-lg border border-slate-200 p-3 dark:border-slate-700">
                <div className="min-w-0">
                  <p className="font-semibold">{timeLabel(session.start)}–{timeLabel(session.end)}</p>
                  <p className="text-sm"><StatusText status={session.status} /> · {session.remaining} places left · {money(session.price_per_person)} per person</p>
                </div>
                <button type="button" className="btn-o shrink-0" aria-pressed={selectedSessionId === session.id}
                  disabled={session.status !== "open" || session.id === null || !poolFacilityId || !Number.isInteger(selectedPool) || selectedPool < 1 || selectedPool > session.remaining}
                  onClick={() => { if (session.id !== null) setSelectedSessionId(session.id); }}>
                  {selectedSessionId === session.id ? "Selected" : "Select"}
                </button>
              </div>
            ))}
          </div>
        )}
        {selectedSlot && facility === "turf" && (
          <div className="rounded-lg border border-pitch-700 p-3">
            <h2 className="font-bold">Review booking</h2>
            <p>{date} · {timeLabel(selectedSlot.start)}–{timeLabel(selectedSlot.end)}</p>
            <p>Price breakdown: selected turf session · {money(selectedSlot.price!)}</p>
            <button type="button" className="btn mt-3 w-full" disabled={busy}
              onClick={() => void submit()}>{busy ? "Creating hold…" : "Hold and continue"}</button>
          </div>
        )}
        {selectedSession && facility === "pool" && (
          <div className="rounded-lg border border-pitch-700 p-3">
            <h2 className="font-bold">Review booking</h2>
            <p>{date} · {timeLabel(selectedSession.start)}–{timeLabel(selectedSession.end)}</p>
            <p>Price breakdown: {selectedPool} participant(s) × {money(selectedSession.price_per_person)} per person</p>
            <button type="button" className="btn mt-3 w-full" disabled={busy || !Number.isInteger(selectedPool) || selectedPool < 1 || selectedPool > selectedSession.remaining}
              onClick={() => void submit()}>{busy ? "Creating hold…" : "Hold and continue"}</button>
          </div>
        )}
      </section>
      <p className="text-xs text-slate-500">Online checkout is SIMULATED. No real payment is made; the booking confirms only after the backend validates the simulated result.</p>
    </div>
  );
}

function BookingCard({ booking, actions }: { booking: Booking; actions?: React.ReactNode }) {
  const serviceTime = booking.starts_at
    ? `${dateTimeLabel(booking.starts_at)}–${timeLabel(booking.ends_at!)}`
    : booking.pool_session
      ? `${dateTimeLabel(booking.pool_session.starts_at)}–${timeLabel(booking.pool_session.ends_at)} · ${booking.participants} participant(s)`
      : "Service time unavailable";
  return (
    <article className="card space-y-2">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <h2 className="font-bold">{booking.ref}</h2>
          <p className="text-sm">{serviceTime}</p>
        </div>
        <p className="font-semibold"><StatusText status={booking.status} /></p>
      </div>
      <p className="text-sm">{booking.channel.replace("_", " ")} · {money(booking.total_amount)}</p>
      {booking.hold_expires_at && booking.status === "held" && <p className="text-sm">Hold expires {dateTimeLabel(booking.hold_expires_at)}</p>}
      {booking.customer && <p className="text-sm text-slate-600 dark:text-slate-300">{booking.customer.name} · {booking.customer.phone}</p>}
      {actions}
    </article>
  );
}

export function MyBookings() {
  const [result, setResult] = useState<PageList<Booking> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try { setResult(await api<PageList<Booking>>("/my/bookings")); }
    catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4">
      <header className="flex items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">My bookings</h1><p className="text-sm text-slate-600 dark:text-slate-300">Your bookings and their current status.</p></div>
        <button type="button" className="btn-o" onClick={() => void load()}>Refresh</button>
      </header>
      <ErrorNotice message={error} />
      {loading ? <p role="status">Loading bookings…</p> : result?.items.length ? (
        <div className="space-y-3">{result.items.map((booking) => (
          <BookingCard key={booking.id} booking={booking} actions={
            booking.channel === "online" ? <CustomerPayment booking={booking} onUpdated={() => void load()} /> : undefined
          } />
        ))}</div>
      ) : <div className="card text-sm">You do not have any bookings yet.</div>}
    </div>
  );
}

interface CustomerPaymentRecord {
  id: number;
  ref: string;
  amount: string;
  method: string;
  status: "pending" | "received" | "verified" | "rejected" | "failed" | "refunded";
  received_at: string | null;
}

interface CustomerReceipt {
  ref: string;
  amount: string;
  currency: string;
  status: CustomerPaymentRecord["status"];
  notice: string;
  label: string | null;
}

interface ActiveIntent {
  id: number;
  amount: string;
  status: string;
  label: string;
}

function CustomerPayment({ booking, onUpdated }: { booking: Booking; onUpdated: () => void }) {
  const [payments, setPayments] = useState<CustomerPaymentRecord[]>([]);
  const [intent, setIntent] = useState<ActiveIntent | null>(null);
  const [receipt, setReceipt] = useState<CustomerReceipt | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const idempotencyKey = useRef(crypto.randomUUID());

  const loadPayments = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api<{
        items: CustomerPaymentRecord[];
        active_intent: ActiveIntent | null;
      }>(`/payments/booking/${encodeURIComponent(booking.ref)}`);
      setPayments(response.items);
      setIntent(response.active_intent);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }
  }, [booking.ref]);

  useEffect(() => { void loadPayments(); }, [loadPayments]);

  const initiate = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api<ActiveIntent & { gateway_label: string }>("/payments/online/initiate", {
        method: "POST",
        headers: { "Idempotency-Key": idempotencyKey.current },
        body: { booking_id: booking.id },
      });
      setIntent({ ...result, label: result.gateway_label });
    } catch (err) {
      setError((err as Error).message);
      await loadPayments();
    } finally {
      setBusy(false);
    }
  };

  const settle = async (result: "success" | "fail" | "cancel") => {
    if (!intent) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await api<{ booking_status: string; label: string }>(
        `/payments/online/${intent.id}/simulate/${result}`,
        { method: "POST" },
      );
      setMessage(result === "success"
        ? `${response.label}: payment verified and booking ${response.booking_status}.`
        : `SIMULATED PAYMENT ${result.toUpperCase()}: booking remains ${response.booking_status}.`);
      setIntent(null);
      idempotencyKey.current = crypto.randomUUID();
      await loadPayments();
      onUpdated();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const showReceipt = async (payment: CustomerPaymentRecord) => {
    setError("");
    try {
      setReceipt(await api<CustomerReceipt>(`/payments/${encodeURIComponent(payment.ref)}/receipt`));
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <div className="space-y-2 border-t border-slate-200 pt-3 dark:border-slate-700">
      {error && <ErrorNotice message={error} />}
      {message && <p role="status" className="text-sm">{message}</p>}
      {loading ? <p role="status" className="text-sm">Loading payment status…</p> : (
        <div className="space-y-2">
          {payments.map((payment) => (
            <div key={payment.id} className="flex flex-wrap items-center justify-between gap-2 text-sm">
              <span>{payment.ref} · {money(payment.amount)} · {payment.method === "online_simulated" ? "SIMULATED PAYMENT · " : ""}{paymentStatusLabel[payment.status]}</span>
              {payment.status === "verified" && <button type="button" className="btn-o" onClick={() => void showReceipt(payment)}>View receipt</button>}
            </div>
          ))}
          {receipt && (
            <div className="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700">
              <p className="font-bold">Receipt {receipt.ref}</p>
              {receipt.label && <p className="font-semibold">{receipt.label}</p>}
              <p>{money(receipt.amount)} {receipt.currency} · {paymentStatusLabel[receipt.status]}</p>
              <p>{receipt.notice}</p>
            </div>
          )}
        </div>
      )}
      {booking.status === "held" && (
        <div className="space-y-2">
          {!intent ? (
            <button type="button" className="btn" disabled={busy || loading} onClick={() => void initiate()}>
              {busy ? "Starting…" : `Pay ${money(booking.total_amount)} · SIMULATED`}
            </button>
          ) : (
            <div className="space-y-2 rounded-lg border border-amber-500 p-3">
              <p className="font-semibold">{intent.label} · {money(intent.amount)}</p>
              <p className="text-xs">Demonstration only: choose a simulated result. No real payment is made.</p>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="btn" disabled={busy} onClick={() => void settle("success")}>Simulate success</button>
                <button type="button" className="btn-o" disabled={busy} onClick={() => void settle("fail")}>Simulate failure</button>
                <button type="button" className="btn-o" disabled={busy} onClick={() => void settle("cancel")}>Cancel simulation</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function Timetable() {
  const [date, setDate] = useState(businessDate);
  const [facility, setFacility] = useState<"turf" | "pool">("turf");
  const { turf, pool, loading, error } = useAvailability(date);
  const days = Array.from({ length: 5 }, (_, offset) => {
    const day = new Date(`${businessDate()}T12:00:00+06:00`);
    day.setUTCDate(day.getUTCDate() + offset);
    return new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Dhaka" }).format(day);
  });
  return (
    <div className="space-y-4">
      <header><h1 className="text-2xl font-bold">Timetable</h1><p className="text-sm text-slate-600 dark:text-slate-300">Availability only. Customer names and contact details are never shown here.</p></header>
      <section className="card space-y-4">
        <div className="flex flex-wrap gap-2" aria-label="Select date">
          {days.map((day) => <button key={day} type="button" className={`btn-o ${date === day ? "bg-pitch-700 text-white" : ""}`} onClick={() => setDate(day)}>
            {new Intl.DateTimeFormat("en-BD", { timeZone: "Asia/Dhaka", weekday: "short", day: "numeric", month: "short" }).format(new Date(`${day}T12:00:00+06:00`))}
          </button>)}
          <label className="sr-only" htmlFor="timetable-date">Choose another date</label>
          <input id="timetable-date" className="field min-w-0 flex-1" type="date" value={date} onChange={(event) => setDate(event.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <button type="button" className={`btn-o ${facility === "turf" ? "bg-pitch-700 text-white" : ""}`} onClick={() => setFacility("turf")}>⚽ Turf</button>
          <button type="button" className={`btn-o ${facility === "pool" ? "bg-pitch-700 text-white" : ""}`} onClick={() => setFacility("pool")}>🏊 Pool</button>
        </div>
        <ErrorNotice message={error} />
        {loading ? <p role="status">Loading timetable…</p> : facility === "turf" ? (
          turf.length ? <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {turf.map((slot) => <div key={slot.start} className={`rounded-lg border p-3 ${slot.status === "held" ? "border-dashed border-amber-600" : "border-slate-200 dark:border-slate-700"}`}>
              <p className="font-semibold">{timeLabel(slot.start)}–{timeLabel(slot.end)}</p>
              <p className="text-sm"><StatusText status={slot.status} />{slot.price ? ` · ${money(slot.price)}` : ""}</p>
            </div>)}
          </div> : <p className="text-sm">No turf slots are configured for this date.</p>
        ) : pool.length ? <div className="space-y-2">
          {pool.map((session) => <div key={session.id} className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
            <p className="font-semibold">{timeLabel(session.start)}–{timeLabel(session.end)}</p>
            <p className="text-sm"><StatusText status={session.status} /> · {session.remaining} of {session.capacity} places remaining · {money(session.price_per_person)} per person</p>
          </div>)}
        </div> : <p className="text-sm">No pool sessions are configured for this date.</p>}
      </section>
    </div>
  );
}

export function StaffBookings() {
  const [date, setDate] = useState(businessDate);
  const [facility, setFacility] = useState<"turf" | "pool">("turf");
  const [channel, setChannel] = useState<"phone" | "walk_in">("phone");
  const [customerName, setCustomerName] = useState("");
  const [customerPhone, setCustomerPhone] = useState("");
  const [customerAddress, setCustomerAddress] = useState("");
  const [contactMessage, setContactMessage] = useState("");
  const [participants, setParticipants] = useState("1");
  const [selected, setSelected] = useState("");
  const [reason, setReason] = useState("");
  const [extension, setExtension] = useState("30");
  const [filterRef, setFilterRef] = useState("");
  const [filterStatus, setFilterStatus] = useState("");
  const [result, setResult] = useState<PageList<Booking> | null>(null);
  const [details, setDetails] = useState<Booking | null>(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const { turf, pool, loading: availabilityLoading, error: availabilityError, refresh } = useAvailability(date);
  const selectedPool = useMemo(() => Number.parseInt(participants, 10), [participants]);

  const loadBookings = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ date_from: date, date_to: date });
      if (filterRef) params.set("ref", filterRef);
      if (filterStatus) params.set("status", filterStatus);
      setResult(await api<PageList<Booking>>(`/bookings?${params.toString()}`));
    } catch (err) { setError((err as Error).message); }
    finally { setLoading(false); }
  }, [date, filterRef, filterStatus]);

  const exportBookings = async () => {
    setError("");
    try {
      const params = new URLSearchParams({ date_from: date, date_to: date });
      if (filterRef) params.set("ref", filterRef);
      if (filterStatus) params.set("status", filterStatus);
      await downloadCsv(`/exports/bookings.csv?${params.toString()}`, "bookings.csv");
    } catch (err) {
      setError((err as Error).message);
    }
  };

  useEffect(() => { void loadBookings(); }, [loadBookings]);
  useEffect(() => { setSelected(""); }, [facility, date]);

  const findContact = async () => {
    setError("");
    setContactMessage("");
    try {
      const found = await api<{ found: boolean; name?: string; phone?: string; address?: string | null }>(
        `/bookings/contacts?phone=${encodeURIComponent(customerPhone)}`,
      );
      if (found.found) {
        setCustomerName(found.name ?? "");
        setCustomerAddress(found.address ?? "");
        setContactMessage("Existing customer contact found.");
      } else {
        setContactMessage("No saved contact found. A new contact will be created with this booking.");
      }
    } catch (err) { setError((err as Error).message); }
  };

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    setNotice("");
    const selectedSlot = facility === "turf" ? turf.find((slot) => slot.start === selected) : undefined;
    const selectedSession = facility === "pool" ? pool.find((session) => String(session.id) === selected) : undefined;
    const body = {
      facility_id: facility === "turf" ? turf[0]?.facility_id : pool[0]?.facility_id,
      channel,
      customer_name: customerName,
      customer_phone: customerPhone,
      customer_address: customerAddress || undefined,
      ...(selectedSlot ? { starts_at: selectedSlot.start } : {}),
      ...(selectedSession ? { pool_session_id: selectedSession.id, participants: selectedPool } : {}),
    };
    try {
      const booking = await api<Booking>("/bookings/staff", { method: "POST", body });
      setNotice(`Created ${booking.ref} · ${money(booking.total_amount)} · hold expires ${booking.hold_expires_at ? dateTimeLabel(booking.hold_expires_at) : "—"}.`);
      setCustomerName("");
      setCustomerPhone("");
      setCustomerAddress("");
      setSelected("");
      await Promise.all([loadBookings(), refresh()]);
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  const updateBooking = async (booking: Booking, action: "cancel" | "release" | "extend") => {
    if (!reason.trim()) { setError("Enter a reason before changing a booking."); return; }
    setBusy(true);
    setError("");
    try {
      const path = `/bookings/${booking.id}/${action === "extend" ? "extend-hold" : action}`;
      const body = action === "extend" ? { reason, minutes: Number(extension) } : { reason };
      await api<Booking>(path, { method: "POST", body });
      setNotice(`${booking.ref} updated.`);
      await Promise.all([loadBookings(), refresh()]);
      if (details?.ref === booking.ref) setDetails(await api<Booking>(`/bookings/${booking.ref}`));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  };

  const showDetails = async (booking: Booking) => {
    setError("");
    try { setDetails(await api<Booking>(`/bookings/${booking.ref}`)); }
    catch (err) { setError((err as Error).message); }
  };

  return (
    <div className="space-y-5">
      <header>
        <h1 className="text-2xl font-bold">Bookings</h1>
        <p className="text-sm text-slate-600 dark:text-slate-300">Create phone or walk-in holds, review booking history, and manage active holds.</p>
      </header>
      <section className="card space-y-4">
        <h2 className="text-lg font-bold">New booking</h2>
        <form className="space-y-3" onSubmit={(event) => void create(event)}>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <label className="space-y-1"><span className="text-sm font-semibold">Customer name</span><input className="field" required minLength={2} value={customerName} onChange={(event) => setCustomerName(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Phone</span><input className="field" type="tel" inputMode="tel" required value={customerPhone} onChange={(event) => setCustomerPhone(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Channel</span><select className="field" value={channel} onChange={(event) => setChannel(event.target.value as "phone" | "walk_in")}><option value="phone">Phone</option><option value="walk_in">Walk-in</option></select></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Facility</span><select className="field" value={facility} onChange={(event) => setFacility(event.target.value as "turf" | "pool")}><option value="turf">Turf</option><option value="pool">Pool</option></select></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Service date</span><input className="field" type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Address (optional)</span><input className="field" value={customerAddress} onChange={(event) => setCustomerAddress(event.target.value)} /></label>
          </div>
          <button className="btn-o" type="button" disabled={!customerPhone.trim()} onClick={() => void findContact()}>Find customer by phone</button>
          {contactMessage && <p role="status" className="text-sm">{contactMessage}</p>}
          {facility === "pool" && <label className="block space-y-1"><span className="text-sm font-semibold">Participants</span><input className="field" type="number" min={1} max={100} value={participants} onChange={(event) => setParticipants(event.target.value)} /></label>}
          <ErrorNotice message={availabilityError} />
          {availabilityLoading ? <p role="status">Loading availability…</p> : facility === "turf" ? (
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-bold">Select a turf time</legend>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {turf.map((slot) => <label key={slot.start} className={`flex min-h-11 cursor-pointer items-center justify-between gap-2 rounded-lg border p-3 ${slot.status !== "free" ? "opacity-60" : ""}`}>
                  <span>{timeLabel(slot.start)}–{timeLabel(slot.end)} · {slot.price ? money(slot.price) : "Price unavailable"} · <StatusText status={slot.status} /></span>
                  <input type="radio" name="turf-slot" value={slot.start} disabled={slot.status !== "free" || !slot.price} checked={selected === slot.start} onChange={() => setSelected(slot.start)} />
                </label>)}
              </div>
            </fieldset>
          ) : (
            <fieldset className="space-y-2">
              <legend className="mb-2 text-sm font-bold">Select a pool session</legend>
              {pool.map((session) => <label key={session.id} className={`flex min-h-11 cursor-pointer items-center justify-between gap-2 rounded-lg border p-3 ${session.status !== "open" ? "opacity-60" : ""}`}>
                <span>{timeLabel(session.start)}–{timeLabel(session.end)} · {session.remaining} left · {money(session.price_per_person)} / person · <StatusText status={session.status} /></span>
                <input type="radio" name="pool-session" value={session.id ?? ""} disabled={session.status !== "open" || session.id === null || selectedPool < 1 || selectedPool > session.remaining} checked={selected === String(session.id)} onChange={() => setSelected(String(session.id))} />
              </label>)}
            </fieldset>
          )}
          <ErrorNotice message={error} />
          {notice && <p role="status" className="rounded-lg bg-emerald-50 p-3 text-sm text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200">{notice}</p>}
          <button className="btn w-full sm:w-auto" disabled={busy || !selected || (facility === "pool" && !Number.isInteger(selectedPool))}>{busy ? "Saving…" : "Create held booking"}</button>
        </form>
      </section>

      <section className="space-y-3">
        <div className="card space-y-3">
          <h2 className="text-lg font-bold">Bookings for {date}</h2>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <label className="space-y-1"><span className="text-sm font-semibold">Reference</span><input className="field" placeholder="Search reference" value={filterRef} onChange={(event) => setFilterRef(event.target.value)} /></label>
            <label className="space-y-1"><span className="text-sm font-semibold">Status</span><select className="field" value={filterStatus} onChange={(event) => setFilterStatus(event.target.value)}><option value="">All statuses</option><option value="held">Held</option><option value="confirmed">Confirmed</option><option value="cancelled">Cancelled</option><option value="expired">Expired</option></select></label>
            <button className="btn-o self-end" type="button" onClick={() => void loadBookings()}>Refresh list</button>
            <button className="btn-o self-end" type="button" onClick={() => void exportBookings()}>Export filtered CSV</button>
          </div>
        </div>
        <ErrorNotice message={error} />
        {loading ? <p role="status">Loading bookings…</p> : result?.items.length ? result.items.map((booking) => (
          <BookingCard key={booking.id} booking={booking} actions={
            <div className="space-y-2 border-t border-slate-200 pt-2 dark:border-slate-700">
              <button type="button" className="btn-o w-full sm:w-auto" onClick={() => void showDetails(booking)}>View event history</button>
              {booking.status === "held" && <div className="flex flex-wrap gap-2">
                <button type="button" className="btn-o" disabled={busy} onClick={() => void updateBooking(booking, "extend")}>Extend hold</button>
                <button type="button" className="btn-o" disabled={busy} onClick={() => void updateBooking(booking, "release")}>Release hold</button>
              </div>}
              {(booking.status === "held" || booking.status === "confirmed") && <button type="button" className="btn-o" disabled={busy} onClick={() => void updateBooking(booking, "cancel")}>Cancel booking</button>}
              {(booking.status === "held" || booking.status === "confirmed") && <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label className="space-y-1"><span className="text-xs font-semibold">Reason required for changes</span><input className="field" value={reason} onChange={(event) => setReason(event.target.value)} /></label>
                {booking.status === "held" && <label className="space-y-1"><span className="text-xs font-semibold">Extend by (minutes)</span><input className="field" type="number" min={1} max={1440} value={extension} onChange={(event) => setExtension(event.target.value)} /></label>}
              </div>}
            </div>
          } />
        )) : <div className="card text-sm">No bookings match these filters.</div>}
        {details && <section className="card space-y-3" aria-label={`History for ${details.ref}`}>
          <div className="flex items-center justify-between gap-2"><h2 className="font-bold">Event history · {details.ref}</h2><button className="btn-o" onClick={() => setDetails(null)}>Close</button></div>
          {details.events?.length ? <ol className="space-y-2">{details.events.map((event, index) => <li key={`${event.at}-${index}`} className="border-l-2 border-pitch-700 pl-3 text-sm">
            <p className="font-semibold">{dateTimeLabel(event.at)} · {event.from_status ?? "Created"} → {event.to_status}</p>
            {event.reason && <p>{event.reason}</p>}
          </li>)}</ol> : <p className="text-sm">No events recorded.</p>}
        </section>}
      </section>
    </div>
  );
}
