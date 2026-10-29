import { Role } from "./api";

export interface NavItem { path: string; label: string; phase: number }

const T = { path: "/timetable", label: "Timetable", phase: 2 };
const NEW = { path: "/new-booking", label: "New booking", phase: 3 };
const PAY = { path: "/payments", label: "Payments", phase: 4 };
const EXP = { path: "/expenses", label: "Expenses", phase: 5 };
const CLOSE = { path: "/closings", label: "Daily closing", phase: 5 };
const REP = { path: "/reports", label: "Reports", phase: 6 };

export const NAV: Record<Role, NavItem[]> = {
  customer: [{ path: "/book", label: "Book", phase: 3 }, { path: "/my-bookings", label: "My bookings", phase: 3 }],
  staff: [T, NEW, PAY, EXP, CLOSE],
  accountant: [PAY, EXP, CLOSE, REP, { path: "/audit", label: "Audit", phase: 1 }],
  admin: [T, NEW, PAY, EXP, CLOSE, REP],
  owner: [T, NEW, PAY, EXP, CLOSE, REP, { path: "/users", label: "Users", phase: 1 }, { path: "/audit", label: "Audit", phase: 1 }],
  shareholder: [{ path: "/overview", label: "Overview", phase: 6 }, { path: "/statement", label: "My statement", phase: 7 }, T],
};
