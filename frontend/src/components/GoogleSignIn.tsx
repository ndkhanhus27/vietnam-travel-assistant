import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: { client_id: string; callback: (response: { credential?: string }) => void }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string>) => void;
          disableAutoSelect: () => void;
        };
      };
    };
  }
}

export function isGoogleSignInOriginSupported(
  protocol: string,
  hostname: string,
): boolean {
  const localHosts = new Set(["localhost", "127.0.0.1", "[::1]"]);
  return protocol === "https:" || localHosts.has(hostname);
}

export function GoogleSignIn({ disabled, onCredential, onUnavailable }: {
  disabled: boolean;
  onCredential: (credential: string) => void;
  onUnavailable: (message: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;
  const originSupported = isGoogleSignInOriginSupported(
    window.location.protocol,
    window.location.hostname,
  );

  useEffect(() => {
    if (!clientId) {
      onUnavailable("Đăng nhập bằng Google chưa được cấu hình cho bản triển khai này.");
      return;
    }
    if (!originSupported) {
      onUnavailable("Đăng nhập bằng Google chỉ khả dụng trên tên miền HTTPS hoặc localhost.");
      return;
    }
    const render = () => {
      if (!window.google || !container.current) return;
      container.current.replaceChildren();
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: ({ credential }) => {
          if (!credential) {
            onUnavailable("Google không trả về thông tin đăng nhập. Vui lòng thử lại.");
            return;
          }
          onCredential(credential);
        },
      });
      const width = Math.max(240, Math.min(400, container.current.clientWidth));
      window.google.accounts.id.renderButton(container.current, { type: "standard", theme: "outline", size: "large", width: String(width), locale: "vi" });
      setReady(true);
    };
    const existing = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
    if (existing) {
      if (window.google) render();
      else existing.addEventListener("load", render, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.onload = render;
    script.onerror = () => onUnavailable("Không thể tải tính năng đăng nhập bằng Google.");
    document.head.appendChild(script);
  }, [clientId, onCredential, onUnavailable, originSupported]);

  if (!clientId || !originSupported) {
    const title = clientId
      ? "Đăng nhập bằng Google yêu cầu tên miền HTTPS"
      : "Chưa cấu hình đăng nhập bằng Google";
    return <button type="button" className="google-button" disabled title={title}>G&nbsp;&nbsp; Tiếp tục với Google</button>;
  }
  return <div className={`google-login-slot ${disabled || !ready ? "is-loading" : ""}`} ref={container} aria-busy={!ready} />;
}
