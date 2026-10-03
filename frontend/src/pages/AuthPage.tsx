import { FormEvent, useCallback, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { GoogleSignIn } from "../components/GoogleSignIn";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { authenticate } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const isLogin = mode === "login";
  const destination = (location.state as { from?: string } | null)?.from || "/";

  const handleError = useCallback((cause: unknown) => {
    if (!(cause instanceof ApiError)) return setError("Không thể kết nối đến máy chủ. Vui lòng thử lại.");
    if (cause.status === 401) return setError("Email hoặc mật khẩu không đúng.");
    if (cause.status === 409) return setError("Email này đã được đăng ký.");
    if (cause.status === 422) return setError("Vui lòng kiểm tra lại thông tin đã nhập.");
    if (cause.status === 429) return setError(cause.retryAfter ? `Bạn thao tác quá nhanh. Vui lòng thử lại sau ${cause.retryAfter} giây.` : "Bạn thao tác quá nhanh. Vui lòng thử lại sau.");
    setError(cause.message);
  }, []);

  const handleGoogleError = useCallback((cause: unknown) => {
    if (!(cause instanceof ApiError)) {
      setError("Không thể đăng nhập bằng Google. Vui lòng thử lại.");
      return;
    }
    if (cause.status === 429) {
      setError(cause.retryAfter
        ? `Bạn thao tác quá nhanh. Vui lòng thử lại sau ${cause.retryAfter} giây.`
        : "Bạn thao tác quá nhanh. Vui lòng thử lại sau.");
      return;
    }
    if (cause.status === 0 || cause.status >= 500) {
      setError("Không thể kết nối để đăng nhập bằng Google. Vui lòng thử lại.");
      return;
    }
    setError("Không thể đăng nhập bằng Google. Vui lòng thử lại.");
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    setError("");
    const form = new FormData(event.currentTarget);
    const displayName = String(form.get("display_name") || "").trim();
    const email = String(form.get("email") || "").trim();
    const password = String(form.get("password") || "");
    if (!email || !password) return setError("Vui lòng điền đầy đủ thông tin bắt buộc.");
    submitting.current = true;
    setLoading(true);
    try {
      const result = isLogin
        ? await api.login({ email, password })
        : await api.register({ display_name: displayName || null, email, password });
      authenticate(result);
      navigate(destination, { replace: true });
    } catch (cause) {
      handleError(cause);
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }

  const googleCredential = useCallback(async (credential: string) => {
    if (submitting.current) return;
    if (!credential) {
      setError("Google không trả về thông tin đăng nhập. Vui lòng thử lại.");
      return;
    }
    setError("");
    submitting.current = true;
    setLoading(true);
    try {
      const result = await api.googleLogin(credential);
      authenticate(result);
      navigate(destination, { replace: true });
    } catch (cause) {
      handleGoogleError(cause);
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }, [authenticate, destination, handleGoogleError, navigate]);

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">Vietnam Travel Advisor</div>
        <h1 id="auth-title">{isLogin ? "Chào mừng bạn trở lại" : "Tạo tài khoản"}</h1>
        <p className="auth-subtitle">{isLogin ? "Đăng nhập để tiếp tục những cuộc trò chuyện du lịch đã lưu." : "Tạo tài khoản để lưu lại các tư vấn cho hành trình khám phá Việt Nam."}</p>
        <form onSubmit={submit} className="auth-form">
          {!isLogin && <label><span>Tên hiển thị</span><input name="display_name" autoComplete="name" disabled={loading} /></label>}
          <label><span>Địa chỉ email</span><input name="email" type="email" autoComplete="email" required disabled={loading} /></label>
          <label><span>Mật khẩu</span><input name="password" type="password" minLength={8} maxLength={128} autoComplete={isLogin ? "current-password" : "new-password"} required disabled={loading} /></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="primary-button auth-submit" disabled={loading}>{loading ? "Đang xử lý..." : isLogin ? "Đăng nhập" : "Tạo tài khoản"}</button>
        </form>
        <div className="or-divider"><span>hoặc</span></div>
        <GoogleSignIn disabled={loading} onCredential={googleCredential} onUnavailable={setError} />
        <p className="auth-switch">{isLogin ? "Chưa có tài khoản?" : "Đã có tài khoản?"} <Link to={isLogin ? "/register" : "/login"}>{isLogin ? "Đăng ký" : "Đăng nhập"}</Link></p>
      </section>
    </main>
  );
}
