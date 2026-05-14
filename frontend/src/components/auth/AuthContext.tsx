import React, { createContext, useContext, useState } from 'react';

interface AuthContextType {
  token: string | null;
  user: { username: string; email: string } | null;
  login: (token: string, user: { username: string; email: string }) => void;
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
  user: { username: string; email: string } | null;
} => {
  const storedToken = localStorage.getItem('token');
  const storedUser = localStorage.getItem('user');

  if (!storedToken || !storedUser) {
    return { token: null, user: null };
  }

  try {
    return {
      token: storedToken,
      user: JSON.parse(storedUser),
    };
  } catch {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
    return { token: null, user: null };
  }
};

export const AuthProvider = ({ children }: AuthProviderProps) => {
  const [storedAuth] = useState(readStoredAuth);
  const [token, setToken] = useState<string | null>(storedAuth.token);
  const [user, setUser] = useState<{ username: string; email: string } | null>(storedAuth.user);

  const login = (token: string, user: { username: string; email: string }) => {
    setToken(token);
    setUser(user);
    localStorage.setItem('token', token);
    localStorage.setItem('user', JSON.stringify(user));
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  };

  const isAuthenticated = !!token;

  return (
    <AuthContext.Provider value={{ token, user, login, logout, isAuthenticated }}>
      {children}
    </AuthContext.Provider>
  );
};
