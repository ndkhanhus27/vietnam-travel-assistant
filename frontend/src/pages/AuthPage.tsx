import { FormEvent, useCallback, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { GoogleSignIn } from "../components/GoogleSignIn";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { authenticate } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const isLogin = mode === "login";
  const destination = (location.state as { from?: string } | null)?.from || "/";

  const handleError = useCallback((cause: unknown) => {
    if (!(cause instanceof ApiError)) return setError("Cannot connect to the server. Please try again.");
    if (cause.status === 401) return setError("Invalid email or password.");
    if (cause.status === 409) return setError("This email is already registered.");
    if (cause.status === 422) return setError(cause.message || "Please check the submitted details.");
    if (cause.status === 429) return setError(cause.retryAfter ? `Too many requests. Try again in ${cause.retryAfter} seconds.` : "Too many requests. Please try again later.");
    setError(cause.message);
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    const form = new FormData(event.currentTarget);
    const displayName = String(form.get("display_name") || "").trim();
    const email = String(form.get("email") || "").trim();
    const password = String(form.get("password") || "");
    if (!email || !password) return setError("Please complete all required fields.");
    setLoading(true);
    try {
      const result = isLogin
        ? await api.login({ email, password })
        : await api.register({ display_name: displayName || null, email, password });
      authenticate(result);
      navigate(destination, { replace: true });
    } catch (cause) {
      handleError(cause);
    } finally {
      setLoading(false);
    }
  }

  const googleCredential = useCallback(async (credential: string) => {
    setError("");
    setLoading(true);
    try {
      const result = await api.googleLogin(credential);
      authenticate(result);
      navigate(destination, { replace: true });
    } catch (cause) {
      handleError(cause);
    } finally {
      setLoading(false);
    }
  }, [authenticate, destination, handleError, navigate]);

  return (
    <main className="auth-page">
      <section className="auth-panel" aria-labelledby="auth-title">
        <div className="auth-brand">Vietnam Travel Advisor</div>
        <h1 id="auth-title">{isLogin ? "Welcome back" : "Create your account"}</h1>
        <p className="auth-subtitle">{isLogin ? "Log in to continue your saved travel conversations." : "Create an account to save your Vietnam travel advice."}</p>
        <form onSubmit={submit} className="auth-form">
          {!isLogin && <label><span>Display name</span><input name="display_name" autoComplete="name" disabled={loading} /></label>}
          <label><span>Email</span><input name="email" type="email" autoComplete="email" required disabled={loading} /></label>
          <label><span>Password</span><input name="password" type="password" minLength={8} maxLength={128} autoComplete={isLogin ? "current-password" : "new-password"} required disabled={loading} /></label>
          {error && <div className="form-error" role="alert">{error}</div>}
          <button className="primary-button auth-submit" disabled={loading}>{loading ? "Please wait..." : isLogin ? "Log in" : "Create account"}</button>
        </form>
        <div className="or-divider"><span>or</span></div>
        <GoogleSignIn disabled={loading} onCredential={googleCredential} onUnavailable={setError} />
        <p className="auth-switch">{isLogin ? "Don't have an account?" : "Already have an account?"} <Link to={isLogin ? "/register" : "/login"}>{isLogin ? "Sign up" : "Log in"}</Link></p>
      </section>
    </main>
  );
}
