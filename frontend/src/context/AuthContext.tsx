import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { api } from "../api/client";
import type { LoginResponse } from "../types/api";

interface AuthUser {
  userId: string;
  username: string;
  displayName: string;
  isSuperuser: boolean;
  groupIds: string[];
}

interface AuthContextValue {
  user: AuthUser | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function loadStoredUser(): AuthUser | null {
  const raw = localStorage.getItem("sre_ai_user");
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(loadStoredUser());

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<LoginResponse>("/auth/login", { username, password });
    const authUser: AuthUser = {
      userId: res.user_id,
      username: res.username,
      displayName: res.display_name,
      isSuperuser: res.is_superuser,
      groupIds: res.group_ids,
    };
    localStorage.setItem("sre_ai_token", res.access_token);
    localStorage.setItem("sre_ai_user", JSON.stringify(authUser));
    setUser(authUser);
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem("sre_ai_token");
    localStorage.removeItem("sre_ai_user");
    setUser(null);
  }, []);

  const value = useMemo(() => ({ user, login, logout }), [user, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
