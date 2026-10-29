import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";

const DEMO_PASSWORD = process.env.DEMO_PASSWORD ?? "DemoPool2026!";

type ApiResult<T> = {
  status: number;
  data: T | null;
  text: string;
};

type TurfSlot = {
  facility_id: number;
  start: string;
  status: string;
};

type PoolSession = {
  id: number;
  facility_id: number;
  remaining: number;
};

type Booking = {
  id: number;
  ref: string;
  total_amount: string;
};

type Payment = {
  id: number;
  status: string;
};

function dhakaDate(offsetDays = 0): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Dhaka",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date());
  const year = Number(parts.find((part) => part.type === "year")?.value);
  const month = Number(parts.find((part) => part.type === "month")?.value);
  const day = Number(parts.find((part) => part.type === "day")?.value);
  return new Date(Date.UTC(year, month - 1, day + offsetDays)).toISOString().slice(0, 10);
}

async function api<T>(
  page: Page,
  path: string,
  method = "GET",
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<ApiResult<T>> {
  const response = await page.evaluate(async ({ path, method, body, headers }) => {
    const csrf = document.cookie
      .split("; ")
      .find((cookie) => cookie.startsWith("csrf_token="))
      ?.split("=")
      .slice(1)
      .join("=") ?? "";
    const requestHeaders: Record<string, string> = { ...headers };
    if (method !== "GET") requestHeaders["X-CSRF-Token"] = csrf;
    if (body !== undefined) requestHeaders["Content-Type"] = "application/json";
    const result = await fetch(`/api${path}`, {
      method,
      credentials: "include",
      headers: requestHeaders,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const text = await result.text();
    let data: unknown = null;
    try {
      data = JSON.parse(text);
    } catch {
      data = null;
    }
    return { status: result.status, data, text };
  }, { path, method, body, headers });
  return response as ApiResult<T>;
}

async function signIn(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.getByPlaceholder("Email").fill(email);
  await page.getByPlaceholder("Password").fill(DEMO_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

async function newRolePage(
  browser: Browser,
  viewport: { width: number; height: number },
  email: string,
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ viewport });
  const page = await context.newPage();
  await signIn(page, email);
  return { context, page };
}

function expectStatus<T>(result: ApiResult<T>, status: number): asserts result is ApiResult<T> {
  expect(result.status, result.text).toBe(status);
}

test("runs the complete demo and protects pool capacity", async ({ browser, page }, testInfo) => {
  const viewport = page.viewportSize() ?? { width: 1280, height: 800 };
  const createdContexts: BrowserContext[] = [];
  const testOffset = testInfo.project.name === "mobile-375" ? 7 : 1;
  const today = dhakaDate();
  const onlineDay = dhakaDate(testOffset);
  const workDay = dhakaDate(testOffset + 1);
  const poolDay = dhakaDate(testInfo.project.name === "mobile-375" ? 4 : 3);

  await signIn(page, "demo-customer@example.com");
  await expect(page.getByText(/DEMO ENVIRONMENT/)).toBeVisible();
  await page.goto("/book");
  await page.getByLabel("Date").fill(onlineDay);
  const availableTurfSlot = page.getByRole("button", { name: "Select", exact: true }).first();
  await expect(availableTurfSlot).toBeEnabled();
  await availableTurfSlot.click();
  await page.getByRole("button", { name: "Hold and continue" }).click();
  await expect(page.getByRole("status").filter({ hasText: "is held" })).toBeVisible();
  await page.goto("/my-bookings");
  const simulatedPayment = page.getByRole("button", { name: /Pay .* SIMULATED/ }).first();
  await expect(simulatedPayment).toBeVisible();
  await simulatedPayment.click();
  await page.getByRole("button", { name: "Simulate success" }).click();
  const completedBooking = page.locator("article").first();
  await expect(completedBooking).toContainText("Confirmed");
  await expect(completedBooking).toContainText("SIMULATED PAYMENT · ✓ Verified");

  const staffSession = await newRolePage(
    browser, viewport, "demo-staff@example.com",
  );
  createdContexts.push(staffSession.context);
  await staffSession.page.goto("/new-booking");
  await expect(
    staffSession.page.getByRole("heading", { name: "Bookings", exact: true }),
  ).toBeVisible();
  const staffSlots = await api<TurfSlot[]>(
    staffSession.page, `/availability/turf?date=${onlineDay}`,
  );
  expectStatus(staffSlots, 200);
  const phoneSlot = staffSlots.data?.find((slot) => slot.status === "free");
  expect(phoneSlot).toBeDefined();
  const phoneBookingResponse = await api<Booking>(
    staffSession.page,
    "/bookings/staff",
    "POST",
    {
      facility_id: phoneSlot!.facility_id,
      starts_at: phoneSlot!.start,
      customer_name: "E2E Phone Customer",
      customer_phone: "01876543210",
      channel: "phone",
    },
  );
  expectStatus(phoneBookingResponse, 201);
  const phoneBooking = phoneBookingResponse.data!;
  const phonePaymentResponse = await api<Payment>(
    staffSession.page,
    `/bookings/${phoneBooking.id}/payments`,
    "POST",
    {
      amount: phoneBooking.total_amount,
      method: "bkash",
      received_at: new Date().toISOString(),
      trx_id: `E2E-BKASH-${Date.now()}`,
    },
  );
  expectStatus(phonePaymentResponse, 201);

  const walkInSlots = await api<TurfSlot[]>(
    staffSession.page, `/availability/turf?date=${workDay}`,
  );
  expectStatus(walkInSlots, 200);
  const walkInSlot = walkInSlots.data?.find((slot) => slot.status === "free");
  expect(walkInSlot).toBeDefined();
  const walkInResponse = await api<Booking>(
    staffSession.page,
    "/bookings/staff",
    "POST",
    {
      facility_id: walkInSlot!.facility_id,
      starts_at: walkInSlot!.start,
      customer_name: "E2E Walk-in Customer",
      customer_phone: "01876543211",
      channel: "walk_in",
    },
  );
  expectStatus(walkInResponse, 201);
  const walkInBooking = walkInResponse.data!;
  const cashPaymentResponse = await api<Payment>(
    staffSession.page,
    `/bookings/${walkInBooking.id}/payments`,
    "POST",
    {
      amount: walkInBooking.total_amount,
      method: "cash",
      received_at: new Date().toISOString(),
    },
  );
  expectStatus(cashPaymentResponse, 201);

  const accountantSession = await newRolePage(
    browser, viewport, "demo-accountant@example.com",
  );
  createdContexts.push(accountantSession.context);
  await accountantSession.page.goto("/reports");
  await expect(
    accountantSession.page.getByRole("heading", {
      name: "Monthly financial report",
      exact: true,
    }),
  ).toBeVisible();
  const receivedPayments = await api<{ items: Payment[] }>(
    accountantSession.page, "/payments?status=received",
  );
  expectStatus(receivedPayments, 200);
  expect(receivedPayments.data?.items.length).toBeGreaterThanOrEqual(2);
  for (const payment of receivedPayments.data?.items ?? []) {
    const verification = await api<{ booking_status: string }>(
      accountantSession.page, `/payments/${payment.id}/verify`, "POST",
    );
    expectStatus(verification, 200);
    expect(verification.data?.booking_status).toBe("confirmed");
  }

  await staffSession.page.goto("/expenses");
  const expenseResponse = await api<{
    ref: string;
    id: number;
    status: string;
  }>(staffSession.page, "/expenses", "POST", {
    expense_date: today,
    payment_date: today,
    category: "electricity",
    description: "E2E electricity expense",
    amount: "1250.00",
    method: "cash",
    vendor: "E2E Utility Vendor",
  });
  expectStatus(expenseResponse, 201);
  const expense = expenseResponse.data!;
  const foundExpense = await api<{ items: { ref: string }[] }>(
    staffSession.page, `/expenses?ref=${encodeURIComponent(expense.ref)}`,
  );
  expectStatus(foundExpense, 200);
  expect(foundExpense.data?.items[0]?.ref).toBe(expense.ref);
  const approvedExpense = await api<{ status: string }>(
    accountantSession.page, `/expenses/${expense.id}/approve`, "POST",
  );
  expectStatus(approvedExpense, 200);
  expect(approvedExpense.data?.status).toBe("approved");

  const closingResponse = await api<{ id: number; status: string }>(
    staffSession.page, "/closings", "POST", {
      business_date: today,
      notes: "E2E daily closing",
      difference_notes: null,
    },
  );
  expectStatus(closingResponse, 201);
  const adminSession = await newRolePage(browser, viewport, "demo-admin@example.com");
  createdContexts.push(adminSession.context);
  await adminSession.page.goto("/closings");
  const reviewedClosing = await api<{ status: string }>(
    adminSession.page,
    `/closings/${closingResponse.data!.id}/review`,
    "POST",
    { review_notes: "E2E manager review" },
  );
  expectStatus(reviewedClosing, 200);
  expect(reviewedClosing.data?.status).toBe("reviewed");

  const ownerSession = await newRolePage(browser, viewport, "demo-owner@example.com");
  createdContexts.push(ownerSession.context);
  const reportMonth = today.slice(0, 7);
  const [yearText, monthText] = reportMonth.split("-");
  const year = Number(yearText);
  const month = Number(monthText);
  const reportPath = `/reports/${year}/${month}`;
  const currentReport = await api<{ status: string }>(
    accountantSession.page, reportPath,
  );
  expectStatus(currentReport, 200);
  if (currentReport.data?.status === "approved") {
    const reopened = await api(
      ownerSession.page, `${reportPath}/reopen`, "POST",
      { reason: "E2E mobile viewport report revision" },
    );
    expectStatus(reopened, 200);
  }
  const eligibleShares = await api(
    accountantSession.page, `${reportPath}/eligible-shares`, "POST",
    { total_shares: 50, reason: "E2E register review" },
  );
  expectStatus(eligibleShares, 200);
  const distribution = await api(
    accountantSession.page, "/distribution", "POST",
    {
      year,
      month,
      pool_amount: "2500.00",
      reason: "E2E report distribution",
    },
  );
  expectStatus(distribution, 200);
  for (const key of [
    "payments_verified",
    "expenses_approved",
    "closings_reviewed",
    "register_confirmed",
    "distribution_recorded",
  ]) {
    const checklist = await api(
      accountantSession.page, `${reportPath}/checklist/${key}`, "PATCH",
      { is_done: true, note: `E2E reviewed ${key}` },
    );
    expectStatus(checklist, 200);
  }
  const submitted = await api(
    accountantSession.page, `${reportPath}/submit-review`, "POST",
    { note: "E2E accountant prepared the report" },
  );
  expectStatus(submitted, 200);
  const approvedReport = await api<{ status: string }>(
    ownerSession.page, `${reportPath}/approve`, "POST",
    { exception_reason: null },
  );
  expectStatus(approvedReport, 200);
  expect(approvedReport.data?.status).toBe("approved");

  const shareholderSession = await newRolePage(
    browser, viewport, "demo-holder-20@example.com",
  );
  createdContexts.push(shareholderSession.context);
  await shareholderSession.page.goto("/statement");
  await expect(
    shareholderSession.page.getByRole("heading", { name: "My shareholder statement" }),
  ).toBeVisible();
  await expect(shareholderSession.page.getByText("20 share(s)", { exact: false })).toBeVisible();
  const statements = await api<{ items: { id: number }[] }>(
    shareholderSession.page, "/statements/mine",
  );
  expectStatus(statements, 200);
  expect(statements.data?.items.length).toBeGreaterThanOrEqual(2);
  const deniedEdit = await api(
    shareholderSession.page,
    `/payments/${phonePaymentResponse.data!.id}/verify`,
    "POST",
  );
  expect(deniedEdit.status).toBe(403);

  await ownerSession.page.goto("/emails");
  const deliveries = await api<{ items: { id: number; kind: string }[] }>(
    ownerSession.page, "/emails",
  );
  expectStatus(deliveries, 200);
  const statementDelivery = deliveries.data?.items.find(
    (delivery) => delivery.kind === "shareholder_statement",
  );
  expect(statementDelivery).toBeDefined();
  const preview = await api(
    ownerSession.page, `/emails/${statementDelivery!.id}/preview`,
  );
  expectStatus(preview, 200);
  expect(preview.text).toContain("not a promise of dividends");

  const poolSessions = await api<PoolSession[]>(
    page, `/availability/pool?date=${poolDay}`,
  );
  expectStatus(poolSessions, 200);
  const lastPlaces = poolSessions.data?.find((session) => session.remaining === 2);
  expect(lastPlaces).toBeDefined();
  const secondCustomer = await newRolePage(
    browser, viewport, "demo-customer-two@example.com",
  );
  createdContexts.push(secondCustomer.context);
  const raceResults = await Promise.all([
    api<Booking>(page, "/bookings", "POST", {
      facility_id: lastPlaces!.facility_id,
      pool_session_id: lastPlaces!.id,
      participants: 2,
    }),
    api<Booking>(secondCustomer.page, "/bookings", "POST", {
      facility_id: lastPlaces!.facility_id,
      pool_session_id: lastPlaces!.id,
      participants: 2,
    }),
  ]);
  expect(raceResults.map((result) => result.status).sort()).toEqual([201, 409]);

  const dimensions = await page.evaluate(() => ({
    width: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width);

  const guestContext = await browser.newContext({ viewport });
  createdContexts.push(guestContext);
  const guestPage = await guestContext.newPage();
  await guestPage.goto("/login");
  expect(await guestPage.locator("html").getAttribute("lang")).toBe("en");
  expect(await guestPage.locator('meta[name="viewport"]').count()).toBe(1);
  await guestPage.keyboard.press("Tab");
  await expect(guestPage.getByLabel("Email")).toBeFocused();

  for (const context of createdContexts) {
    await context.close();
  }
});
