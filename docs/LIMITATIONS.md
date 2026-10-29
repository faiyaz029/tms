# Limitations and next steps

This is a demonstration build. Online checkout is simulated, and the application
does not move real money.

## Current limitations

- The login failure limiter is held in process memory. Use one backend process
  for the demo; a multi-process deployment needs a shared rate-limit store.
- Phone numbers are format-validated but are not verified with SMS OTP.
- Email can use a console logger, database outbox, or configured SMTP server.
  Outbox and console states are not email delivery confirmations.
- Password reset uses the selected email backend. Console/outbox are suitable for
  development; SMTP credentials and transport security must be configured before
  relying on real email.
- Scheduled hold expiry is available as an operator command, not a persistent
  scheduler. Run `python -m app.cli expire-holds` periodically if needed.
- Facility, schedule, pricing, and pool-session administration screens are
  incomplete; configuration APIs are available.
- Shareholder payout recording is not implemented. Statements report
  allocations as calculated, not paid.
- Automated browser tests exercise the core demonstration workflow, not every
  combination of roles, filters, devices, and error conditions.
- Monitoring, production secret management, backups, restore automation, and
  multi-region/high-availability operation are deployment responsibilities.

## Before any real deployment

Do not treat this demo as a production financial ledger. Set a strong
`SECRET_KEY`, use HTTPS and `COOKIE_SECURE=true`, configure restrictive
infrastructure/network access, review the permission matrix and database
migrations, configure email intentionally, establish monitored backups, and
complete independent operational and security reviews.
