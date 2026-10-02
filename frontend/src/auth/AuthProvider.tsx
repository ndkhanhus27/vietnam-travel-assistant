import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, sessionStore } from "../api/client";
import type { AuthResponse, UserResponse } from "../api/types";

type AuthContextValue = {
  user: UserResponse | null;
  bootstrapping: boolean;
  authenticate: (result: AuthResponse) => void;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserResponse | null>(null);
  const [bootstrapping, setBootstrapping] = useState(true);

  useEffect(() => {
    let active = true;
    const synchronize = () => {
      const session = sessionStore.get();
      if (!session) setUser(null);
      else setUser(session.user);
    };
    window.addEventListener(sessionStore.event, synchronize);
    (async () => {
      if (!sessionStore.get()) {
        if (active) setBootstrapping(false);
        return;
      }
      try {
        const currentUser = await api.me();
        if (active) setUser(currentUser);
      } catch {
        sessionStore.clear();
        if (active) setUser(null);
      } finally {
        if (active) setBootstrapping(false);
      }
    })();
    return () => {
      active = false;
      window.removeEventListener(sessionStore.event, synchronize);
    };
  }, []);

  const value = useMemo<AuthContextValue>(() => ({
    user,
    bootstrapping,
    authenticate: (result) => {
      sessionStore.set(result);
      setUser(result.user);
    },
    logout: async () => {
      await api.logout();
      setUser(null);
    },
  }), [bootstrapping, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
