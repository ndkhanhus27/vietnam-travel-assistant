import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthProvider";
import { AuthPage } from "./pages/AuthPage";
import { TravelChatPage } from "./pages/TravelChatPage";
import { AdminPage } from "./pages/AdminPage";

function ProtectedRoute() {
  const { user, bootstrapping } = useAuth();
  const location = useLocation();
  if (bootstrapping) return <main className="center-state"><p>Đang khôi phục phiên đăng nhập...</p></main>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

function PublicOnlyRoute() {
  const { user, bootstrapping } = useAuth();
  if (bootstrapping) return <main className="center-state"><p>Đang khôi phục phiên đăng nhập...</p></main>;
  return user ? <Navigate to="/" replace /> : <Outlet />;
}

export default function App() {
  return (
    <Routes>
      <Route element={<PublicOnlyRoute />}>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
      </Route>
      <Route element={<ProtectedRoute />}>
        <Route path="/" element={<TravelChatPage />} />
        <Route path="/c/:conversationId" element={<TravelChatPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
