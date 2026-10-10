import { FormEvent, useCallback, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { GoogleSignIn } from "../components/GoogleSignIn";
import { isGmailAddress } from "../auth/emailPolicy";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { authenticate } = useAuth();
  const [step, setStep] = useState<"email" | "password" | "link">("email");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
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
    if (step === "email") {
      if (!isGmailAddress(email)) return setError("Chỉ hỗ trợ địa chỉ @gmail.com. Vui lòng sử dụng Gmail.");
      setEmail(email.trim().toLowerCase());
      setStep("password");
      return;
    }
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirm_password") || "");
    if (!password) return setError("Vui lòng nhập mật khẩu.");
    if (!isLogin && step !== "link" && password !== confirmation) return setError("Mật khẩu xác nhận không khớp.");
    submitting.current = true;
    setLoading(true);
    try {
      const result = step === "link" && linkCredential
        ? await api.googleLogin(linkCredential, password)
        : isLogin
          ? await api.login({ email, password })
          : await api.register({ email, password, display_name: String(form.get("display_name") || "").trim() || null });
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
        setStep("link");
        setError("");
      } else handleError(cause);
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }, [authenticate, destination, handleError, navigate]);

  const back = () => { setStep("email"); setLinkCredential(null); setShowPassword(false); setError(""); };
  const title = step === "link" ? "Liên kết tài khoản Google" : step === "password" ? isLogin ? "Nhập mật khẩu" : "Tạo mật khẩu" : isLogin ? "Đăng nhập" : "Tạo tài khoản";

  return <main className="auth-page"><section className="auth-panel" aria-labelledby="auth-title">
    <div className="auth-brand">Vietnam Travel Advisor</div>
    <h1 id="auth-title">{title}</h1>
    {step === "link" && <p className="auth-subtitle" role="status">Gmail vừa chọn đã có tài khoản. Xác nhận mật khẩu hiện tại để liên kết và giữ các cuộc trò chuyện của bạn.</p>}
    {step === "password" && <div className="auth-email-summary"><span>{email}</span><button type="button" onClick={back} disabled={loading}>Thay đổi</button></div>}
    <form className="auth-form" onSubmit={submit} key={step}>
      {step === "email" ? <label><span>Địa chỉ Gmail</span><input name="email" type="email" autoComplete="email" placeholder="ban@gmail.com" value={email} onChange={event => setEmail(event.target.value)} required disabled={loading} autoFocus /></label> : <>
        {!isLogin && step !== "link" && <label><span>Tên hiển thị</span><input name="display_name" autoComplete="name" maxLength={120} disabled={loading} /></label>}
        <label><span>Mật khẩu</span><input name="password" type={showPassword ? "text" : "password"} minLength={8} maxLength={128} autoComplete={isLogin || step === "link" ? "current-password" : "new-password"} required disabled={loading} autoFocus /></label>
        {!isLogin && step !== "link" && <label><span>Xác nhận mật khẩu</span><input name="confirm_password" type={showPassword ? "text" : "password"} minLength={8} maxLength={128} autoComplete="new-password" required disabled={loading} /></label>}
        <label className="auth-password-toggle"><input type="checkbox" checked={showPassword} onChange={event => setShowPassword(event.target.checked)} />Hiện mật khẩu</label>
        {(isLogin || step === "link") && <Link className="auth-forgot" to="/forgot-password" state={{ email }}>Quên mật khẩu?</Link>}
      </>}
      {error && <div className="form-error" role="alert">{error}</div>}
      <button className="primary-button auth-submit" disabled={loading}>{loading ? "Đang xử lý..." : step === "link" ? "Xác nhận liên kết Google" : "Tiếp tục"}</button>
    </form>
    {step === "email" ? <>
      <div className="or-divider"><span>hoặc</span></div>
      <GoogleSignIn disabled={loading} onCredential={googleCredential} onUnavailable={setError} />
      <p className="auth-switch">{isLogin ? "Chưa có tài khoản?" : "Đã có tài khoản?"} <Link to={isLogin ? "/register" : "/login"}>{isLogin ? "Đăng ký" : "Đăng nhập"}</Link></p>
    </> : <button className="auth-back" type="button" onClick={back} disabled={loading}>Quay lại</button>}
  </section></main>;
}
