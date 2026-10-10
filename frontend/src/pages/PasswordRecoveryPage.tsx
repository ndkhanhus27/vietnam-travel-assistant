import { FormEvent, useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { api, ApiError, sessionStore } from "../api/client";
import { isGmailAddress } from "../auth/emailPolicy";
import { AuthLayout } from "../components/AuthLayout";
import { PasswordField } from "../components/PasswordField";

export function PasswordRecoveryPage({ reset = false }: { reset?: boolean }) {
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
    if (reset && password !== confirmation) return setError("Mật khẩu xác nhận không khớp.");
    const email = String(form.get("email") || "").trim();
    if (!reset && !isGmailAddress(email)) return setError("Chỉ hỗ trợ địa chỉ @gmail.com.");
    submitting.current = true;
    setLoading(true);
    try {
      if (reset) {
        await api.resetPassword(token, password, confirmation);
        sessionStore.clear();
        setMessage("Mật khẩu đã được cập nhật. Hãy đăng nhập lại bằng mật khẩu mới.");
      } else {
        const result = await api.forgotPassword(email.toLowerCase());
        setMessage(result.message);
      }
      setDone(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Không thể kết nối. Vui lòng thử lại.");
    } finally {
      submitting.current = false;
      setLoading(false);
    }
  }

  return <AuthLayout>
    <div className="auth-brand">Trợ lý du lịch Việt Nam</div>
    <h1 id="auth-title">{reset ? "Đặt lại mật khẩu" : "Quên mật khẩu?"}</h1>
    <p className="auth-subtitle">{reset ? "Chọn mật khẩu mới cho tài khoản của bạn." : "Nhập Gmail của bạn để nhận liên kết khôi phục."}</p>
    {reset && !token ? <div className="form-error" role="alert">Liên kết thiếu mã xác nhận. Hãy yêu cầu liên kết mới.</div> : !done && <form className="auth-form" onSubmit={submit}>
      {reset ? <>
        <PasswordField label="Mật khẩu mới" autoComplete="new-password" disabled={loading} />
        <PasswordField label="Xác nhận mật khẩu" name="confirm_password" autoComplete="new-password" disabled={loading} />
      </> : <label><span>Địa chỉ Gmail</span><input name="email" type="email" autoComplete="email" defaultValue={initialEmail} required disabled={loading} /></label>}
      <button className="primary-button auth-submit" disabled={loading}>{loading ? "Đang xử lý..." : reset ? "Lưu mật khẩu mới" : "Gửi liên kết xác nhận"}</button>
    </form>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {message && <p role="status">{message}</p>}
    <p className="auth-switch"><Link to="/login">Quay lại đăng nhập</Link></p>
    {reset && <p><Link to="/forgot-password">Yêu cầu liên kết mới</Link></p>}
  </AuthLayout>;
}
