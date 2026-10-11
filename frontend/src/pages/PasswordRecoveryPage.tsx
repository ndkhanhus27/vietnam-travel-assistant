import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, ApiError, sessionStore } from "../api/client";
import { isGmailAddress } from "../auth/emailPolicy";
import { AuthLayout } from "../components/AuthLayout";
import { PasswordField } from "../components/PasswordField";
import { Button } from "antd";
import { useLocale } from "../locale/LocaleProvider";
import { localizeNotification } from "../locale/notifications";

export function PasswordRecoveryPage({ reset = false }: { reset?: boolean }) {
  const { t } = useLocale();
  const location = useLocation();
  const initialEmail = (location.state as { email?: string } | null)?.email || "";
  const [token] = useState(() => {
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    return value;
  });
  useEffect(() => {
    if (reset && token) window.history.replaceState(window.history.state, "", window.location.pathname);
  }, [reset, token]);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState(false);
  const submitting = useRef(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    const form = new FormData(event.currentTarget);
    const password = String(form.get("password") || "");
    const confirmation = String(form.get("confirm_password") || "");
    setError("");
    setMessage("");
    if (reset && password !== confirmation) return setError(t("Mật khẩu xác nhận không khớp.", "The passwords do not match."));
    const email = String(form.get("email") || "").trim();
    if (!reset && !isGmailAddress(email)) return setError(t("Chỉ hỗ trợ địa chỉ @gmail.com.", "Only @gmail.com addresses are supported."));
    submitting.current = true;
    setLoading(true);
    try {
      if (reset) {
        await api.resetPassword(token, password, confirmation);
        sessionStore.clear();
        setMessage(t("Mật khẩu đã được cập nhật. Hãy đăng nhập lại bằng mật khẩu mới.", "Your password has been updated. Sign in again with the new password."));
      } else {
        const result = await api.forgotPassword(email.toLowerCase());
        setMessage(result.message);
      }
      setDone(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("Không thể kết nối. Vui lòng thử lại.", "Could not connect. Please try again."));
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }

  return <AuthLayout>
    <div className="auth-brand">Vietnam Travel Advisor</div>
    <h1 id="auth-title">{reset ? t("Đặt lại mật khẩu", "Reset password") : t("Quên mật khẩu?", "Forgot password?")}</h1>
    <p className="auth-subtitle">{reset ? t("Chọn mật khẩu mới cho tài khoản của bạn.", "Choose a new password for your account.") : t("Nhập Gmail của bạn để nhận liên kết khôi phục.", "Enter your Gmail address to receive a recovery link.")}</p>
    {reset && !token ? <div className="form-error" role="alert">{t("Liên kết thiếu mã xác nhận. Hãy yêu cầu liên kết mới.", "The recovery token is missing. Request a new link.")}</div> : !done && <form className="auth-form" onSubmit={submit}>
      {reset ? <>
        <PasswordField label={t("Mật khẩu mới", "New password")} autoComplete="new-password" disabled={loading} />
        <PasswordField label={t("Xác nhận mật khẩu", "Confirm password")} name="confirm_password" autoComplete="new-password" disabled={loading} />
      </> : <label><span>{t("Địa chỉ Gmail", "Gmail address")}</span><input name="email" type="email" autoComplete="email" defaultValue={initialEmail} required disabled={loading} /></label>}
      <Button htmlType="submit" type="primary" className="auth-submit" loading={loading}>{reset ? t("Lưu mật khẩu mới", "Save new password") : t("Gửi liên kết xác nhận", "Send recovery link")}</Button>
    </form>}
    {error && <div className="form-error" role="alert">{localizeNotification(error)}</div>}
    {message && <p role="status">{message}</p>}
    <p className="auth-switch"><Link to="/login">{t("Quay lại đăng nhập", "Back to sign in")}</Link></p>
    {reset && <p><Link to="/forgot-password">{t("Yêu cầu liên kết mới", "Request a new link")}</Link></p>}
  </AuthLayout>;
}
