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
    let renderedWidth = -1;
    const render = () => {
      if (!window.google || !container.current) return;
      const width = Math.floor(Math.min(400, container.current.clientWidth));
      if (width <= 0 || width === renderedWidth) return;
      renderedWidth = width;
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
      window.google.accounts.id.renderButton(container.current, {
        type: width < 200 ? "icon" : "standard", theme: "outline", size: "large",
        ...(width >= 200 ? { width: String(width) } : {}), locale: "vi",
      });
      setReady(true);
    };
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(render);
    if (container.current) observer?.observe(container.current);
    const failed = () => onUnavailable("Không thể tải tính năng đăng nhập bằng Google.");
    const existing = document.querySelector<HTMLScriptElement>('script[src="https://accounts.google.com/gsi/client"]');
    if (existing) {
      if (window.google) render();
      else existing.addEventListener("load", render, { once: true });
      existing.addEventListener("error", failed, { once: true });
      return () => { observer?.disconnect(); existing.removeEventListener("load", render); existing.removeEventListener("error", failed); };
    }
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.defer = true;
    script.addEventListener("load", render, { once: true });
    script.addEventListener("error", failed, { once: true });
    document.head.appendChild(script);
    return () => { observer?.disconnect(); script.removeEventListener("load", render); script.removeEventListener("error", failed); };
  }, [clientId, onCredential, onUnavailable, originSupported]);

  if (!clientId || !originSupported) {
    const title = clientId
      ? "Đăng nhập bằng Google yêu cầu tên miền HTTPS"
      : "Chưa cấu hình đăng nhập bằng Google";
    return <button type="button" className="google-button" disabled title={title}>G&nbsp;&nbsp; Tiếp tục với Google</button>;
  }
  return <div className={`google-login-slot ${disabled || !ready ? "is-loading" : ""}`} ref={container} aria-busy={!ready} />;
}
