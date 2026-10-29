import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { NAV } from "./nav";
import Layout from "./components/Layout";
import { CompleteProfile, Login, Register } from "./pages/AuthPages";
import Placeholder from "./pages/Placeholder";
import Users from "./pages/Users";
import { Book, MyBookings, StaffBookings, Timetable } from "./pages/BookingPages";
import Payments from "./pages/Payments";
import Expenses from "./pages/Expenses";
import Closings from "./pages/Closings";

function Protected({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-6">Loading…</p>;
  if (!user) return <Navigate to="/login" replace />;
  if (user.role === "customer" && !user.profile_complete) return <Navigate to="/complete-profile" replace />;
  return children;
}

function Home() {
  const { user } = useAuth();
  return <Navigate to={NAV[user!.role][0].path} replace />;
}

export default function App() {
  const { user } = useAuth();
  const paths = [...new Set(Object.values(NAV).flat().map((i) => i.path))]
    .filter((p) => !["/users", "/book", "/my-bookings", "/new-booking", "/timetable", "/payments", "/expenses", "/closings"].includes(p));
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/complete-profile" element={user ? <CompleteProfile /> : <Navigate to="/login" replace />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Home />} />
        {paths.map((p) => <Route key={p} path={p} element={<Placeholder />} />)}
        <Route path="/book" element={user?.role === "customer" ? <Book /> : <Navigate to="/" replace />} />
        <Route path="/my-bookings" element={user?.role === "customer" ? <MyBookings /> : <Navigate to="/" replace />} />
        <Route path="/new-booking" element={user && ["owner", "admin", "staff"].includes(user.role)
          ? <StaffBookings /> : <Navigate to="/" replace />} />
        <Route path="/timetable" element={user && ["owner", "admin", "staff", "shareholder"].includes(user.role)
          ? <Timetable /> : <Navigate to="/" replace />} />
        <Route path="/payments" element={user && ["owner", "admin", "staff", "accountant"].includes(user.role)
          ? <Payments /> : <Navigate to="/" replace />} />
        <Route path="/expenses" element={user && ["owner", "admin", "staff", "accountant"].includes(user.role)
          ? <Expenses /> : <Navigate to="/" replace />} />
        <Route path="/closings" element={user && ["owner", "admin", "staff", "accountant"].includes(user.role)
          ? <Closings /> : <Navigate to="/" replace />} />
        <Route path="/users" element={user?.role === "owner" ? <Users /> : <Navigate to="/" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
