import { useEffect, useRef, useState } from "react";

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (options: { client_id: string; callback: (response: { credential: string }) => void }) => void;
          renderButton: (element: HTMLElement, options: Record<string, string>) => void;
        };
      };
    };
  }
}

export function GoogleSignIn({ disabled, onCredential, onUnavailable }: {
  disabled: boolean;
  onCredential: (credential: string) => void;
  onUnavailable: (message: string) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined;

  useEffect(() => {
    if (!clientId) return;
    const render = () => {
      if (!window.google || !container.current) return;
      container.current.replaceChildren();
      window.google.accounts.id.initialize({ client_id: clientId, callback: ({ credential }) => onCredential(credential) });
      window.google.accounts.id.renderButton(container.current, { type: "standard", theme: "outline", size: "large", width: "356" });
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
    script.onerror = () => onUnavailable("Google sign-in could not be loaded.");
    document.head.appendChild(script);
  }, [clientId, onCredential, onUnavailable]);

  if (!clientId) return <button type="button" className="google-button" disabled title="Set VITE_GOOGLE_CLIENT_ID to enable Google sign-in">G&nbsp;&nbsp; Continue with Google</button>;
  return <div className={`google-login-slot ${disabled || !ready ? "is-loading" : ""}`} ref={container} aria-busy={!ready} />;
}
