import { useAuth } from './AuthContext';
import { getAccessToken } from '../../services/authStorage';

export const useAuthApi = () => {
  const { token } = useAuth();

  const fetchWithAuth = async (url: string, options: RequestInit = {}) => {
    const headers = new Headers(options.headers);
    headers.set('Content-Type', 'application/json');

    const latestToken = getAccessToken() ?? token;
    if (latestToken) {
      headers.set('Authorization', `Bearer ${latestToken}`);
    } else {
      headers.delete('Authorization');
    }

    const response = await fetch(url, {
      ...options,
      headers,
    });

    return response;
  };

  return { fetchWithAuth };
};
