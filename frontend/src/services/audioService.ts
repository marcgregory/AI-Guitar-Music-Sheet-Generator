import axios from 'axios';
import { useAuth } from '../components/auth/AuthContext';

// API base URL
const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000/api/v1';

const audioService = {
  /**
   * Upload an audio file (MP3 or WAV)
   */
  uploadAudioFile: async (file: File, projectId?: number): Promise<any> => {
    const { user } = useAuth();
    if (!user) throw new Error('User not authenticated');

    const formData = new FormData();
    formData.append('file', file);
    if (projectId !== undefined) {
      formData.append('project_id', projectId.toString());
    }

    const response = await axios.post(`${API_BASE_URL}/audio/upload`, formData, {
      headers: {
        'Authorization': `Bearer ${user.token}`,
        'Content-Type': 'multipart/form-data',
      },
    });

    return response.data;
  },

  /**
   * Extract audio from a YouTube URL
   */
  extractAudioFromYouTube: async (youtubeUrl: string, projectId?: number): Promise<any> => {
    const { user } = useAuth();
    if (!user) throw new Error('User not authenticated');

    const response = await axios.post(`${API_BASE_URL}/audio/youtube`, {
      youtube_url: youtubeUrl,
      project_id: projectId
    }, {
      headers: {
        'Authorization': `Bearer ${user.token}`,
        'Content-Type': 'application/json',
      },
    });

    return response.data;
  },

  /**
   * Get transcription status
   */
  getTranscriptionStatus: async (transcriptionId: number): Promise<any> => {
    const { user } = useAuth();
    if (!user) throw new Error('User not authenticated');

    const response = await axios.get(`${API_BASE_URL}/audio/${transcriptionId}/status`, {
      headers: {
        'Authorization': `Bearer ${user.token}`,
      },
    });

    return response.data;
  }
};

export default audioService;