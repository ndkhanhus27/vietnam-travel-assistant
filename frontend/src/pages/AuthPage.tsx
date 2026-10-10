import { FormEvent, useCallback, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { GoogleSignIn } from "../components/GoogleSignIn";
import { AuthLayout } from "../components/AuthLayout";
import { PasswordField } from "../components/PasswordField";
import { isGmailAddress } from "../auth/emailPolicy";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { authenticate } = useAuth();
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [googleNotice, setGoogleNotice] = useState("");
  const [linkCredential, setLinkCredential] = useState<string | null>(null);
  const submitting = useRef(false);
  const isLogin = mode === "login";
  const from = (location.state as { from?: string } | null)?.from;
  const destination = from?.startsWith("/") && !from.startsWith("//") ? from : "/";

  const handleError = useCallback((cause: unknown) => {
    if (!(cause instanceof ApiError)) return setError("Không thể kết nối đến máy chủ. Vui lòng thử lại.");
    if (cause.status === 401) return setError("Thông tin đăng nhập không đúng hoặc đã hết hạn. Vui lòng thử lại.");
    if (cause.status === 429) return setError(cause.retryAfter ? `Vui lòng thử lại sau ${cause.retryAfter} giây.` : "Bạn thao tác quá nhanh. Vui lòng thử lại sau.");
    setError(cause.message);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    setError("");
    const normalizedEmail = email.trim().toLowerCase();
    if (!linkCredential && !isGmailAddress(normalizedEmail)) return setError("Chỉ hỗ trợ địa chỉ @gmail.com. Vui lòng sử dụng Gmail.");
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    if (!password) return setError("Vui lòng nhập mật khẩu.");
    if (!isLogin && !linkCredential && password !== String(form.get("confirm_password") || "")) return setError("Mật khẩu xác nhận không khớp.");
    submitting.current = true;
    setLoading(true);
    try {
      const result = linkCredential
        ? await api.googleLogin(linkCredential, password)
        : isLogin
          ? await api.login({ email: normalizedEmail, password })
          : await api.register({ email: normalizedEmail, password, display_name: null });
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
    submitting.current = true;
    setLoading(true);
    setError("");
    try {
      const result = await api.googleLogin(credential);
      authenticate(result);
      navigate(destination, { replace: true });
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 409) {
        setLinkCredential(credential);
        setError("");
      } else handleError(cause);
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }, [authenticate, destination, handleError, navigate]);

  return <AuthLayout>
    <div className="auth-brand">Trợ lý du lịch Việt Nam</div>
    <h1 id="auth-title">{linkCredential ? "Liên kết Google" : isLogin ? "Đăng nhập" : "Tạo tài khoản"}</h1>
    <p className="auth-subtitle">{linkCredential ? "Nhập mật khẩu hiện tại để liên kết tài khoản." : isLogin ? "Tiếp tục cuộc trò chuyện của bạn." : "Đăng ký bằng Gmail hoặc tài khoản Google."}</p>
    <form className="auth-form" onSubmit={submit} key={linkCredential ? "link" : mode}>
      {!linkCredential && <label><span>Địa chỉ Gmail</span><input name="email" type="email" autoComplete="email" placeholder="ban@gmail.com" value={email} onChange={event => setEmail(event.target.value)} required disabled={loading} autoFocus /></label>}
      <PasswordField autoComplete={isLogin || linkCredential ? "current-password" : "new-password"} disabled={loading} autoFocus={Boolean(linkCredential)} />
      {!isLogin && !linkCredential && <PasswordField label="Xác nhận mật khẩu" name="confirm_password" autoComplete="new-password" disabled={loading} />}
      {(isLogin || linkCredential) && <Link className="auth-forgot" to="/forgot-password" state={{ email }}>Quên mật khẩu?</Link>}
      {error && <div className="form-error" role="alert">{error}</div>}
      <button className="primary-button auth-submit" disabled={loading}>{loading ? "Đang xử lý..." : linkCredential ? "Xác nhận liên kết Google" : isLogin ? "Đăng nhập" : "Tạo tài khoản"}</button>
    </form>
    {linkCredential ? <button className="auth-back" type="button" onClick={() => { setLinkCredential(null); setError(""); }} disabled={loading}>Quay lại đăng nhập</button> : <>
      <p className="auth-switch">{isLogin ? "Chưa có tài khoản?" : "Đã có tài khoản?"} <Link to={isLogin ? "/register" : "/login"}>{isLogin ? "Đăng ký" : "Đăng nhập"}</Link></p>
      <div className="or-divider"><span>hoặc</span></div>
      <GoogleSignIn disabled={loading} onCredential={googleCredential} onUnavailable={setGoogleNotice} />
      {googleNotice && <p className="auth-provider-notice" role="status">{googleNotice}</p>}
    </>}
  </AuthLayout>;
}
