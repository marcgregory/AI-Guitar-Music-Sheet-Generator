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
  selected_stem?: StemSelection | null;
  processing_status?: ProcessingStatusValue | null;
  queue_position?: number | null;
  estimated_wait_time?: number | null;
  separated_audio_file_path?: string | null;
  midi_file_path?: string | null;
  tab_file_path?: string | null;
  youtube_url?: string | null;
  source_type?: "upload" | "youtube" | string | null;
  source_url?: string | null;
  normalized_source_id?: string | null;
  audio_hash?: string | null;
  duplicate_of_id?: number | null;
  is_deleted?: boolean | null;
  deleted_at?: string | null;
  original_audio_url?: string | null;
  original_audio_public_id?: string | null;
  separated_audio_url?: string | null;
  separated_audio_public_id?: string | null;
  midi_file_url?: string | null;
  midi_file_public_id?: string | null;
  tab_file_url?: string | null;
  tab_file_public_id?: string | null;
  duplicate_reused?: boolean | null;
  duplicate_message?: string | null;
  duration?: number | null;
  detected_tempo?: number | null;
  tempo_confidence?: number | null;
  detected_key?: string | null;
  key_confidence?: number | null;
  user_id: number;
  project_id?: number | null;
  is_processed: boolean;
  processing_error?: string | null;
  warning_message?: string | null;
  can_generate_score?: boolean | null;
  can_play_stem?: boolean | null;
  transcription_attempts?: number | null;
  notes_data?: string | null;
  chords_data?: string | null;
  tablature_data?: string | null;
  notation_data?: string | null;
  chord_chart_data?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface InstrumentTrack {
  id: number;
  transcription_id: number;
  instrument_type: string;
  display_name: string;
  stem_audio_path?: string | null;
  notes_json?: string | null;
  chords_json?: string | null;
  tab_json?: string | null;
  notation_json?: string | null;
  confidence_score?: number | null;
  processing_status: string;
  confidence_notes?: string | null;
  created_at: string;
  updated_at?: string | null;
}

export interface TranscriptionStatus {
  status: ProcessingStatusValue;
  transcription_id: number;
  progress?: number;
  error?: string;
  warning?: string | null;
  message?: string;
  selected_stem?: StemSelection | null;
  can_play_stem?: boolean;
  can_generate_score?: boolean;
  queue_position?: number | null;
  estimated_wait_time?: number | null;
  duplicate_reused?: boolean;
  duplicate_message?: string | null;
}

export type StemSelection = "vocals" | "drums" | "bass" | "other";
export type ProcessingStatusValue =
  | "pending"
  | "queued"
  | "processing"
  | "completed"
  | "completed_with_warning"
  | "failed"
  | "cancelled"
  | "deleted";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const getAuthHeader = (token: string | null) => {
  if (!token) throw new Error("User not authenticated");
  return {
    Authorization: `Bearer ${token}`,
  };
};

const transcriptionListCache = new Map<string, Transcription[]>();

const cloneTranscriptions = (transcriptions: Transcription[]): Transcription[] =>
  transcriptions.map((transcription) => ({ ...transcription }));

const rememberTranscriptions = (
  token: string,
  transcriptions: Transcription[],
): Transcription[] => {
  const snapshot = cloneTranscriptions(transcriptions);
  transcriptionListCache.set(token, snapshot);
  return cloneTranscriptions(snapshot);
};

const rememberTranscription = (token: string, transcription: Transcription): void => {
  const cached = transcriptionListCache.get(token) ?? [];
  const withoutDuplicate = cached.filter((item) => item.id !== transcription.id);
  transcriptionListCache.set(token, [{ ...transcription }, ...withoutDuplicate]);
};

const audioService = {
  getAudioFileUrl: (audioFilePath: string | null | undefined): string | null => {
    if (!audioFilePath) return null;
    const filename = audioFilePath.split(/[\\/]/).pop();
    return filename ? `${API_ORIGIN}/audio-files/${encodeURIComponent(filename)}` : null;
  },

  getCachedTranscriptions: (token: string | null): Transcription[] | null => {
    if (!token) return null;
    const cached = transcriptionListCache.get(token);
    return cached ? cloneTranscriptions(cached) : null;
  },

  /**
   * List the signed-in user's transcriptions.
   */
  listTranscriptions: async (token: string): Promise<Transcription[]> => {
    const response = await axios.get(`${API_BASE_URL}/audio/`, {
      headers: getAuthHeader(token),
    });

    return rememberTranscriptions(token, response.data);
  },

  /**
   * Upload an audio file (MP3 or WAV)
   */
  uploadAudioFile: async (
    file: File,
    token: string,
    selectedStem: StemSelection,
    projectId?: number,
    onUploadProgress?: (progress: number) => void,
  ): Promise<Transcription> => {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("selected_stem", selectedStem);
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

    rememberTranscription(token, response.data);
    return response.data;
  },

  /**
   * Extract audio from a YouTube URL
   */
  extractAudioFromYouTube: async (
    youtubeUrl: string,
    token: string,
    selectedStem: StemSelection,
    projectId?: number,
  ): Promise<Transcription> => {
    const response = await axios.post(
      `${API_BASE_URL}/audio/youtube`,
      {
        youtube_url: youtubeUrl,
        selected_stem: selectedStem,
        project_id: projectId,
      },
      {
        headers: {
          ...getAuthHeader(token),
          "Content-Type": "application/json",
        },
      },
    );

    rememberTranscription(token, response.data);
    return response.data;
  },

  /**
   * Get transcription status
   */
  getTranscriptionStatus: async (
    transcriptionId: number,
    token: string,
  ): Promise<TranscriptionStatus> => {
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
  ): Promise<Transcription> => {
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

  listInstrumentTracks: async (
    transcriptionId: number,
    token: string,
  ): Promise<InstrumentTrack[]> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/tracks`,
      {
        headers: getAuthHeader(token),
      },
    );

    return response.data;
  },

  getInstrumentTrackStem: async (
    transcriptionId: number,
    trackId: number,
    token: string,
  ): Promise<Blob> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/tracks/${trackId}/stem`,
      {
        headers: getAuthHeader(token),
        responseType: "blob",
      },
    );

    return response.data;
  },

  getInstrumentTrackPreview: async (
    transcriptionId: number,
    trackId: number,
    token: string,
  ): Promise<Blob> => {
    const response = await axios.get(
      `${API_BASE_URL}/audio/${transcriptionId}/tracks/${trackId}/preview`,
      {
        headers: getAuthHeader(token),
        responseType: "blob",
      },
    );

    return response.data;
  },

  deleteTranscription: async (
    transcriptionId: number,
    token: string,
  ): Promise<Transcription> => {
    const response = await axios.delete(
      `${API_BASE_URL}/transcriptions/${transcriptionId}`,
      {
        headers: getAuthHeader(token),
      },
    );

    const cached = transcriptionListCache.get(token);
    if (cached) {
      transcriptionListCache.set(
        token,
        cached.filter((item) => item.id !== transcriptionId),
      );
    }
    return response.data;
  },

  reprocessInstrumentTrack: async (
    transcriptionId: number,
    _trackId: number,
    token: string,
  ): Promise<InstrumentTrack> => {
    const response = await axios.post(
      `${API_BASE_URL}/transcriptions/${transcriptionId}/reprocess`,
      {},
      {
        headers: getAuthHeader(token),
      },
    );

    return response.data;
  },

  retryTranscription: async (
    transcriptionId: number,
    token: string,
    options?: {
      lower_threshold?: boolean;
      alternate_settings?: Record<string, unknown>;
      selected_stem?: StemSelection;
      sensitivity?: "high" | "normal" | string;
      reuse_separated_stem?: boolean;
    },
  ): Promise<TranscriptionStatus> => {
    const response = await axios.post(
      `${API_BASE_URL}/transcriptions/${transcriptionId}/retry`,
      {
        lower_threshold: options?.lower_threshold ?? true,
        alternate_settings: options?.alternate_settings,
        selected_stem: options?.selected_stem,
        sensitivity: options?.sensitivity,
        reuse_separated_stem: options?.reuse_separated_stem,
      },
      {
        headers: getAuthHeader(token),
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
    trackId?: number,
  ): Promise<Blob> => {
    try {
      const exportUrl = trackId === undefined
        ? `${API_BASE_URL}/audio/${transcriptionId}/${format}`
        : `${API_BASE_URL}/audio/${transcriptionId}/tracks/${trackId}/${format}`;
      const response = await axios.get(
        exportUrl,
        {
          headers: getAuthHeader(token),
          responseType: "blob",
        },
      );

      return response.data;
    } catch (err: unknown) {
      const data = isRecord(err) && isRecord(err.response) ? err.response.data : null;
      if (data instanceof Blob && data.type.includes("application/json")) {
        const errorJson = JSON.parse(await data.text()) as unknown;
        const detail = isRecord(errorJson) && typeof errorJson.detail === "string"
          ? errorJson.detail
          : `Failed to download ${format}`;
        throw new Error(detail, { cause: err });
      }
      throw err;
    }
  },
};

export default audioService;
