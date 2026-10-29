# Demo script (about 15 minutes)

Start with `APP_ENV=demo`, then run `python -m app.seed` after migrations. See
the README for Docker setup and the warning for the destructive `--reset`
option. The frontend shows a DEMO ENVIRONMENT banner. Use a laptop for
staff-facing pages and a phone or 375px viewport for the customer flow.

The seed creates role accounts listed below. All use `DemoPool2026!` only in
demo mode. These public credentials are never for production.

| Role | Email |
|---|---|
| Owner | `demo-owner@example.com` |
| Admin | `demo-admin@example.com` |
| Staff | `demo-staff@example.com` |
| Accountant | `demo-accountant@example.com` |
| Customer | `demo-customer@example.com` |
| Shareholder (20 shares) | `demo-holder-20@example.com` |
| Shareholder (12 shares) | `demo-holder-12@example.com` |
| Shareholder (8 shares) | `demo-holder-8@example.com` |
| Shareholder (6 shares) | `demo-holder-6@example.com` |
| Shareholder (4 shares) | `demo-holder-4@example.com` |

1. **Seeded overview.** Show the turf and pool timetable, held/confirmed/
   expired/cancelled bookings, sample payment methods, and the 50-share
   register. Point out the approved previous-month report and open current
   report.
2. **Online booking (customer).** Choose a future turf slot, review its price,
   hold it, and complete **Simulate success** from My bookings. Show the
   confirmed status and receipt. State that no real payment occurred.
3. **Phone booking (staff).** Create a phone booking for a new contact and
   record a bKash payment with a reference. It remains awaiting verification.
4. **Independent verification.** Sign in as accountant, verify the payment,
   and show that the booking confirms only after verification.
5. **Walk-in (staff).** Create a walk-in booking and record cash. Verify it as
   an authorized accountant.
6. **Expense.** Enter an electricity expense, copy its generated `EXP-`
   reference, search by it, and approve it as a different user.
7. **Daily closing.** Submit a closing as staff and review it as owner/admin.
   Show totals and pending items.
8. **Monthly report.** As accountant, confirm eligible shares, complete the
   checklist, set the distribution pool, and submit the report for review.
   Approve it as owner.
9. **Allocation and statement.** Show the per-share result and unequal
   allocations (20, 12, 8, 6, 4 shares). Sign in as a shareholder to view only
   that shareholder's own approved statement.
10. **Email preview.** As owner/admin, open the rendered statement preview and
    explain the delivery state. A preview is not a sent or delivered email.
11. **Permission boundary.** Try to verify a payment as shareholder; the API
    denies the action.
12. **Pool capacity.** Use two customer browser contexts on a seeded session
    with two places left. Reserve both places from each context at once; exactly
    one request succeeds.

## Always say

Payments in the demo are simulated. Allocations are calculated figures, not
payments or guaranteed dividends. All seeded names and transactions are sample
data.
