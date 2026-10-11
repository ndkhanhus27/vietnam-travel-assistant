import { FormEvent, useCallback, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { GoogleSignIn } from "../components/GoogleSignIn";
import { AuthLayout } from "../components/AuthLayout";
import { PasswordField } from "../components/PasswordField";
import { isGmailAddress } from "../auth/emailPolicy";
import { Button } from "antd";
import { useLocale } from "../locale/LocaleProvider";
import { localizeNotification } from "../locale/notifications";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { authenticate } = useAuth();
  const { t } = useLocale();
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
    if (!(cause instanceof ApiError)) return setError(t("Không thể kết nối đến máy chủ. Vui lòng thử lại.", "Could not connect to the server. Please try again."));
    if (cause.status === 401) return setError(t("Thông tin đăng nhập không đúng hoặc đã hết hạn. Vui lòng thử lại.", "Your credentials are incorrect or expired. Please try again."));
    if (cause.status === 429) return setError(cause.retryAfter ? t(`Vui lòng thử lại sau ${cause.retryAfter} giây.`, `Please try again in ${cause.retryAfter} seconds.`) : t("Bạn thao tác quá nhanh. Vui lòng thử lại sau.", "Too many attempts. Please try again later."));
    setError(cause.message);
  }, [t]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    setError("");
    const normalizedEmail = email.trim().toLowerCase();
    if (!linkCredential && !isGmailAddress(normalizedEmail)) return setError(t("Chỉ hỗ trợ địa chỉ @gmail.com. Vui lòng sử dụng Gmail.", "Only @gmail.com addresses are supported."));
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    if (!password) return setError(t("Vui lòng nhập mật khẩu.", "Please enter your password."));
    if (!isLogin && !linkCredential && password !== String(form.get("confirm_password") || "")) return setError(t("Mật khẩu xác nhận không khớp.", "The passwords do not match."));
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
    <div className="auth-brand">Vietnam Travel Advisor</div>
    <h1 id="auth-title">{linkCredential ? t("Liên kết Google", "Link Google") : isLogin ? t("Đăng nhập", "Sign in") : t("Tạo tài khoản", "Create account")}</h1>
    <p className="auth-subtitle">{linkCredential ? t("Nhập mật khẩu hiện tại để liên kết tài khoản.", "Enter your current password to link this account.") : isLogin ? t("Chào mừng bạn quay lại.", "Welcome back.") : t("Bắt đầu hành trình chỉ trong vài bước.", "Start your journey in a few simple steps.")}</p>
    {!linkCredential && <>
      <GoogleSignIn disabled={loading} onCredential={googleCredential} onUnavailable={setGoogleNotice} />
      {googleNotice && <p className="auth-provider-notice" role="status">{localizeNotification(googleNotice)}</p>}
      <div className="or-divider"><span>{t("hoặc", "or")}</span></div>
    </>}
    <form className="auth-form" onSubmit={submit} key={linkCredential ? "link" : mode}>
      {!linkCredential && <label><span>{t("Địa chỉ Gmail", "Gmail address")}</span><input name="email" type="email" autoComplete="email" placeholder="you@gmail.com" value={email} onChange={event => setEmail(event.target.value)} required disabled={loading} autoFocus /></label>}
      <PasswordField autoComplete={isLogin || linkCredential ? "current-password" : "new-password"} disabled={loading} autoFocus={Boolean(linkCredential)} />
      {!isLogin && !linkCredential && <PasswordField label={t("Xác nhận mật khẩu", "Confirm password")} name="confirm_password" autoComplete="new-password" disabled={loading} />}
      {(isLogin || linkCredential) && <Link className="auth-forgot" to="/forgot-password" state={{ email }}>{t("Quên mật khẩu?", "Forgot password?")}</Link>}
      {error && <div className="form-error" role="alert">{localizeNotification(error)}</div>}
      <Button htmlType="submit" type="primary" className="auth-submit" loading={loading}>{linkCredential ? t("Xác nhận liên kết Google", "Confirm Google link") : isLogin ? t("Đăng nhập", "Sign in") : t("Tạo tài khoản", "Create account")}</Button>
    </form>
    {linkCredential ? <button className="auth-back" type="button" onClick={() => { setLinkCredential(null); setError(""); }} disabled={loading}>{t("Quay lại đăng nhập", "Back to sign in")}</button> :
      <p className="auth-switch">{isLogin ? t("Chưa có tài khoản?", "New here?") : t("Đã có tài khoản?", "Already have an account?")} <Link to={isLogin ? "/register" : "/login"}>{isLogin ? t("Đăng ký", "Create account") : t("Đăng nhập", "Sign in")}</Link></p>}
  </AuthLayout>;
}
