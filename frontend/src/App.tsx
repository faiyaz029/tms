import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { NAV } from "./nav";
import Layout from "./components/Layout";
import { CompleteProfile, Login, Register } from "./pages/AuthPages";
import Placeholder from "./pages/Placeholder";
import Users from "./pages/Users";

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
  const paths = [...new Set(Object.values(NAV).flat().map((i) => i.path))].filter((p) => p !== "/users");
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />
      <Route path="/complete-profile" element={user ? <CompleteProfile /> : <Navigate to="/login" replace />} />
      <Route element={<Protected><Layout /></Protected>}>
        <Route index element={<Home />} />
        {paths.map((p) => <Route key={p} path={p} element={<Placeholder />} />)}
        <Route path="/users" element={user?.role === "owner" ? <Users /> : <Navigate to="/" replace />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
