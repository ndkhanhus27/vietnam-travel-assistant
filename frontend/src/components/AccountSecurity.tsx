import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import { Button } from "antd";
import { useLocale } from "../locale/LocaleProvider";

export function AccountSecurity({ email }: { email: string }) {
  const { t } = useLocale();
  const [methods, setMethods] = useState<{ has_password: boolean; google_linked: boolean } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    let active = true;
    api.authMethods().then(result => { if (active) setMethods(result); })
      .catch(() => { if (active) setError(t("Không thể tải phương thức đăng nhập. Hãy đóng và mở lại cài đặt.", "Could not load sign-in methods. Reopen settings and try again.")); });
    return () => { active = false; };
  }, [email]);

  async function changePassword() {
    if (submitting.current || sent) return;
    submitting.current = true;
    setSending(true);
    setError("");
    try {
      await api.forgotPassword(email);
      setMessage(t("Hãy kiểm tra Gmail để xác nhận thay đổi mật khẩu. Liên kết có hiệu lực trong 20 phút.", "Check Gmail to confirm the password change. The link is valid for 20 minutes."));
      setSent(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : t("Không thể gửi liên kết. Vui lòng thử lại.", "Could not send the link. Please try again."));
    } finally {
      setSending(false);
      submitting.current = false;
    }
  }

  return <section className="account-security" aria-labelledby="security-title">
    <h4 id="security-title">{t("Phương thức đăng nhập", "Sign-in methods")}</h4>
    {!methods && !error && <p role="status">{t("Đang tải...", "Loading...")}</p>}
    {methods?.google_linked && <div className="security-method"><strong>Google</strong><span>{t("Đã liên kết với Gmail của bạn", "Linked to your Gmail account")}</span></div>}
    {methods?.has_password ? <div className="security-method security-password">
      <div><strong>{t("Mật khẩu", "Password")}</strong><span>{t("Xác nhận qua Gmail khi thay đổi mật khẩu.", "Confirm password changes through Gmail.")}</span></div>
      <Button onClick={() => void changePassword()} disabled={sending || sent}>{sending ? t("Đang gửi...", "Sending...") : sent ? t("Đã gửi yêu cầu", "Request sent") : t("Đổi mật khẩu", "Change password")}</Button>
    </div> : methods && <p>{t("Tài khoản này đăng nhập bằng Google. Mật khẩu được quản lý trong tài khoản Google của bạn.", "This account signs in with Google. Its password is managed by Google.")}</p>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {message && <div className="form-success" role="status">{message}</div>}
  </section>;
}
