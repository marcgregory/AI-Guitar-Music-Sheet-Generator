const ACCESS_TOKEN_KEY = "access_token";
const REFRESH_TOKEN_KEY = "refresh_token";
const LEGACY_TOKEN_KEY = "token";
const USER_KEY = "user";

export interface StoredUser {
  username: string;
  email: string;
}

const isBrowser = () => typeof window !== "undefined";

const readStorage = (key: string): string | null => {
  if (!isBrowser()) return null;
  return localStorage.getItem(key) ?? sessionStorage.getItem(key);
};

export const getAccessToken = (): string | null => {
  const token = readStorage(ACCESS_TOKEN_KEY);
  if (token && token !== "undefined" && token !== "null") return token;

  const legacyToken = readStorage(LEGACY_TOKEN_KEY);
  if (legacyToken && legacyToken !== "undefined" && legacyToken !== "null") {
    localStorage.setItem(ACCESS_TOKEN_KEY, legacyToken);
    localStorage.removeItem(LEGACY_TOKEN_KEY);
    sessionStorage.removeItem(LEGACY_TOKEN_KEY);
    return legacyToken;
  }

  return null;
};

export const getRefreshToken = (): string | null => {
  const token = readStorage(REFRESH_TOKEN_KEY);
  return token && token !== "undefined" && token !== "null" ? token : null;
};

export const getStoredUser = (): StoredUser | null => {
  const storedUser = readStorage(USER_KEY);
  if (!storedUser) return null;

  try {
    return JSON.parse(storedUser) as StoredUser;
  } catch {
    clearAuthStorage();
    return null;
  }
};

export const setAuthStorage = (
  accessToken: string,
  user: StoredUser,
  refreshToken?: string | null,
): void => {
  localStorage.setItem(ACCESS_TOKEN_KEY, accessToken);
  localStorage.setItem(USER_KEY, JSON.stringify(user));

  if (refreshToken) {
    localStorage.setItem(REFRESH_TOKEN_KEY, refreshToken);
  } else {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
    sessionStorage.removeItem(REFRESH_TOKEN_KEY);
  }

  localStorage.removeItem(LEGACY_TOKEN_KEY);
  sessionStorage.removeItem(LEGACY_TOKEN_KEY);
};

export const clearAuthStorage = (): void => {
  for (const storage of [localStorage, sessionStorage]) {
    storage.removeItem(ACCESS_TOKEN_KEY);
    storage.removeItem(REFRESH_TOKEN_KEY);
    storage.removeItem(LEGACY_TOKEN_KEY);
    storage.removeItem(USER_KEY);
  }
};

export const isJwtExpired = (token: string | null): boolean => {
  if (!token) return true;

  try {
    const [, payload] = token.split(".");
    if (!payload) return true;
    const normalized = payload.replace(/-/g, "+").replace(/_/g, "/");
    const decoded = JSON.parse(window.atob(normalized)) as { exp?: number };
    if (!decoded.exp) return false;
    return decoded.exp * 1000 <= Date.now();
  } catch {
    return true;
  }
};
