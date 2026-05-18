import type { InstrumentTrack, Transcription } from "../services/audioService";

export type CapabilityKey = "tabs" | "score" | "rhythm" | "playback";

export type TranscriptionMetadata = {
  stemLabel: string;
  instrumentLabel: string;
  sourceBadge: string;
  sourceLabel: string;
  outputLabel: string;
  playbackLabel: string;
  tuningLabel: string | null;
  importType: string | null;
  trackCount: number;
  isImport: boolean;
  isMultiTrack: boolean;
  tone: "guitar" | "bass" | "drums" | "vocals" | "midi" | "gp" | "tab";
  outputBadges: string[];
  capabilities: Record<CapabilityKey, boolean>;
  description: string;
  durationSeconds: number;
};

const parseJsonField = (value: unknown): unknown => {
  if (!value) return null;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const hasText = (value: unknown): boolean =>
  typeof value === "string" && value.trim().length > 0;

export const hasNoteEvents = (notesData: unknown): boolean => {
  const parsed = parseJsonField(notesData);
  if (Array.isArray(parsed)) return parsed.length > 0;
  if (!isRecord(parsed)) return false;
  return (
    (Array.isArray(parsed.notes) && parsed.notes.length > 0) ||
    (Array.isArray(parsed.pitch_info) && parsed.pitch_info.length > 0)
  );
};

export const hasDrumHits = (notesData: unknown): boolean => {
  const parsed = parseJsonField(notesData);
  return Boolean(isRecord(parsed) && Array.isArray(parsed.drum_hits) && parsed.drum_hits.length > 0);
};

const hasTabData = (tablatureData: unknown): boolean => {
  const parsed = parseJsonField(tablatureData);
  if (!parsed) return false;
  if (typeof parsed === "string") return parsed.trim().length > 0;
  if (!isRecord(parsed)) return false;
  return (
    (Array.isArray(parsed.tablature) && parsed.tablature.length > 0) ||
    (Array.isArray(parsed.tracks) && parsed.tracks.length > 0)
  );
};

const durationFromTimedData = (notesData: unknown, tablatureData: unknown): number => {
  const candidates: number[] = [];
  const collect = (items: unknown[]) => {
    items.forEach((item) => {
      if (!isRecord(item)) return;
      const start = Number(item.startTime ?? item.onset ?? 0);
      const end = Number(item.offset ?? start + Number(item.duration ?? 0));
      if (Number.isFinite(end) && end > 0) candidates.push(end);
    });
  };

  const parsedNotes = parseJsonField(notesData);
  if (Array.isArray(parsedNotes)) collect(parsedNotes);
  if (isRecord(parsedNotes)) {
    if (Array.isArray(parsedNotes.notes)) collect(parsedNotes.notes);
    if (Array.isArray(parsedNotes.pitch_info)) collect(parsedNotes.pitch_info);
    if (Array.isArray(parsedNotes.drum_hits)) collect(parsedNotes.drum_hits);
    if (isRecord(parsedNotes.rhythm_analysis)) {
      const totalDuration = Number(parsedNotes.rhythm_analysis.total_duration);
      if (Number.isFinite(totalDuration) && totalDuration > 0) candidates.push(totalDuration);
    }
  }

  const parsedTab = parseJsonField(tablatureData);
  if (isRecord(parsedTab) && Array.isArray(parsedTab.tablature)) collect(parsedTab.tablature);

  return Math.ceil(Math.max(0, ...candidates));
};

const stemLabelOf = (stem?: string | null): string => {
  switch ((stem || "other").toLowerCase()) {
    case "bass":
      return "Bass";
    case "drums":
      return "Drums";
    case "vocals":
      return "Vocals";
    case "other":
    default:
      return "Guitar/Accompaniment";
  }
};

const instrumentLabelOf = (stem?: string | null, explicitInstrument?: string | null): string => {
  if (explicitInstrument) return explicitInstrument;
  switch ((stem || "other").toLowerCase()) {
    case "bass":
      return "Bass Guitar";
    case "drums":
      return "Percussion";
    case "vocals":
      return "Vocal Stem";
    case "other":
    default:
      return "Guitar/Accompaniment";
  }
};

const normalizeImportType = (sourceType?: string | null, importType?: string | null): string | null => {
  const value = (importType || sourceType || "").toLowerCase();
  if (value.includes("gp") || value.includes("guitar_pro")) return "gp5";
  if (value.includes("midi")) return "midi";
  if (value.includes("tab")) return "tab";
  return null;
};

export const buildTranscriptionMetadata = (
  transcription: Transcription,
  tracks: InstrumentTrack[] = [],
): TranscriptionMetadata => {
  const importType = normalizeImportType(transcription.source_type, transcription.import_type);
  const isImport = Boolean(importType);
  const selectedStem = transcription.selected_stem || "other";
  const trackCount = Number(transcription.track_count ?? tracks.length ?? 0);
  const isMultiTrack = trackCount > 1 || Boolean(transcription.output_mode === "multi_track");
  const hasNotes = Boolean(transcription.can_generate_score || hasNoteEvents(transcription.notes_data));
  const hasTabs = Boolean(transcription.can_generate_tab ?? hasTabData(transcription.tablature_data));
  const hasRhythm = Boolean(transcription.can_generate_rhythm ?? hasDrumHits(transcription.notes_data));
  const hasScore = Boolean(transcription.can_generate_score && (hasNotes || hasText(transcription.notation_data)));
  const hasPlayback = Boolean(transcription.can_play_stem || transcription.original_audio_url || transcription.separated_audio_url || transcription.audio_file_path);
  const stemLabel = isImport ? "Imported Project" : stemLabelOf(selectedStem);
  const instrumentLabel = instrumentLabelOf(selectedStem, transcription.instrument_type);
  const tuningLabel = transcription.tuning || (selectedStem === "bass" ? "E A D G" : selectedStem === "other" ? "E A D G B E" : null);
  const sourceBadge = importType === "midi"
    ? "MIDI IMPORT"
    : importType === "gp5"
      ? "GP5 IMPORT"
      : importType === "tab"
        ? "TAB IMPORT"
        : selectedStem === "other"
          ? "GUITAR STEM"
          : `${stemLabel.toUpperCase()} STEM`;
  const sourceLabel = importType === "midi"
    ? "Imported MIDI"
    : importType === "gp5"
      ? "Imported Guitar Pro"
      : importType === "tab"
        ? "Imported TAB"
        : selectedStem === "other" ? "Guitar/Accompaniment Stem" : `${stemLabel} Stem`;
  const outputBadges = [
    hasTabs ? "TAB READY" : null,
    hasScore ? "SCORE READY" : null,
    hasPlayback ? "SYNC READY" : null,
    hasRhythm ? "RHYTHM READY" : null,
    hasPlayback && !hasTabs && !hasScore && !hasRhythm ? "PLAYBACK ONLY" : null,
    isMultiTrack ? "MULTI-TRACK" : null,
    importType === "midi" ? "IMPORTED MIDI" : null,
    importType === "gp5" ? "IMPORTED GP5" : null,
  ].filter((badge): badge is string => Boolean(badge));
  const outputLabel = isMultiTrack
    ? "Multi-Track Project"
    : importType === "midi"
      ? "Imported MIDI Score"
      : importType === "gp5"
        ? "Imported Guitar Pro Score"
        : importType === "tab"
          ? "Imported TAB"
          : hasRhythm
    ? "Drum Rhythm Lane"
    : hasTabs && hasScore && selectedStem === "bass"
      ? "Bass Tab + Score"
      : hasTabs && hasScore
        ? "Guitar Tab + Score"
        : hasTabs
          ? selectedStem === "bass" ? "Bass Tab" : "Guitar Tab Attempt"
          : hasPlayback
            ? "Playback Only"
            : "Metadata Only";
  const playbackLabel = isMultiTrack
    ? "Multi-Track Playback"
    : selectedStem === "bass"
      ? "Bass Playback"
      : selectedStem === "drums"
        ? "Drum Playback"
        : selectedStem === "vocals"
          ? "Vocal Playback"
          : "Synced Stem Playback";
  const tone = importType === "midi"
    ? "midi"
    : importType === "gp5"
      ? "gp"
      : importType === "tab"
        ? "tab"
        : selectedStem === "bass"
          ? "bass"
          : selectedStem === "drums"
            ? "drums"
            : selectedStem === "vocals"
              ? "vocals"
              : "guitar";
  const durationSeconds = Math.max(
    Number(transcription.duration ?? 0),
    durationFromTimedData(transcription.notes_data, transcription.tablature_data),
    ...tracks.map((track) => durationFromTimedData(track.notes_json, track.tab_json)),
  );
  const description = (() => {
    if (isImport && isMultiTrack) return "Multi-track project imported successfully.";
    if (isImport) return `${sourceLabel} parsed successfully.`;
    if (selectedStem === "bass" && (hasTabs || hasScore)) return "Bass tab generated successfully.";
    if (selectedStem === "drums" && hasRhythm) return "Drum rhythm lane ready.";
    if (selectedStem === "vocals") return "Vocal stem playback is ready. Melody notation is planned for a future release.";
    if (hasPlayback && !hasNotes && !hasTabs && !hasRhythm) return "Playback available. No note events detected.";
    if (selectedStem === "other" && (hasTabs || hasScore)) return "Guitar transcription generated from selected stem.";
    return transcription.warning_message || "Playback available, but notation generation was limited.";
  })();

  return {
    stemLabel,
    instrumentLabel,
    sourceBadge,
    sourceLabel,
    outputLabel,
    playbackLabel,
    tuningLabel,
    importType,
    trackCount,
    isImport,
    isMultiTrack,
    tone,
    outputBadges,
    capabilities: {
      tabs: hasTabs,
      score: hasScore,
      rhythm: hasRhythm,
      playback: hasPlayback,
    },
    description,
    durationSeconds,
  };
};
