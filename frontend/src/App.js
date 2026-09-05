import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { Toaster } from "sonner";
import { AuthProvider, useAuth } from "@/context/AuthContext";
import { hasRole } from "@/lib/api";
import { Layout } from "@/components/Layout";
import Dashboard from "@/pages/Dashboard";
import CaseDetail from "@/pages/CaseDetail";
import Ingest from "@/pages/Ingest";
import Jobs from "@/pages/Jobs";
import Login from "@/pages/Login";
import Users from "@/pages/Users";
import Zones from "@/pages/Zones";
import VesselProfile from "@/pages/VesselProfile";
import { ForgotPassword, ResetPassword } from "@/pages/PasswordReset";

const Protected = ({ children, role }) => {
  const { user } = useAuth();
  const loc = useLocation();
  if (user === null) return <div className="grid h-screen place-items-center font-mono text-xs text-slate-400" data-testid="auth-checking">Checking session…</div>;
  if (!user) return <Navigate to="/login" state={{ from: loc.pathname }} replace />;
  if (role && !hasRole(user, role)) return <Navigate to="/" replace />;
  return children;
};

function App() {
  return (
    <div className="App">
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
            <Route path="/reset-password" element={<ResetPassword />} />
            <Route element={<Protected><Layout /></Protected>}>
              <Route path="/" element={<Dashboard />} />
              <Route path="/cases/:id" element={<CaseDetail />} />
              <Route path="/vessels/:mmsi" element={<VesselProfile />} />
              <Route path="/zones" element={<Zones />} />
              <Route path="/ingest" element={<Ingest />} />
              <Route path="/jobs" element={<Jobs />} />
              <Route path="/users" element={<Protected role="admin"><Users /></Protected>} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
      <Toaster theme="dark" position="bottom-right" toastOptions={{ style: { background: "#162032", border: "1px solid #334155", color: "#F8FAFC" } }} />
    </div>
  );
}

export default App;
