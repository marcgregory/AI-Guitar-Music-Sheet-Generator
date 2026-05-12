import { useAuth } from './AuthContext';

export const useAuthApi = () => {
  const { token } = useAuth();

  const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
    const headers: HeadersInit = {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    };

    if (token) {
      headers.Authorization = `Bearer ${token}`;
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    return response;
  };

  return { fetchWithAuth };
};