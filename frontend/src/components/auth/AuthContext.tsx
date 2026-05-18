import React, { createContext, useContext, useState } from 'react';
import {
  clearAuthStorage,
  getAccessToken,
  getStoredUser,
  isJwtExpired,
  setAuthStorage,
  type StoredUser,
} from '../../services/authStorage';
import { clearAuthHeader } from '../../services/apiClient';

interface AuthContextType {
  token: string | null;
  user: StoredUser | null;
  login: (token: string, user: StoredUser, refreshToken?: string | null) => void;
  logout: () => void;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

interface AuthProviderProps {
  children: React.ReactNode;
}

const readStoredAuth = (): {
  token: string | null;
  user: StoredUser | null;
} => {
  const storedToken = getAccessToken();
  const storedUser = getStoredUser();

  if (!storedToken || !storedUser || isJwtExpired(storedToken)) {
    clearAuthStorage();
    return { token: null, user: null };
  }

  return { token: storedToken, user: storedUser };
};

export const AuthProvider = ({ children }: AuthProviderProps) => {
  const [storedAuth] = useState(readStoredAuth);
  const [token, setToken] = useState<string | null>(storedAuth.token);
  const [user, setUser] = useState<StoredUser | null>(storedAuth.user);

  const login = (token: string, user: StoredUser, refreshToken?: string | null) => {
    if (!token || token === 'undefined' || token === 'null') {
      throw new Error('Login response did not include an access token');
    }
    setToken(token);
    setUser(user);
    setAuthStorage(token, user, refreshToken);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    clearAuthStorage();
    clearAuthHeader();
  };

  const isAuthenticated = !!token && !isJwtExpired(token);

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
};
