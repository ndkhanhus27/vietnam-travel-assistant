import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useLocale } from "../locale/LocaleProvider";

export function PasswordField({ label, name = "password", autoComplete = "current-password", disabled = false, autoFocus = false }: { label?: string; name?: string; autoComplete?: string; disabled?: boolean; autoFocus?: boolean }) {
  const { language, t } = useLocale();
  const [visible, setVisible] = useState(false);
  const id = `auth-${name}`;
  const fieldLabel = label || t("Mật khẩu", "Password");
  const action = visible
    ? (language === "vi" ? `Ẩn ${fieldLabel.toLowerCase()}` : `Hide ${fieldLabel.toLowerCase()}`)
    : (language === "vi" ? `Hiện ${fieldLabel.toLowerCase()}` : `Show ${fieldLabel.toLowerCase()}`);
  return <div className="auth-field"><label htmlFor={id}>{fieldLabel}</label><div className="auth-password-input"><input id={id} name={name} type={visible ? "text" : "password"} minLength={8} maxLength={128} autoComplete={autoComplete} placeholder={autoComplete === "new-password" ? t("Ít nhất 8 ký tự", "At least 8 characters") : t("Nhập mật khẩu", "Enter password")} required disabled={disabled} autoFocus={autoFocus} /><button type="button" className="auth-eye" aria-label={action} aria-pressed={visible} title={action} onClick={() => setVisible(value => !value)} disabled={disabled}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div></div>;
}
