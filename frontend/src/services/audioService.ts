import axios from "axios";

// API base URL
const API_BASE_URL =
  import.meta.env.VITE_API_URL || "http://localhost:8003/api/v1";

const getAuthHeader = (token: string | null) => {
  if (!token) throw new Error("User not authenticated");
  return {
    Authorization: `Bearer ${token}`,
  };
};

const audioService = {
  /**
   * Upload an audio file (MP3 or WAV)
   */
  uploadAudioFile: async (
    file: File,
    token: string,
    projectId?: number,
  ): Promise<any> => {
    const formData = new FormData();
    formData.append("file", file);
    if (projectId !== undefined) {
      formData.append("project_id", projectId.toString());
    }

    const response = await axios.post(
      `${API_BASE_URL}/audio/upload`,
      formData,
      {
        headers: {
          ...getAuthHeader(token),
          "Content-Type": "multipart/form-data",
        },
      },
    );

    return response.data;
  },

  /**
   * Extract audio from a YouTube URL
   */
  extractAudioFromYouTube: async (
    youtubeUrl: string,
    token: string,
    projectId?: number,
  ): Promise<any> => {
    const response = await axios.post(
      `${API_BASE_URL}/audio/youtube`,
      {
        youtube_url: youtubeUrl,
        project_id: projectId,
      },
      {
        headers: {
          ...getAuthHeader(token),
          "Content-Type": "application/json",
        },
      },
    );

    return response.data;
  },

  /**
   * Get transcription status
   */
  getTranscriptionStatus: async (
    transcriptionId: number,
    token: string,
  ): Promise<any> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/status`,
      {
        headers: getAuthHeader(token),
      },
    );

    return response.data;
  },
};

export default audioService;
