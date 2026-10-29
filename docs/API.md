# API reference

Generated from the FastAPI OpenAPI schema (version 0.1.0).

All routes are under `/api`. Protected routes require the access-token cookie. Unsafe requests also require the `X-CSRF-Token` header matching the CSRF cookie.
The central role and permission matrix is in `backend/app/permissions.py`.

## POST `/api/auth/forgot-password`

Forgot Password

JSON request body: `ForgotPasswordIn`.

Responses: `202` Successful Response, `422` Validation Error.

## POST `/api/auth/google`

Google Login

JSON request body: `GoogleIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/auth/login`

Login

JSON request body: `LoginIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/auth/logout`

Logout

Responses: `204` Successful Response.

## GET `/api/auth/me`

Me

Responses: `200` Successful Response.

## PATCH `/api/auth/profile`

Update Profile

JSON request body: `ProfileIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/auth/register`

Register

JSON request body: `RegisterIn`.

Responses: `201` Successful Response, `422` Validation Error.

## POST `/api/auth/reset-password`

Reset Password

JSON request body: `ResetPasswordIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/availability/pool`

Pool

Parameters:

- `query` `date` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/availability/turf`

Turf

Parameters:

- `query` `date` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/bookings`

List Bookings

Parameters:

- `query` `date_from` (optional, object)
- `query` `date_to` (optional, object)
- `query` `facility_id` (optional, object)
- `query` `channel` (optional, object)
- `query` `status` (optional, object)
- `query` `ref` (optional, object)
- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/bookings`

Create Online Booking

JSON request body: `BookingSelection`.

Responses: `201` Successful Response, `422` Validation Error.

## GET `/api/bookings/contacts`

Find Customer Contact

Parameters:

- `query` `phone` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/bookings/staff`

Create Staff Booking

JSON request body: `StaffBookingIn`.

Responses: `201` Successful Response, `422` Validation Error.

## POST `/api/bookings/{booking_id}/cancel`

Cancel Booking

Parameters:

- `path` `booking_id` (required, integer)

JSON request body: `BookingActionIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/bookings/{booking_id}/extend-hold`

Extend Booking Hold

Parameters:

- `path` `booking_id` (required, integer)

JSON request body: `ExtendHoldIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/bookings/{booking_id}/payments`

Add Manual Payment

Parameters:

- `path` `booking_id` (required, integer)

JSON request body: `ManualPaymentIn`.

Responses: `201` Successful Response, `422` Validation Error.

## POST `/api/bookings/{booking_id}/release`

Release Booking Hold

Parameters:

- `path` `booking_id` (required, integer)

JSON request body: `BookingActionIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/bookings/{booking_id}/renew-hold`

Renew Booking Hold

Parameters:

- `path` `booking_id` (required, integer)

JSON request body: `BookingActionIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/bookings/{ref}`

Get Booking

Parameters:

- `path` `ref` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/closings`

List Closings

Parameters:

- `query` `date` (optional, object)
- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/closings`

Add Closing

JSON request body: `ClosingSubmitIn`.

Responses: `201` Successful Response, `422` Validation Error.

## GET `/api/closings/totals`

Closing Preview

Parameters:

- `query` `business_date` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/closings/{closing_id}`

Get Closing

Parameters:

- `path` `closing_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/closings/{closing_id}/review`

Review

Parameters:

- `path` `closing_id` (required, integer)

JSON request body: `ClosingReviewIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/distribution`

Record Distribution

JSON request body: `ReportDistributionIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/emails`

List Email Deliveries

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/emails/{delivery_id}/preview`

Preview Email

Parameters:

- `path` `delivery_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/emails/{delivery_id}/retry`

Retry Email

Parameters:

- `path` `delivery_id` (required, integer)

Responses: `202` Successful Response, `422` Validation Error.

## GET `/api/expense-categories`

List Categories

Responses: `200` Successful Response.

## POST `/api/expense-categories`

Create Category

JSON request body: `ExpenseCategoryCreateIn`.

Responses: `201` Successful Response, `422` Validation Error.

## PATCH `/api/expense-categories/{code}`

Update Category

Parameters:

- `path` `code` (required, string)

JSON request body: `ExpenseCategoryUpdateIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/expenses`

List Expenses

Parameters:

- `query` `ref` (optional, object)
- `query` `date_from` (optional, object)
- `query` `date_to` (optional, object)
- `query` `amount` (optional, object)
- `query` `category` (optional, object)
- `query` `vendor` (optional, object)
- `query` `method` (optional, object)
- `query` `trx_id` (optional, object)
- `query` `memo_no` (optional, object)
- `query` `status` (optional, object)
- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/expenses`

Add Expense

JSON request body: `ExpenseCreateIn`.

Responses: `201` Successful Response, `422` Validation Error.

## PATCH `/api/expenses/{expense_id}`

Edit Expense

Parameters:

- `path` `expense_id` (required, integer)

JSON request body: `ExpenseUpdateIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/expenses/{expense_id}/approve`

Approve

Parameters:

- `path` `expense_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/expenses/{expense_id}/events`

Expense Events

Parameters:

- `path` `expense_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/expenses/{expense_id}/reject`

Reject

Parameters:

- `path` `expense_id` (required, integer)

JSON request body: `ExpenseRejectIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/expenses/{expense_ref}`

Get Expense

Parameters:

- `path` `expense_ref` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/exports/bookings.csv`

Export Bookings

Parameters:

- `query` `date_from` (optional, object)
- `query` `date_to` (optional, object)
- `query` `facility_id` (optional, object)
- `query` `channel` (optional, object)
- `query` `status` (optional, object)
- `query` `ref` (optional, object)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/exports/closings.csv`

Export Closings

Parameters:

- `query` `date` (optional, object)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/exports/expenses.csv`

Export Expenses

Parameters:

- `query` `ref` (optional, object)
- `query` `date_from` (optional, object)
- `query` `date_to` (optional, object)
- `query` `amount` (optional, object)
- `query` `category` (optional, object)
- `query` `vendor` (optional, object)
- `query` `method` (optional, object)
- `query` `trx_id` (optional, object)
- `query` `memo_no` (optional, object)
- `query` `status` (optional, object)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/exports/payments.csv`

Export Payments

Parameters:

- `query` `received_from` (optional, object)
- `query` `received_to` (optional, object)
- `query` `method` (optional, object)
- `query` `status` (optional, object)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/exports/reports.csv`

Export Reports

Parameters:

- `query` `year` (optional, object)
- `query` `month` (optional, object)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/facilities`

List Facilities

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/facilities`

Create Facility

JSON request body: `object`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/health`

Health

Responses: `200` Successful Response.

## GET `/api/my/bookings`

List My Bookings

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/my/shareholding`

Get My Shareholding

Responses: `200` Successful Response.

## GET `/api/payments`

List Payments

Parameters:

- `query` `received_from` (optional, object)
- `query` `received_to` (optional, object)
- `query` `method` (optional, object)
- `query` `status` (optional, object)
- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/payments/booking/{booking_ref}`

Booking Payments

Parameters:

- `path` `booking_ref` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/payments/methods`

List Payment Methods

Responses: `200` Successful Response.

## POST `/api/payments/online/initiate`

Initiate Online

Parameters:

- `header` `Idempotency-Key` (required, string)

JSON request body: `OnlinePaymentIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/payments/online/{intent_id}/simulate/{result}`

Simulate Payment

Parameters:

- `path` `intent_id` (required, integer)
- `path` `result` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/payments/{payment_id}`

Payment Detail

Parameters:

- `path` `payment_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/payments/{payment_id}/reject`

Reject

Parameters:

- `path` `payment_id` (required, integer)

JSON request body: `PaymentRejectIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/payments/{payment_id}/verify`

Verify

Parameters:

- `path` `payment_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/payments/{payment_ref}/receipt`

Receipt

Parameters:

- `path` `payment_ref` (required, string)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/reports/approved`

List Approved Reports

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/reports/approved/{year}/{month}/expenses`

List Approved Expenses

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)
- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/reports/{year}/{month}`

Get Report

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/reports/{year}/{month}/approve`

Approve Monthly Report

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)

JSON request body: `ReportApproveIn`.

Responses: `200` Successful Response, `422` Validation Error.

## PATCH `/api/reports/{year}/{month}/checklist/{key}`

Change Report Checklist

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)
- `path` `key` (required, string)

JSON request body: `ReportChecklistUpdateIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/reports/{year}/{month}/eligible-shares`

Confirm Eligible Shares

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)

JSON request body: `EligibleSharesUpdateIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/reports/{year}/{month}/reopen`

Reopen Monthly Report

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)

JSON request body: `ReportReopenIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/reports/{year}/{month}/submit-review`

Submit Report For Review

Parameters:

- `path` `year` (required, integer)
- `path` `month` (required, integer)

JSON request body: `ReportReviewSubmitIn`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/settings`

List Settings

Responses: `200` Successful Response.

## POST `/api/settings`

Upsert Setting

JSON request body: `SettingUpdate`.

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/settings/public`

Public Settings

Responses: `200` Successful Response.

## GET `/api/shareholders`

List Shareholders

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/shareholders`

Add Shareholder

JSON request body: `ShareholderCreateIn`.

Responses: `201` Successful Response, `422` Validation Error.

## PATCH `/api/shareholders/{shareholder_id}`

Edit Shareholder

Parameters:

- `path` `shareholder_id` (required, integer)

JSON request body: `ShareholderUpdateIn`.

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/shareholders/{shareholder_id}/holdings`

Add Holding

Parameters:

- `path` `shareholder_id` (required, integer)

JSON request body: `ShareholdingCreateIn`.

Responses: `201` Successful Response, `422` Validation Error.

## GET `/api/statements/mine`

My Statements

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/statements/{statement_id}`

Get My Statement

Parameters:

- `path` `statement_id` (required, integer)

Responses: `200` Successful Response, `422` Validation Error.

## GET `/api/users`

List Users

Parameters:

- `query` `page` (optional, integer)
- `query` `size` (optional, integer)

Responses: `200` Successful Response, `422` Validation Error.

## POST `/api/users`

Create User

JSON request body: `StaffCreateIn`.

Responses: `201` Successful Response, `422` Validation Error.

## PATCH `/api/users/{user_id}/active`

Set Active

Parameters:

- `path` `user_id` (required, integer)
- `query` `active` (required, boolean)

Responses: `200` Successful Response, `422` Validation Error.
