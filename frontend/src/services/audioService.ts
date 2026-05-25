import apiClient, { API_ORIGIN } from "./apiClient";
const PUBLIC_AUDIO_PATHS = ["/demo/", "/audio-files/"];

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
  source_type?: "upload" | "youtube" | "demo" | string | null;
  source_url?: string | null;
  normalized_source_id?: string | null;
  audio_hash?: string | null;
  duplicate_of_id?: number | null;
  is_demo?: boolean | null;
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
  lyrics_generation_status?: LyricsGenerationStatusValue | null;
  tab_generation_status?: GenerationStatusValue | null;
  rhythm_generation_status?: GenerationStatusValue | null;
  modal_dispatch_status?: string | null;
  modal_job_type?: string | null;
  modal_retry_at?: string | null;
  instrument_type?: string | null;
  output_mode?: string | null;
  can_generate_tab?: boolean | null;
  can_generate_score?: boolean | null;
  can_generate_rhythm?: boolean | null;
  can_play_stem?: boolean | null;
  available_exports?: ExportFormat[] | null;
  track_count?: number | null;
  tuning?: string | null;
  import_type?: string | null;
  transcription_attempts?: number | null;
  notes_data?: string | null;
  chords_data?: string | null;
  tablature_data?: string | null;
  notation_data?: string | null;
  chord_chart_data?: string | null;
  lyrics_data?: string | null;
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
  separated_audio_url?: string | null;
  available_exports?: ExportFormat[] | null;
  is_demo?: boolean;
  queue_position?: number | null;
  estimated_wait_time?: number | null;
  duplicate_reused?: boolean;
  duplicate_message?: string | null;
  lyrics_generation_status?: LyricsGenerationStatusValue | null;
  tab_generation_status?: GenerationStatusValue | null;
  rhythm_generation_status?: GenerationStatusValue | null;
  modal_dispatch_status?: string | null;
  modal_job_type?: string | null;
  modal_retry_at?: string | null;
  lyrics_data?: string | null;
}

export type StemSelection = "vocals" | "drums" | "bass" | "other";
export type LyricsLanguage = "auto" | "en" | "tl" | "ceb" | "es" | "ja" | "ko";
export type ExportFormat = "midi" | "musicxml" | "tab";
export type LyricsGenerationStatusValue =
  | "pending"
  | "processing"
  | "completed"
  | "completed_with_warning"
  | "failed";
export type GenerationStatusValue =
  | "idle"
  | "queued"
  | "processing"
  | "completed"
  | "failed";
export type ProcessingStatusValue =
  | "pending"
  | "queued"
  | "processing"
  | "stem_ready"
  | "completed"
  | "completed_with_warning"
  | "failed"
  | "cancelled"
  | "deleted";

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const transcriptionListCache = new Map<string, Transcription[]>();
const TRANSCRIPTION_LIST_TIMEOUT_MS = 15000;

const cloneTranscriptions = (
  transcriptions: Transcription[],
): Transcription[] =>
  transcriptions.map((transcription) => ({ ...transcription }));

const rememberTranscriptions = (
  token: string,
  transcriptions: Transcription[],
): Transcription[] => {
  const snapshot = cloneTranscriptions(transcriptions);
  transcriptionListCache.set(token, snapshot);
  return cloneTranscriptions(snapshot);
};

const rememberTranscription = (
  token: string,
  transcription: Transcription,
): void => {
  const cached = transcriptionListCache.get(token) ?? [];
  const withoutDuplicate = cached.filter(
    (item) => item.id !== transcription.id,
  );
  transcriptionListCache.set(token, [
    { ...transcription },
    ...withoutDuplicate,
  ]);
};

const audioService = {
  resolvePlayableAudioUrl: (
    audioUrl: string | null | undefined,
  ): string | null => {
    if (!audioUrl) return null;
    const trimmed = audioUrl.trim();
    if (!trimmed) return null;
    if (/^https?:\/\//i.test(trimmed) || trimmed.startsWith("blob:"))
      return trimmed;
    if (PUBLIC_AUDIO_PATHS.some((prefix) => trimmed.startsWith(prefix))) {
      return `${API_ORIGIN}${trimmed}`;
    }
    if (
      /^[a-zA-Z]:[\\/]/.test(trimmed) ||
      trimmed.includes("\\") ||
      trimmed.startsWith("/")
    ) {
      return null;
    }
    return null;
  },

  getAudioFileUrl: (
    audioFilePath: string | null | undefined,
  ): string | null => {
    if (!audioFilePath) return null;
    const publicAudioUrl = audioService.resolvePlayableAudioUrl(audioFilePath);
    if (publicAudioUrl) return publicAudioUrl;
    const filename = audioFilePath.split(/[\\/]/).pop();
    return filename
      ? `${API_ORIGIN}/audio-files/${encodeURIComponent(filename)}`
      : null;
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
    const response = await apiClient.get("/audio/", {
      timeout: TRANSCRIPTION_LIST_TIMEOUT_MS,
    });

    return rememberTranscriptions(token, response.data);
  },

  getDemoTranscription: async (token: string): Promise<Transcription> => {
    const response = await apiClient.get("/audio/demo");

    rememberTranscription(token, response.data);
    return response.data;
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

    const response = await apiClient.post("/audio/upload", formData, {
      onUploadProgress: (event) => {
        if (!event.total) return;
        onUploadProgress?.(Math.round((event.loaded * 100) / event.total));
      },
    });

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
    const response = await apiClient.post("/audio/youtube", {
      youtube_url: youtubeUrl,
      selected_stem: selectedStem,
      project_id: projectId,
    });

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
    void token;
    const response = await apiClient.get(`/audio/${transcriptionId}/status`);

    return response.data;
  },

  /**
   * Get completed transcription data
   */
  getTranscriptionResult: async (
    transcriptionId: number,
    token: string,
  ): Promise<Transcription> => {
    void token;
    const response = await apiClient.get(`/audio/${transcriptionId}/result`);

    return response.data;
  },

  getSourceAudio: async (
    transcriptionId: number,
    token: string,
  ): Promise<Blob> => {
    void token;
    const response = await apiClient.get(`/audio/${transcriptionId}/source`, {
      responseType: "blob",
    });

    return response.data;
  },

  listInstrumentTracks: async (
    transcriptionId: number,
    token: string,
  ): Promise<InstrumentTrack[]> => {
    void token;
    const response = await apiClient.get(`/audio/${transcriptionId}/tracks`);

    return response.data;
  },

  getInstrumentTrackStem: async (
    transcriptionId: number,
    trackId: number,
    token: string,
  ): Promise<Blob> => {
    void token;
    const response = await apiClient.get(
      `/audio/${transcriptionId}/tracks/${trackId}/stem`,
      {
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
    void token;
    const response = await apiClient.get(
      `/audio/${transcriptionId}/tracks/${trackId}/preview`,
      {
        responseType: "blob",
      },
    );

    return response.data;
  },

  deleteTranscription: async (
    transcriptionId: number,
    token: string,
  ): Promise<Transcription> => {
    const response = await apiClient.delete(
      `/transcriptions/${transcriptionId}`,
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
    trackId: number,
    token: string,
  ): Promise<InstrumentTrack> => {
    void token;
    const response = await apiClient.post(
      `/audio/${transcriptionId}/tracks/${trackId}/reprocess`,
      {},
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
    void token;
    const response = await apiClient.post(
      `/transcriptions/${transcriptionId}/retry`,
      {
        lower_threshold: options?.lower_threshold ?? true,
        alternate_settings: options?.alternate_settings,
        selected_stem: options?.selected_stem,
        sensitivity: options?.sensitivity,
        reuse_separated_stem: options?.reuse_separated_stem,
      },
    );

    return response.data;
  },

  generateTab: async (
    transcriptionId: number,
    token: string,
    options?: {
      sensitivity?: "high" | "normal" | string;
    },
  ): Promise<TranscriptionStatus> => {
    void token;
    const response = await apiClient.post(
      `/audio/${transcriptionId}/generate-tabs`,
      {
        sensitivity: options?.sensitivity,
      },
    );

    return response.data;
  },

  generateLyrics: async (
    transcriptionId: number,
    token: string,
    options?: {
      language?: LyricsLanguage;
    },
  ): Promise<TranscriptionStatus> => {
    void token;
    const response = await apiClient.post(
      `/audio/${transcriptionId}/generate-lyrics`,
      {
        language: options?.language ?? "auto",
      },
    );

    return response.data;
  },

  /**
   * Download a generated transcription export.
   */
  downloadExport: async (
    transcriptionId: number,
    format: ExportFormat,
    token: string,
    trackId?: number,
  ): Promise<Blob> => {
    try {
      const exportUrl =
        trackId === undefined
          ? `/audio/${transcriptionId}/${format}`
          : `/audio/${transcriptionId}/tracks/${trackId}/${format}`;
      void token;
      const response = await apiClient.get(exportUrl, {
        responseType: "blob",
      });

      return response.data;
    } catch (err: unknown) {
      const data =
        isRecord(err) && isRecord(err.response) ? err.response.data : null;
      if (data instanceof Blob && data.type.includes("application/json")) {
        const errorJson = JSON.parse(await data.text()) as unknown;
        const detail =
          isRecord(errorJson) && typeof errorJson.detail === "string"
            ? errorJson.detail
            : `Failed to download ${format}`;
        throw new Error(detail, { cause: err });
      }
      throw err;
    }
  },
};

export default audioService;
