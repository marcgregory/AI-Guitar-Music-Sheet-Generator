import axios, { AxiosError, type AxiosRequestConfig } from "axios";
import { clearAuthStorage, getAccessToken, getRefreshToken, getStoredUser, setAuthStorage } from "./authStorage";

export const API_BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
export const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

interface RefreshResponse {
  access_token: string;
  refresh_token?: string | null;
}

interface RetriableRequest extends AxiosRequestConfig {
  _retry?: boolean;
}

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
});

apiClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  config.headers = config.headers ?? {};

  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  } else {
    delete config.headers.Authorization;
  }

  return config;
});

apiClient.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const originalRequest = error.config as RetriableRequest | undefined;
    const refreshToken = getRefreshToken();

    if (error.response?.status === 401 && refreshToken && originalRequest && !originalRequest._retry) {
      originalRequest._retry = true;
      try {
        const response = await axios.post<RefreshResponse>(`${API_BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        });
        const user = getStoredUser();
        if (!user) {
          throw new Error("Cannot refresh a session without stored user state");
        }
        setAuthStorage(
          response.data.access_token,
          user,
          response.data.refresh_token ?? refreshToken,
        );
        return apiClient(originalRequest);
      } catch {
        clearAuthStorage();
      }
    }

    if (error.response?.status === 401) {
      clearAuthStorage();
      if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
        window.location.assign("/login");
      }
    }

    return Promise.reject(error);
  },
);

export const clearAuthHeader = (): void => {
  delete apiClient.defaults.headers.common.Authorization;
};

export default apiClient;
