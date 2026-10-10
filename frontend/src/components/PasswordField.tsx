import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";

export function PasswordField({ label = "Mật khẩu", name = "password", autoComplete = "current-password", disabled = false, autoFocus = false }: { label?: string; name?: string; autoComplete?: string; disabled?: boolean; autoFocus?: boolean }) {
  const [visible, setVisible] = useState(false);
  const id = `auth-${name}`;
  return <div className="auth-field"><label htmlFor={id}>{label}</label><div className="auth-password-input"><input id={id} name={name} type={visible ? "text" : "password"} minLength={8} maxLength={128} autoComplete={autoComplete} placeholder={autoComplete === "new-password" ? "Ít nhất 8 ký tự" : "Nhập mật khẩu"} required disabled={disabled} autoFocus={autoFocus} /><button type="button" className="auth-eye" aria-label={visible ? `Ẩn ${label.toLowerCase()}` : `Hiện ${label.toLowerCase()}`} aria-pressed={visible} title={visible ? "Ẩn mật khẩu" : "Hiện mật khẩu"} onClick={() => setVisible(value => !value)} disabled={disabled}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div>;
}
