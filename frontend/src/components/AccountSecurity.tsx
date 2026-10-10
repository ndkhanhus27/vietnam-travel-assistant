import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";

export function AccountSecurity({ email }: { email: string }) {
  const [methods, setMethods] = useState<{ has_password: boolean; google_linked: boolean } | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [sending, setSending] = useState(false);
  const [sent, setSent] = useState(false);
  const submitting = useRef(false);

  useEffect(() => {
    let active = true;
    api.authMethods().then(result => { if (active) setMethods(result); })
      .catch(() => { if (active) setError("Không thể tải phương thức đăng nhập. Hãy đóng và mở lại cài đặt."); });
    return () => { active = false; };
  }, [email]);

  async function changePassword() {
    if (submitting.current || sent) return;
    submitting.current = true;
    setSending(true);
    setError("");
    try {
      await api.forgotPassword(email);
      setMessage("Hãy kiểm tra Gmail để xác nhận thay đổi mật khẩu. Liên kết có hiệu lực trong 20 phút.");
      setSent(true);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Không thể gửi liên kết. Vui lòng thử lại.");
    } finally {
      setSending(false);
      submitting.current = false;
    }
  }

  return <section className="account-security" aria-labelledby="security-title">
    <h4 id="security-title">Phương thức đăng nhập</h4>
    {!methods && !error && <p role="status">Đang tải...</p>}
    {methods?.google_linked && <div className="security-method"><strong>Google</strong><span>Đã liên kết với Gmail của bạn</span></div>}
    {methods?.has_password ? <div className="security-method security-password">
      <div><strong>Mật khẩu</strong><span>Xác nhận qua Gmail khi thay đổi mật khẩu.</span></div>
      <button className="secondary-button" onClick={() => void changePassword()} disabled={sending || sent}>{sending ? "Đang gửi..." : sent ? "Đã gửi yêu cầu" : "Đổi mật khẩu"}</button>
    </div> : methods && <p>Tài khoản này đăng nhập bằng Google. Mật khẩu được quản lý trong tài khoản Google của bạn.</p>}
    {error && <div className="form-error" role="alert">{error}</div>}
    {message && <div className="form-success" role="status">{message}</div>}
  </section>;
}
