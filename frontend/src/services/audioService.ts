import axios from "axios";

// API base URL
const API_BASE_URL =
  import.meta.env.VITE_API_URL || "http://localhost:8000/api/v1";
const API_ORIGIN = API_BASE_URL.replace(/\/api\/v1\/?$/, "");

export interface Transcription {
  id: number;
  title: string;
  audio_file_path?: string | null;
  preprocessed_audio_file_path?: string | null;
  separated_audio_file_path?: string | null;
  midi_file_path?: string | null;
  youtube_url?: string | null;
  duration?: number | null;
  detected_tempo?: number | null;
  tempo_confidence?: number | null;
  detected_key?: string | null;
  key_confidence?: number | null;
  user_id: number;
  project_id?: number | null;
  is_processed: boolean;
  processing_error?: string | null;
  created_at: string;
  updated_at?: string | null;
}

const getAuthHeader = (token: string | null) => {
  if (!token) throw new Error("User not authenticated");
  return {
    Authorization: `Bearer ${token}`,
  };
};

const audioService = {
  getAudioFileUrl: (audioFilePath: string | null | undefined): string | null => {
    if (!audioFilePath) return null;
    const filename = audioFilePath.split(/[\\/]/).pop();
    return filename ? `${API_ORIGIN}/audio-files/${encodeURIComponent(filename)}` : null;
  },

  /**
   * List the signed-in user's transcriptions.
   */
  listTranscriptions: async (token: string): Promise<Transcription[]> => {
    const response = await axios.get(`${API_BASE_URL}/audio/`, {
      headers: getAuthHeader(token),
    });

    return response.data;
  },

  /**
   * Upload an audio file (MP3 or WAV)
   */
  uploadAudioFile: async (
    file: File,
    token: string,
    projectId?: number,
    onUploadProgress?: (progress: number) => void,
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
        onUploadProgress: (event) => {
          if (!event.total) return;
          onUploadProgress?.(Math.round((event.loaded * 100) / event.total));
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

  /**
   * Get completed transcription data
   */
  getTranscriptionResult: async (
    transcriptionId: number,
    token: string,
  ): Promise<any> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/result`,
      {
        headers: getAuthHeader(token),
      },
    );

    return response.data;
  },

  getSourceAudio: async (
    transcriptionId: number,
    token: string,
  ): Promise<Blob> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/source`,
      {
        headers: getAuthHeader(token),
        responseType: "blob",
      },
    );

    return response.data;
  },

  /**
   * Download a generated transcription export.
   */
  downloadExport: async (
    transcriptionId: number,
    format: "midi" | "musicxml" | "tab",
    token: string,
  ): Promise<Blob> => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/audio/${transcriptionId}/${format}`,
        {
          headers: getAuthHeader(token),
          responseType: "blob",
        },
      );

      return response.data;
    } catch (err: any) {
      const data = err.response?.data;
      if (data instanceof Blob && data.type.includes("application/json")) {
        const errorJson = JSON.parse(await data.text());
        throw new Error(errorJson.detail || `Failed to download ${format}`);
      }
      throw err;
    }
  },
};

export default audioService;
