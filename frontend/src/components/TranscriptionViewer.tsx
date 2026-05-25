import React, {
  useState,
  useEffect,
  useMemo,
  useRef,
  useCallback,
} from "react";
import type { AlphaTabApi } from "@coderline/alphatab";
import audioService from "../services/audioService";
import type { InstrumentTrack, Transcription } from "../services/audioService";
import type { LyricsLanguage } from "../services/audioService";
import { buildTranscriptionMetadata } from "../utils/transcriptionMetadata";
import { useNavigate, useParams } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import {
  CheckCircle2,
  ChevronDown,
  Download,
  Expand,
  FileDown,
  FolderOpen,
  Info,
  Link as LinkIcon,
  Mic,
  Music2,
  Pause,
  Play,
  SlidersHorizontal,
  Volume2,
  Waves,
} from "lucide-react";

type TablatureNote = {
  id?: string | number;
  string?: number;
  fret?: number;
  startTime?: number;
  duration?: number;
  onset?: number;
  offset?: number;
  measure?: number;
  beat?: number;
  confidence?: number;
};

type ChordSegment = {
  chord?: string;
  chord_symbol?: string;
  onset?: number;
  offset?: number;
  confidence?: number;
};

type ScoreNote = TablatureNote & {
  pitch?: number;
};

type DrumHit = {
  onset?: number;
  offset?: number;
  intensity?: number;
  confidence?: number;
  instrument?: string;
  drum?: string;
  drum_type?: string;
  type?: string;
  label?: string;
  midi_note?: number;
  pitch?: number;
};

type DrumTabLaneKey = "cymbal" | "hihat" | "snare" | "tom" | "kick";

type DrumTabLane = {
  key: DrumTabLaneKey;
  label: string;
  cells: string[];
};

type DrumTabGrid = {
  lanes: DrumTabLane[];
  slotTimes: number[];
  stepDuration: number;
  subdivision: "1/4" | "1/8" | "1/16";
};

type LyricsSegment = {
  start?: number;
  end?: number;
  text?: string;
};

type LyricsData = {
  text?: string;
  segments?: LyricsSegment[];
  requested_language?: string | null;
  language?: string | null;
  model?: string;
  message?: string | null;
};

const lyricsLanguageOptions: Array<{ value: LyricsLanguage; label: string }> = [
  { value: "auto", label: "Auto detect" },
  { value: "en", label: "English" },
  { value: "tl", label: "Tagalog / Filipino" },
  { value: "ceb", label: "Cebuano / Bisaya" },
  { value: "es", label: "Spanish" },
  { value: "ja", label: "Japanese" },
  { value: "ko", label: "Korean" },
];

const lyricsLanguageLabel = (value: string | null | undefined): string => {
  const match = lyricsLanguageOptions.find((option) => option.value === value);
  return match?.label ?? (value ? value.toUpperCase() : "Auto detect");
};

const parseLyricsData = (
  value: string | null | undefined,
): LyricsData | null => {
  if (!value) return null;
  try {
    const parsed = JSON.parse(value) as unknown;
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      !Array.isArray(parsed)
    ) {
      return parsed as LyricsData;
    }
  } catch {
    return null;
  }
  return null;
};

const lyricStatusOf = (transcription: Transcription): string =>
  transcription.lyrics_generation_status || "pending";

const isGenerationInProgressStatus = (status: string | null | undefined) =>
  status === "queued" || status === "processing";

const isGenerationCompleteStatus = (status: string | null | undefined) =>
  status === "completed";

const isGenerationFailedStatus = (status: string | null | undefined) =>
  status === "failed";

const tabStatusOf = (transcription: Transcription): string =>
  transcription.tab_generation_status || "idle";

const rhythmStatusOf = (transcription: Transcription): string =>
  transcription.rhythm_generation_status || "idle";

const generationStatusForMode = (
  transcription: Transcription,
  mode: "tabs" | "rhythm" | "lyrics",
): string => {
  if (mode === "rhythm") return rhythmStatusOf(transcription);
  if (mode === "tabs") return tabStatusOf(transcription);
  return lyricStatusOf(transcription);
};

const isTabsGenerating = (transcription: Transcription): boolean =>
  (transcription.selected_stem === "other" ||
    transcription.selected_stem === "bass") &&
  isGenerationInProgressStatus(tabStatusOf(transcription));

const isRhythmGenerating = (transcription: Transcription): boolean =>
  transcription.selected_stem === "drums" &&
  isGenerationInProgressStatus(rhythmStatusOf(transcription));

const lyricTime = (seconds: number | undefined): string => {
  const value = Math.max(0, Number(seconds ?? 0));
  const minutes = Math.floor(value / 60);
  const remaining = Math.floor(value % 60);
  return `${minutes}:${remaining.toString().padStart(2, "0")}`;
};

const lyricSegmentTime = (value: number | undefined): number | null => {
  const time = Number(value);
  return Number.isFinite(time) ? time : null;
};

const lyricSegmentKey = (segment: LyricsSegment, index: number): string =>
  `${segment.start ?? "start"}-${segment.end ?? "end"}-${index}`;

type DrumTabMeasure = {
  measure: number;
  startSlot: number;
  endSlot: number;
  startTime: number;
  endTime: number;
  lanes: DrumTabLane[];
};

type ScoreSystem = {
  start: number;
  end: number;
  measureStarts: number[];
  notes: DisplayScoreNote[];
  chords: ChordSegment[];
};

type DisplayScoreNote = ScoreNote & {
  displayOnset: number;
};

type TimedTabNote = ScoreNote & {
  id: string;
  startTime: number;
  duration: number;
  onset: number;
  offset: number;
  string: number;
  fret: number;
  measure: number;
  beat: number;
};

type AlphaTexBuildResult = {
  tex: string;
  truncated: boolean;
  renderedBars: number;
};

type SelectedTrackView = "global" | number;

type ActiveScoreSource = {
  id: SelectedTrackView;
  title: string;
  label: string;
  instrumentType: string;
  tablatureData: unknown;
  notesData: unknown;
  chordsData: unknown;
  notationData: unknown;
  processingStatus?: string;
  confidenceScore?: number | null;
  confidenceNotes?: string | null;
  hasStemAudio: boolean;
  isGlobal: boolean;
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

const writeTextAt = (target: string[], text: string, startColumn: number) => {
  const column = Math.max(0, Math.min(startColumn, target.length - 1));
  text.split("").forEach((char, index) => {
    if (column + index < target.length) {
      target[column + index] = char;
    }
  });
};

const formatChordName = (value: string): string =>
  value.replace(":maj", "").replace(":min", "m").replace(":7", "7");

const tuningFromTablature = (tablatureData: unknown): number[] => {
  const parsed = parseJsonField(tablatureData);
  if (
    isRecord(parsed) &&
    Array.isArray(parsed.tuning) &&
    parsed.tuning.length > 0
  ) {
    const numericTuning = parsed.tuning
      .map(Number)
      .filter((note: number) => Number.isFinite(note));
    if (numericTuning.length > 0) return numericTuning;

    const labelTuning = parsed.tuning.map((note) =>
      String(note ?? "").trim().toUpperCase(),
    );
    if (labelTuning.join(" ") === "E A D G") return [28, 33, 38, 43];
    if (labelTuning.join(" ") === "E A D G B E") {
      return [40, 45, 50, 55, 59, 64];
    }
  }
  return [40, 45, 50, 55, 59, 64];
};

const labelsForTuning = (tuning: number[]): string[] => {
  if (tuning.length === 4) return ["G", "D", "A", "E"];
  return ["e", "B", "G", "D", "A", "E"].slice(0, Math.max(1, tuning.length));
};

const midiNoteToAlphaTexPitch = (midiNote: number): string => {
  const noteNames = [
    "C",
    "C#",
    "D",
    "D#",
    "E",
    "F",
    "F#",
    "G",
    "G#",
    "A",
    "A#",
    "B",
  ];
  const roundedNote = Math.round(midiNote);
  const noteName = noteNames[((roundedNote % 12) + 12) % 12];
  const octave = Math.floor(roundedNote / 12) - 1;
  return `${noteName}${octave}`;
};

const escapeAlphaTexText = (value: string): string =>
  value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');

const displayInstrumentName = (instrumentType: string): string => {
  if (!instrumentType) return "Track";
  return (
    instrumentType.charAt(0).toUpperCase() +
    instrumentType.slice(1).replace("_", " ")
  );
};

const exportSlug = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "") || "track";

const buildAsciiTab = (tablatureData: unknown, chordsData: unknown): string => {
  const parsed = parseJsonField(tablatureData);
  const notes: TablatureNote[] =
    isRecord(parsed) && Array.isArray(parsed.tablature)
      ? (parsed.tablature as TablatureNote[])
      : [];
  const parsedChords = parseJsonField(chordsData);
  const chords: ChordSegment[] =
    isRecord(parsedChords) && Array.isArray(parsedChords.chords)
      ? (parsedChords.chords as ChordSegment[])
      : isRecord(parsedChords) && Array.isArray(parsedChords.chord_charts)
        ? (parsedChords.chord_charts as ChordSegment[])
        : [];

  if (notes.length === 0) return "";

  const maxOffset = Math.max(
    ...notes.map((note) => noteStartTime(note) + noteDuration(note, 0.12)),
    0.1,
  );
  const blockTime = 0.1;
  const columnsPerBlock = 2;
  const totalColumns = Math.max(
    24,
    Math.ceil(maxOffset / blockTime) * columnsPerBlock,
  );
  const tuning = tuningFromTablature(tablatureData);
  const labels = labelsForTuning(tuning);
  const rows = labels.map(() => Array(totalColumns).fill("-"));
  const chordRow = Array(totalColumns).fill(" ");

  notes.forEach((note) => {
    const stringNumber = Number(note.string);
    const fret = Number(note.fret);
    const onset = noteStartTime(note);
    if (
      !Number.isFinite(stringNumber) ||
      stringNumber < 1 ||
      stringNumber > labels.length
    )
      return;
    if (!Number.isFinite(fret) || fret < 0) return;

    const rowIndex = stringNumber - 1;
    const columnStart = Math.min(
      Math.max(Math.round(onset / blockTime) * columnsPerBlock, 0),
      totalColumns - 1,
    );
    const fretText = String(fret).padStart(2, " ");
    writeTextAt(rows[rowIndex], fretText, columnStart);
  });

  chords.forEach((segment) => {
    const rawChord = segment.chord ?? segment.chord_symbol ?? "";
    if (!rawChord || rawChord === "N") return;

    const onset = Number(segment.onset ?? 0);
    if (!Number.isFinite(onset) || onset < 0) return;

    const columnStart = Math.min(
      Math.max(Math.round(onset / blockTime) * columnsPerBlock, 0),
      totalColumns - 1,
    );
    writeTextAt(chordRow, formatChordName(rawChord), columnStart);
  });

  const systemWidth = 96;
  const systems: string[] = [];
  for (let start = 0; start < totalColumns; start += systemWidth) {
    const end = Math.min(start + systemWidth, totalColumns);
    const chordSlice = chordRow.slice(start, end).join("").trimEnd();
    if (chordSlice.trim().length > 0) {
      systems.push(`  ${chordSlice}`);
    }
    labels.forEach((label, index) => {
      systems.push(`${label}|${rows[index].slice(start, end).join("")}`);
    });
    systems.push("");
  }

  return systems.join("\n").trimEnd();
};

const hasUsableBlob = (value: unknown): boolean =>
  typeof value === "string" && value.trim().length > 0;

const mediaErrorDetails = (audio: HTMLMediaElement) => {
  const error = audio.error;
  if (!error) return null;
  const messages: Record<number, string> = {
    [MediaError.MEDIA_ERR_ABORTED]: "Playback was aborted.",
    [MediaError.MEDIA_ERR_NETWORK]: "A network error interrupted loading.",
    [MediaError.MEDIA_ERR_DECODE]: "The audio could not be decoded.",
    [MediaError.MEDIA_ERR_SRC_NOT_SUPPORTED]:
      "The audio source is not supported.",
  };
  return {
    code: error.code,
    message: error.message || messages[error.code] || "Unknown media error.",
  };
};

const probeAudioNetwork = async (src: string): Promise<void> => {
  if (!src || src.startsWith("blob:")) return;
  try {
    const response = await fetch(src, { method: "HEAD", mode: "cors" });
    console.error("Audio playback network probe", {
      src,
      ok: response.ok,
      status: response.status,
      statusText: response.statusText,
      contentType: response.headers.get("content-type"),
    });
  } catch (error: unknown) {
    console.error("Audio playback network error", {
      src,
      error: errorMessageOf(error, "Network request failed"),
    });
  }
};

const selectedStemInstrument = (
  selectedStem: string | null | undefined,
): string =>
  ({
    other: "guitar",
    bass: "bass",
    drums: "drums",
    vocals: "vocals",
  })[selectedStem || "other"] ?? "guitar";

const selectedStemLabel = (selectedStem: string | null | undefined): string =>
  ({
    other: "Guitar/Accompaniment",
    bass: "Bass",
    drums: "Drums",
    vocals: "Vocals",
  })[selectedStem || "other"] ?? "Guitar/Accompaniment";

const trackHasStemAudio = (
  transcription: Transcription | null,
  track: InstrumentTrack,
): boolean =>
  hasUsableBlob(track.stem_audio_path) ||
  (hasUsableBlob(transcription?.separated_audio_url) &&
    track.instrument_type ===
      selectedStemInstrument(transcription?.selected_stem));

const extractNoteEvents = (notesData: unknown): ScoreNote[] => {
  const parsed = parseJsonField(notesData);
  if (Array.isArray(parsed)) return parsed;
  if (!isRecord(parsed)) return [];
  if (Array.isArray(parsed.notes)) return parsed.notes as ScoreNote[];
  if (Array.isArray(parsed.pitch_info)) return parsed.pitch_info as ScoreNote[];
  return [];
};

const extractDrumHits = (notesData: unknown): DrumHit[] => {
  const parsed = parseJsonField(notesData);
  if (!isRecord(parsed) || !Array.isArray(parsed.drum_hits)) return [];

  return (parsed.drum_hits as DrumHit[])
    .filter((hit) => Number.isFinite(Number(hit.onset)))
    .sort((a, b) => Number(a.onset ?? 0) - Number(b.onset ?? 0));
};

const getDrumTotalDuration = (notesData: unknown, hits: DrumHit[]): number => {
  const parsed = parseJsonField(notesData);
  if (isRecord(parsed) && isRecord(parsed.rhythm_analysis)) {
    const duration = Number(parsed.rhythm_analysis.total_duration);
    if (Number.isFinite(duration) && duration > 0) return duration;
  }

  return Math.max(
    ...hits.map((hit) => Number(hit.offset ?? hit.onset ?? 0)),
    0,
  );
};

const normalizeDrumLane = (value: unknown): DrumTabLaneKey | null => {
  const label = String(value ?? "").toLowerCase();
  if (!label) return null;
  if (
    label.includes("kick") ||
    label.includes("bass drum") ||
    label === "bd" ||
    label === "kd"
  ) {
    return "kick";
  }
  if (label.includes("snare") || label === "sd") return "snare";
  if (
    label.includes("hi-hat") ||
    label.includes("hihat") ||
    label.includes("hat") ||
    label === "hh"
  ) {
    return "hihat";
  }
  if (label.includes("tom") || label === "tt" || label === "ft") return "tom";
  if (
    label.includes("cymbal") ||
    label.includes("crash") ||
    label.includes("ride") ||
    label === "cy" ||
    label === "cr" ||
    label === "rd"
  ) {
    return "cymbal";
  }
  return null;
};

const laneFromMidiNote = (value: unknown): DrumTabLaneKey | null => {
  const note = Number(value);
  if (!Number.isFinite(note)) return null;
  if ([35, 36].includes(note)) return "kick";
  if ([38, 40].includes(note)) return "snare";
  if ([42, 44, 46].includes(note)) return "hihat";
  if ([41, 43, 45, 47, 48, 50].includes(note)) return "tom";
  if ([49, 51, 52, 53, 55, 57, 59].includes(note)) return "cymbal";
  return null;
};

const inferDrumLane = (
  hit: DrumHit,
  slotIndex: number,
  slotCount: number,
): DrumTabLaneKey => {
  const explicitLane =
    normalizeDrumLane(hit.instrument) ??
    normalizeDrumLane(hit.drum) ??
    normalizeDrumLane(hit.drum_type) ??
    normalizeDrumLane(hit.type) ??
    normalizeDrumLane(hit.label) ??
    laneFromMidiNote(hit.midi_note) ??
    laneFromMidiNote(hit.pitch);

  if (explicitLane) return explicitLane;

  const intensity = Math.max(
    0,
    Math.min(1, Number(hit.intensity ?? hit.confidence ?? 0.5)),
  );
  const sixteenthInBar = slotIndex % 16;
  const nearMeasureStart = sixteenthInBar <= 1 || sixteenthInBar >= 15;
  const nearBackbeat =
    Math.abs(sixteenthInBar - 4) <= 1 || Math.abs(sixteenthInBar - 12) <= 1;
  const sparsePattern = slotCount <= 12;

  if (nearMeasureStart && intensity >= 0.82) return "cymbal";
  if ((sixteenthInBar === 0 || sixteenthInBar === 8) && intensity >= 0.52) {
    return "kick";
  }
  if (nearBackbeat && intensity >= 0.46) return "snare";
  if (sparsePattern && intensity >= 0.68) return "kick";
  if (intensity >= 0.74) return "snare";
  return "hihat";
};

const drumSymbolForLane = (lane: DrumTabLaneKey): string =>
  lane === "kick" ? "o" : lane === "snare" || lane === "tom" ? "o" : "x";

const chooseDrumSubdivision = (
  tempo: number | null | undefined,
  duration: number,
): { subdivision: DrumTabGrid["subdivision"]; stepDuration: number } => {
  const quarterDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const sixteenthDuration = quarterDuration / 4;
  const estimatedSlots = duration / sixteenthDuration;

  if (estimatedSlots <= 96) {
    return { subdivision: "1/16", stepDuration: sixteenthDuration };
  }
  if (estimatedSlots <= 192) {
    return { subdivision: "1/8", stepDuration: quarterDuration / 2 };
  }
  return { subdivision: "1/4", stepDuration: quarterDuration };
};

const buildDrumTabGrid = (
  hits: DrumHit[],
  duration: number,
  tempo?: number | null,
): DrumTabGrid | null => {
  if (hits.length < 2) return null;

  const { subdivision, stepDuration } = chooseDrumSubdivision(tempo, duration);
  const slotCount = Math.max(16, Math.ceil(duration / stepDuration) + 1);
  const laneDefinitions: Array<{ key: DrumTabLaneKey; label: string }> = [
    { key: "cymbal", label: "CY" },
    { key: "hihat", label: "HH" },
    { key: "snare", label: "SD" },
    { key: "tom", label: "TM" },
    { key: "kick", label: "BD" },
  ];
  const lanes = laneDefinitions.map(({ key, label }) => ({
    key,
    label,
    cells: Array.from({ length: slotCount }, () => "-"),
  }));

  hits.forEach((hit) => {
    const onset = Number(hit.onset ?? 0);
    const slotIndex = Math.max(
      0,
      Math.min(slotCount - 1, Math.round(onset / stepDuration)),
    );
    const laneKey = inferDrumLane(hit, slotIndex, slotCount);
    const lane = lanes.find((item) => item.key === laneKey);
    if (lane) lane.cells[slotIndex] = drumSymbolForLane(laneKey);
  });

  const populatedLanes = lanes.filter((lane) =>
    lane.cells.some((cell) => cell !== "-"),
  );

  return {
    lanes: populatedLanes,
    slotTimes: Array.from(
      { length: slotCount },
      (_item, index) => index * stepDuration,
    ),
    stepDuration,
    subdivision,
  };
};

const slotsPerDrumMeasure = (
  subdivision: DrumTabGrid["subdivision"],
): number => {
  if (subdivision === "1/4") return 4;
  if (subdivision === "1/8") return 8;
  return 16;
};

const groupDrumTabMeasures = (grid: DrumTabGrid): DrumTabMeasure[] => {
  const measureSlots = slotsPerDrumMeasure(grid.subdivision);
  const measures: DrumTabMeasure[] = [];

  for (
    let startSlot = 0, measure = 1;
    startSlot < grid.slotTimes.length;
    startSlot += measureSlots, measure += 1
  ) {
    const endSlot = Math.min(startSlot + measureSlots, grid.slotTimes.length);
    measures.push({
      measure,
      startSlot,
      endSlot,
      startTime: grid.slotTimes[startSlot] ?? startSlot * grid.stepDuration,
      endTime:
        (grid.slotTimes[endSlot - 1] ?? (endSlot - 1) * grid.stepDuration) +
        grid.stepDuration,
      lanes: grid.lanes.map((lane) => ({
        ...lane,
        cells: lane.cells.slice(startSlot, endSlot),
      })),
    });
  }

  return measures;
};

const extractTabNotes = (tablatureData: unknown): ScoreNote[] => {
  const parsed = parseJsonField(tablatureData);
  return isRecord(parsed) && Array.isArray(parsed.tablature)
    ? (parsed.tablature as ScoreNote[])
    : [];
};

const noteStartTime = (note: TablatureNote): number => {
  const startTime = Number(note.startTime);
  if (Number.isFinite(startTime)) return startTime;
  const onset = Number(note.onset);
  return Number.isFinite(onset) ? onset : 0;
};

const noteDuration = (
  note: TablatureNote,
  fallbackDuration: number,
): number => {
  const duration = Number(note.duration);
  if (Number.isFinite(duration) && duration > 0) return duration;

  const startTime = noteStartTime(note);
  const offset = Number(note.offset);
  if (Number.isFinite(offset) && offset > startTime) {
    return offset - startTime;
  }

  return fallbackDuration;
};

const buildTimedTabNotes = (
  tablatureData: unknown,
  notesData: unknown,
  tempo?: number | null,
): TimedTabNote[] => {
  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const measureDuration = beatDuration * 4;
  const fallbackDuration = Math.max(0.12, beatDuration * 0.45);

  return buildScoreNotes(tablatureData, notesData)
    .map((note, index) => {
      const startTime = noteStartTime(note);
      const duration = noteDuration(note, fallbackDuration);
      const onset = startTime;
      const stringNumber = Math.round(Number(note.string));
      const fret = Math.round(Number(note.fret));
      if (
        !Number.isFinite(startTime) ||
        !Number.isFinite(duration) ||
        !Number.isFinite(stringNumber) ||
        !Number.isFinite(fret) ||
        stringNumber < 1 ||
        fret < 0
      ) {
        return null;
      }

      const offset = startTime + Math.max(0.08, duration);
      const measuredBeat =
        Math.floor((startTime % measureDuration) / beatDuration) + 1;

      return {
        ...note,
        id:
          note.id !== undefined && note.id !== null
            ? String(note.id)
            : `${index}-${startTime}-${stringNumber}-${fret}`,
        startTime,
        duration,
        onset,
        offset,
        string: stringNumber,
        fret,
        measure: Number.isFinite(Number(note.measure))
          ? Math.max(1, Math.round(Number(note.measure)))
          : Math.floor(startTime / measureDuration) + 1,
        beat: Number.isFinite(Number(note.beat))
          ? Number(note.beat)
          : measuredBeat,
      };
    })
    .filter((note): note is TimedTabNote => note !== null)
    .sort((a, b) => a.startTime - b.startTime || a.string - b.string);
};

const activeTimedNoteIdsAt = (
  notes: TimedTabNote[],
  activeTime: number,
): Set<string> => {
  const ids = new Set<string>();
  notes.forEach((note) => {
    const audibleUntil = note.startTime + Math.max(note.duration, 0.08);
    if (activeTime >= note.startTime && activeTime < audibleUntil) {
      ids.add(note.id);
    }
  });
  return ids;
};

const extractChords = (chordsData: unknown): ChordSegment[] => {
  const parsed = parseJsonField(chordsData);
  if (isRecord(parsed) && Array.isArray(parsed.chords))
    return parsed.chords as ChordSegment[];
  if (isRecord(parsed) && Array.isArray(parsed.chord_charts))
    return parsed.chord_charts as ChordSegment[];
  return [];
};

const pitchFromTabNote = (
  note: TablatureNote,
  tuning: number[] = [40, 45, 50, 55, 59, 64],
) => {
  const stringNumber = Number(note.string);
  const fret = Number(note.fret);
  if (!Number.isFinite(stringNumber) || !Number.isFinite(fret))
    return undefined;
  if (stringNumber < 1 || stringNumber > tuning.length || fret < 0)
    return undefined;
  return tuning[tuning.length - stringNumber] + fret;
};

const buildScoreNotes = (
  tablatureData: unknown,
  notesData: unknown,
): ScoreNote[] => {
  const tabNotes = extractTabNotes(tablatureData);
  const noteEvents = extractNoteEvents(notesData);
  const tuning = tuningFromTablature(tablatureData);

  if (tabNotes.length === 0) {
    return noteEvents
      .map((note) => ({
        ...note,
        onset: noteStartTime(note),
        startTime: noteStartTime(note),
        pitch: Number(note.pitch),
      }))
      .filter(
        (note) =>
          Number.isFinite(Number(note.onset)) &&
          Number.isFinite(Number(note.pitch)),
      );
  }

  return tabNotes
    .map((tabNote) => {
      const onset = noteStartTime(tabNote);
      const matchingEvent = noteEvents.find((event) => {
        const eventOnset = noteStartTime(event);
        return Math.abs(eventOnset - onset) < 0.03;
      });

      return {
        ...tabNote,
        onset,
        startTime: onset,
        pitch: Number(
          matchingEvent?.pitch ?? pitchFromTabNote(tabNote, tuning),
        ),
      };
    })
    .filter(
      (note) =>
        Number.isFinite(Number(note.onset)) &&
        Number.isFinite(Number(note.fret)),
    );
};

const buildAlphaTexFromScore = ({
  title,
  tempo,
  tablatureData,
  notesData,
  instrumentType,
}: {
  title: string;
  tempo?: number;
  tablatureData: unknown;
  notesData: unknown;
  instrumentType: string;
}): AlphaTexBuildResult | null => {
  const tuning = tuningFromTablature(tablatureData);
  const notes = buildScoreNotes(tablatureData, notesData)
    .filter((note) => {
      const stringNumber = Number(note.string);
      const fret = Number(note.fret);
      return (
        Number.isFinite(Number(note.onset)) &&
        Number.isFinite(stringNumber) &&
        Number.isFinite(fret) &&
        stringNumber >= 1 &&
        stringNumber <= tuning.length &&
        fret >= 0 &&
        fret <= 36
      );
    })
    .sort((a, b) => Number(a.onset ?? 0) - Number(b.onset ?? 0));

  if (notes.length === 0) return null;

  const safeTempo = tempo && tempo > 0 ? tempo : 120;
  const sixteenthDuration = 60 / safeTempo / 4;
  const maxSlots = 3072;
  const slotMap = new Map<number, string[]>();
  let highestSlot = 0;

  notes.forEach((note) => {
    const slot = Math.max(
      0,
      Math.round(noteStartTime(note) / sixteenthDuration),
    );
    if (slot >= maxSlots) return;

    const stringNumber = Math.round(Number(note.string));
    const fret = Math.round(Number(note.fret));
    const token = `${fret}.${stringNumber}`;
    const existing = slotMap.get(slot) ?? [];
    if (!existing.includes(token)) {
      existing.push(token);
    }
    slotMap.set(slot, existing);
    highestSlot = Math.max(highestSlot, slot);
  });

  if (slotMap.size === 0) return null;

  const slotCount = Math.min(
    maxSlots,
    Math.max(16, Math.ceil((highestSlot + 1) / 16) * 16),
  );
  const tokens: string[] = [":16"];

  for (let slot = 0; slot < slotCount; slot += 1) {
    const slotNotes = slotMap.get(slot);
    if (!slotNotes || slotNotes.length === 0) {
      tokens.push("r");
    } else if (slotNotes.length === 1) {
      tokens.push(slotNotes[0]);
    } else {
      tokens.push(`(${slotNotes.join(" ")})`);
    }

    if ((slot + 1) % 16 === 0 && slot + 1 < slotCount) {
      tokens.push("|");
    }
  }

  const instrumentName = displayInstrumentName(instrumentType);
  const alphaTexTuning = tuning
    .slice()
    .reverse()
    .map(midiNoteToAlphaTexPitch)
    .join(" ");

  return {
    tex: [
      `\\title "${escapeAlphaTexText(title || `${instrumentName} Transcription`)}"`,
      `\\subtitle "${escapeAlphaTexText(`${instrumentName} AI draft`)}"`,
      `\\tempo ${Math.round(safeTempo)}`,
      "\\track",
      "\\staff { score tabs }",
      `\\tuning (${alphaTexTuning}) { label "${escapeAlphaTexText(`${instrumentName} tuning`)}" }`,
      tokens.join(" "),
    ].join("\n"),
    truncated: highestSlot >= maxSlots,
    renderedBars: Math.ceil(slotCount / 16),
  };
};

const confidenceOf = (value?: number) =>
  Number.isFinite(Number(value)) ? Number(value) : 0;

const hasConfidenceScore = (value: unknown): value is number =>
  value !== null && value !== undefined && Number.isFinite(Number(value));

const prepareDisplayNotes = (
  notes: ScoreNote[],
  tempo?: number,
): DisplayScoreNote[] => {
  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const gridSize = Math.max(0.08, beatDuration / 4);
  const bestBySlot = new Map<string, DisplayScoreNote>();

  notes.forEach((note) => {
    const onset = noteStartTime(note);
    const stringNumber = Number(note.string);
    const pitch = Number(note.pitch);
    if (!Number.isFinite(onset)) return;
    if (!Number.isFinite(stringNumber) && !Number.isFinite(pitch)) return;

    const slot = Math.round(onset / gridSize);
    const displayOnset = slot * gridSize;
    const key = `${slot}:${Number.isFinite(stringNumber) ? `s${stringNumber}` : `p${pitch}`}`;
    const candidate = { ...note, displayOnset };
    const existing = bestBySlot.get(key);
    if (
      !existing ||
      confidenceOf(candidate.confidence) >= confidenceOf(existing.confidence)
    ) {
      bestBySlot.set(key, candidate);
    }
  });

  return Array.from(bestBySlot.values()).sort(
    (a, b) =>
      a.displayOnset - b.displayOnset ||
      Number(a.string ?? a.pitch ?? 0) - Number(b.string ?? b.pitch ?? 0),
  );
};

const mergeChordSegments = (chords: ChordSegment[]): ChordSegment[] => {
  const merged: ChordSegment[] = [];

  chords
    .filter((chord) => {
      const rawChord = chord.chord ?? chord.chord_symbol ?? "";
      const confidence = chord.confidence;
      return (
        rawChord &&
        rawChord !== "N" &&
        Number.isFinite(Number(chord.onset ?? 0)) &&
        (!Number.isFinite(Number(confidence)) || Number(confidence) >= 0.32)
      );
    })
    .sort((a, b) => Number(a.onset ?? 0) - Number(b.onset ?? 0))
    .forEach((chord) => {
      const rawChord = chord.chord ?? chord.chord_symbol ?? "";
      const last = merged[merged.length - 1];
      const lastRaw = last?.chord ?? last?.chord_symbol ?? "";

      if (
        last &&
        lastRaw === rawChord &&
        Number(chord.onset ?? 0) - Number(last.offset ?? last.onset ?? 0) < 0.18
      ) {
        last.offset = Math.max(
          Number(last.offset ?? 0),
          Number(chord.offset ?? chord.onset ?? 0),
        );
        last.confidence = Math.max(
          confidenceOf(last.confidence),
          confidenceOf(chord.confidence),
        );
        return;
      }

      merged.push({ ...chord });
    });

  return merged;
};

const buildScoreSystems = (
  notes: DisplayScoreNote[],
  chords: ChordSegment[],
  tempo?: number,
): ScoreSystem[] => {
  if (notes.length === 0) return [];

  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const measureDuration = beatDuration * 4;
  const maxDurationPerSystem = measureDuration * 2;
  const maxNotesPerSystem = 24;
  const systems: ScoreSystem[] = [];
  let start = Math.max(
    0,
    Math.floor(notes[0].displayOnset / measureDuration) * measureDuration,
  );
  let current: DisplayScoreNote[] = [];

  notes.forEach((note) => {
    const onset = note.displayOnset;
    const isFull = current.length >= maxNotesPerSystem;
    const isTooWide =
      onset - start >= maxDurationPerSystem && current.length > 0;
    if (isFull || isTooWide) {
      const end = Math.max(
        start + measureDuration,
        current[current.length - 1].displayOnset + beatDuration,
      );
      systems.push({
        start,
        end,
        measureStarts: [],
        notes: current,
        chords: [],
      });
      start = Math.max(
        0,
        Math.floor(onset / measureDuration) * measureDuration,
      );
      current = [];
    }
    current.push(note);
  });

  if (current.length > 0) {
    const end = Math.max(
      start + measureDuration,
      current[current.length - 1].displayOnset + beatDuration,
    );
    systems.push({
      start,
      end,
      measureStarts: [],
      notes: current,
      chords: [],
    });
  }

  const mergedChords = mergeChordSegments(chords);

  return systems.map((system) => {
    const end = system.end;
    const measureStarts = Array.from(
      {
        length: Math.max(
          2,
          Math.ceil((end - system.start) / measureDuration) + 1,
        ),
      },
      (_item, measureIndex) => system.start + measureIndex * measureDuration,
    ).filter((measureStart) => measureStart <= end + 0.01);

    return {
      ...system,
      end,
      measureStarts,
      chords: mergedChords.filter((chord) => {
        const onset = Number(chord.onset ?? 0);
        return onset >= system.start && onset < end;
      }),
    };
  });
};

const staffYForPitch = (pitch?: number) => {
  if (!Number.isFinite(Number(pitch))) return 34;
  const clamped = Math.max(52, Math.min(84, Number(pitch)));
  return 34 - (clamped - 64) * 2.1;
};

const formatDuration = (time: number): string => {
  const safeTime = Number.isFinite(time) ? Math.max(0, time) : 0;
  const minutes = Math.floor(safeTime / 60);
  const seconds = Math.floor(safeTime % 60);
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
};

const ScoreSheet = ({
  title,
  tempo,
  detectedKey,
  currentTime,
  tablatureData,
  notesData,
  chordsData,
  instrumentType,
  onSeek,
}: {
  title: string;
  tempo?: number;
  detectedKey?: string;
  currentTime: number;
  tablatureData: unknown;
  notesData: unknown;
  chordsData: unknown;
  instrumentType: string;
  onSeek: (time: number) => void;
}) => {
  const frameRef = useRef<HTMLDivElement>(null);
  const systemRefs = useRef<Array<SVGGElement | null>>([]);
  const tuning = useMemo(
    () => tuningFromTablature(tablatureData),
    [tablatureData],
  );
  const hasTablature = useMemo(
    () => extractTabNotes(tablatureData).length > 0,
    [tablatureData],
  );
  const stringCount = Math.max(1, tuning.length);
  const timedTabNotes = useMemo(
    () => buildTimedTabNotes(tablatureData, notesData, tempo),
    [notesData, tablatureData, tempo],
  );
  const scoreNotes = useMemo(
    () =>
      prepareDisplayNotes(
        hasTablature
          ? timedTabNotes
          : buildScoreNotes(tablatureData, notesData),
        tempo,
      ),
    [hasTablature, notesData, tablatureData, tempo, timedTabNotes],
  );
  const chords = useMemo(() => extractChords(chordsData), [chordsData]);
  const systems = useMemo(
    () => buildScoreSystems(scoreNotes, chords, tempo),
    [scoreNotes, chords, tempo],
  );
  const activeTime = Number.isFinite(currentTime) ? currentTime : 0;
  const activeSystemIndex = systems.findIndex(
    (system) => activeTime >= system.start && activeTime <= system.end,
  );
  const activeNoteIds = useMemo(
    () => activeTimedNoteIdsAt(timedTabNotes, activeTime),
    [activeTime, timedTabNotes],
  );

  useEffect(() => {
    if (activeSystemIndex < 0) return;

    const activeSystem = systemRefs.current[activeSystemIndex];
    const scrollContainer = frameRef.current?.closest(".score-viewer");
    if (!activeSystem || !(scrollContainer instanceof HTMLElement)) return;

    const containerRect = scrollContainer.getBoundingClientRect();
    const systemRect = activeSystem.getBoundingClientRect();
    const comfortableTop = containerRect.top + containerRect.height * 0.2;
    const comfortableBottom = containerRect.bottom - containerRect.height * 0.2;

    if (
      systemRect.top >= comfortableTop &&
      systemRect.bottom <= comfortableBottom
    )
      return;

    const nextScrollTop =
      scrollContainer.scrollTop +
      systemRect.top -
      containerRect.top -
      (containerRect.height - systemRect.height) / 2;

    scrollContainer.scrollTo({
      top: Math.max(0, nextScrollTop),
      behavior: "smooth",
    });
  }, [activeSystemIndex]);

  if (systems.length === 0) return null;

  const width = 1000;
  const left = 86;
  const right = 956;
  const notationTop = 86;
  const tabTop = 172;
  const staffGap = 9;
  const systemHeight = hasTablature ? 248 : 174;
  const pageHeight = 214 + systems.length * systemHeight;
  const instrumentName = displayInstrumentName(instrumentType);
  const pageTitle =
    title && title.length > 52
      ? `${title.slice(0, 49)}...`
      : title || `${instrumentName} Transcription`;

  const timeToX = (time: number, system: ScoreSystem) => {
    const progress =
      (time - system.start) / Math.max(system.end - system.start, 0.1);
    return left + Math.max(0, Math.min(1, progress)) * (right - left);
  };

  return (
    <div className="score-sheet-frame" ref={frameRef}>
      <svg
        className="score-sheet"
        viewBox={`0 0 ${width} ${pageHeight}`}
        role="img"
        aria-label={`${pageTitle} ${instrumentName.toLowerCase()} score`}
      >
        <rect width={width} height={pageHeight} fill="#fff" />
        <text x={width / 2} y="58" textAnchor="middle" className="score-title">
          {pageTitle}
        </text>
        <text
          x={width / 2}
          y="84"
          textAnchor="middle"
          className="score-subtitle"
        >
          {instrumentName} transcription
        </text>
        <text x={left} y="118" className="score-meta">
          {hasTablature
            ? stringCount === 4
              ? "Standard bass tuning"
              : "Standard tuning"
            : "Staff notation"}
        </text>
        <text x={left} y="146" className="score-tempo">
          q = {tempo || 120}
        </text>
        <text x={right} y="118" textAnchor="end" className="score-meta">
          {detectedKey ? `Key: ${detectedKey}` : "AI generated score"}
        </text>
        <text x={left} y="176" className="score-section">
          Intro
        </text>

        {systems.map((system, systemIndex) => {
          const y = 204 + systemIndex * systemHeight;
          const notationY = y + notationTop;
          const tabY = y + tabTop;
          const contentBottom = hasTablature
            ? tabY + (stringCount - 1) * staffGap + 48
            : notationY + 4 * staffGap + 48;
          const isActiveSystem =
            activeTime >= system.start && activeTime <= system.end;
          const playheadX = timeToX(activeTime, system);
          let lastChordX = -Infinity;

          return (
            <g key={`${system.start}-${system.end}`}>
              <g
                ref={(node) => {
                  systemRefs.current[systemIndex] = node;
                }}
                aria-hidden="true"
              >
                <rect
                  x={left - 64}
                  y={notationY - 52}
                  width={right - left + 96}
                  height={contentBottom - notationY + 32}
                  fill="transparent"
                />
              </g>
              {isActiveSystem && (
                <g className="score-playback-layer">
                  <rect
                    x={left - 8}
                    y={notationY - 32}
                    width={right - left + 16}
                    height={contentBottom - notationY}
                    className="score-active-system"
                  />
                  <line
                    x1={playheadX}
                    x2={playheadX}
                    y1={notationY - 38}
                    y2={contentBottom - 30}
                    className="score-playhead"
                  />
                </g>
              )}

              <text
                x={left - 24}
                y={notationY - 14}
                className="score-measure-number"
              >
                {systemIndex * 2 + 1}
              </text>
              <text x={left - 52} y={notationY + 24} className="score-clef">
                G
              </text>
              <text x={left - 50} y={notationY + 54} className="score-time">
                4/4
              </text>
              {hasTablature && (
                <text
                  x={left - 34}
                  y={tabY + 27}
                  className="score-tab-label"
                  transform={`rotate(-90 ${left - 34} ${tabY + 27})`}
                >
                  TAB
                </text>
              )}

              {Array.from({ length: 5 }, (_item, lineIndex) => (
                <line
                  key={`staff-${lineIndex}`}
                  x1={left}
                  x2={right}
                  y1={notationY + lineIndex * staffGap}
                  y2={notationY + lineIndex * staffGap}
                  className="score-staff-line"
                />
              ))}
              {hasTablature &&
                Array.from({ length: stringCount }, (_item, lineIndex) => (
                  <line
                    key={`tab-${lineIndex}`}
                    x1={left}
                    x2={right}
                    y1={tabY + lineIndex * staffGap}
                    y2={tabY + lineIndex * staffGap}
                    className="score-tab-line"
                  />
                ))}

              {system.measureStarts.map((measureStart) => {
                const x = timeToX(measureStart, system);
                return (
                  <g key={`bar-${measureStart}`}>
                    <line
                      x1={x}
                      x2={x}
                      y1={notationY}
                      y2={notationY + 4 * staffGap}
                      className="score-barline"
                    />
                    {hasTablature && (
                      <line
                        x1={x}
                        x2={x}
                        y1={tabY}
                        y2={tabY + (stringCount - 1) * staffGap}
                        className="score-barline"
                      />
                    )}
                  </g>
                );
              })}

              {system.chords.map((chord, chordIndex) => {
                const rawChord = chord.chord ?? chord.chord_symbol ?? "";
                const chordX = timeToX(
                  Number(chord.onset ?? system.start),
                  system,
                );
                if (chordX - lastChordX < 54) return null;
                lastChordX = chordX;
                return (
                  <text
                    key={`chord-${chordIndex}-${rawChord}`}
                    x={chordX}
                    y={notationY - 18}
                    className="score-chord"
                  >
                    {formatChordName(rawChord)}
                  </text>
                );
              })}

              {system.notes.map((note, noteIndex) => {
                const onset = Number(
                  note.displayOnset ?? note.onset ?? system.start,
                );
                const startTime = noteStartTime(note);
                const duration = noteDuration(note, 0.12);
                const offset = startTime + Math.max(duration, 0.08);
                const isCurrentNote =
                  isActiveSystem &&
                  (note.id !== undefined
                    ? activeNoteIds.has(String(note.id))
                    : activeTime >= startTime && activeTime < offset);
                const x = timeToX(onset, system);
                const noteY = notationY + staffYForPitch(note.pitch);
                const stringNumber = Math.max(
                  1,
                  Math.min(stringCount, Number(note.string || 1)),
                );
                const fret = Number(note.fret ?? 0);
                const tabNoteY = tabY + (stringNumber - 1) * staffGap + 3;

                return (
                  <g
                    key={`note-${noteIndex}-${onset}-${fret}`}
                    className={isCurrentNote ? "score-current-note" : undefined}
                    role="button"
                    tabIndex={0}
                    onClick={() => onSeek(startTime)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSeek(startTime);
                      }
                    }}
                  >
                    {isCurrentNote && (
                      <circle
                        cx={x}
                        cy={noteY}
                        r="10"
                        className="score-current-note-halo"
                      />
                    )}
                    <ellipse
                      cx={x}
                      cy={noteY}
                      rx="5.8"
                      ry="4.2"
                      className="score-notehead"
                    />
                    <line
                      x1={x + 5}
                      x2={x + 5}
                      y1={noteY}
                      y2={noteY - 30}
                      className="score-stem"
                    />
                    {hasTablature && isCurrentNote && (
                      <rect
                        x={x - 11}
                        y={tabNoteY - 14}
                        width="22"
                        height="18"
                        rx="3"
                        className="score-current-fret-bg"
                      />
                    )}
                    {hasTablature && (
                      <text
                        x={x}
                        y={tabNoteY}
                        textAnchor="middle"
                        className="score-fret"
                      >
                        {fret}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
    </div>
  );
};

const AlphaTabScore = ({
  title,
  tempo,
  tablatureData,
  notesData,
  instrumentType,
  fallback,
}: {
  title: string;
  tempo?: number;
  tablatureData: unknown;
  notesData: unknown;
  instrumentType: string;
  fallback: React.ReactNode;
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const apiRef = useRef<AlphaTabApi | null>(null);
  const [renderState, setRenderState] = useState<
    "idle" | "loading" | "ready" | "error"
  >("idle");
  const [renderError, setRenderError] = useState<string | null>(null);
  const alphaTex = useMemo(
    () =>
      buildAlphaTexFromScore({
        title,
        tempo,
        tablatureData,
        notesData,
        instrumentType,
      }),
    [instrumentType, notesData, tablatureData, tempo, title],
  );

  useEffect(() => {
    const element = containerRef.current;
    if (!element || !alphaTex) {
      setRenderState(alphaTex ? "idle" : "error");
      return undefined;
    }

    let disposed = false;
    element.innerHTML = "";
    setRenderState("loading");
    setRenderError(null);

    let api: AlphaTabApi | null = null;
    let offError: (() => void) | null = null;
    let offRendered: (() => void) | null = null;

    import("@coderline/alphatab")
      .then((alphaTabModule) => {
        if (disposed) return;

        api = new alphaTabModule.AlphaTabApi(element, {
          display: {
            scale: 0.92,
          },
          core: {
            enableLazyLoading: false,
            fontDirectory: "/alphatab/font/",
            useWorkers: false,
          },
          player: {
            enablePlayer: false,
          },
          notation: {
            notationMode: "GuitarPro",
          },
        });
        apiRef.current = api;

        offError = api.error.on((error) => {
          if (disposed) return;
          setRenderError(
            error.message || "alphaTab could not render this generated score.",
          );
          setRenderState("error");
        });
        offRendered = api.postRenderFinished.on(() => {
          if (disposed) return;
          setRenderState("ready");
        });

        api.tex(alphaTex.tex);
      })
      .catch((error: unknown) => {
        if (disposed) return;
        setRenderError(errorMessageOf(error, "alphaTab could not be loaded."));
        setRenderState("error");
      });

    return () => {
      disposed = true;
      offError?.();
      offRendered?.();
      api?.destroy();
      if (apiRef.current === api) {
        apiRef.current = null;
      }
    };
  }, [alphaTex]);

  if (!alphaTex || renderState === "error") {
    return (
      <>
        {renderError && (
          <div className="alphatab-fallback-note" role="status">
            alphaTab could not render this draft, so the classic viewer is
            shown.
          </div>
        )}
        {fallback}
      </>
    );
  }

  return <>{fallback}</>;
};

const DrumRhythmLane = ({
  title,
  notesData,
  tempo,
  currentTime,
}: {
  title: string;
  notesData: unknown;
  tempo?: number | null;
  currentTime: number;
}) => {
  const hits = useMemo(() => extractDrumHits(notesData), [notesData]);
  const totalDuration = useMemo(
    () => getDrumTotalDuration(notesData, hits),
    [hits, notesData],
  );
  const drumTabGrid = useMemo(
    () => buildDrumTabGrid(hits, Math.max(totalDuration, 1), tempo),
    [hits, tempo, totalDuration],
  );
  const activeTime = Number.isFinite(currentTime) ? currentTime : 0;
  const duration = Math.max(totalDuration, activeTime, 1);
  const playheadLeft = `${Math.max(0, Math.min(100, (activeTime / duration) * 100))}%`;
  const activeTabSlot =
    drumTabGrid && drumTabGrid.stepDuration > 0
      ? Math.max(
          0,
          Math.min(
            drumTabGrid.slotTimes.length - 1,
            Math.round(activeTime / drumTabGrid.stepDuration),
          ),
        )
      : -1;
  const visibleTitle =
    title && title.length > 62 ? `${title.slice(0, 59)}...` : title;

  return (
    <div
      className="drum-rhythm-frame"
      role="img"
      aria-label={`${visibleTitle} drum rhythm lane`}
    >
      <div className="drum-rhythm-header">
        <div>
          <span className="meta-label">Drum rhythm</span>
          <strong>{visibleTitle}</strong>
        </div>
        <span>{hits.length} hits</span>
      </div>
      <div className="drum-rhythm-lane">
        <div className="drum-rhythm-grid" aria-hidden="true">
          {Array.from({ length: 17 }, (_item, index) => (
            <span key={index} style={{ left: `${(index / 16) * 100}%` }} />
          ))}
        </div>
        {hits.map((hit, index) => {
          const onset = Number(hit.onset ?? 0);
          const offset = Number(hit.offset ?? onset + 0.08);
          const intensity = Math.max(
            0.08,
            Math.min(1, Number(hit.intensity ?? hit.confidence ?? 0.5)),
          );
          const isActive =
            activeTime >= onset && activeTime <= Math.max(offset, onset + 0.12);
          const left = `${Math.max(0, Math.min(100, (onset / duration) * 100))}%`;
          const height = `${32 + intensity * 88}px`;

          return (
            <span
              key={`${onset}-${index}`}
              className={`drum-hit-marker ${isActive ? "active" : ""}`}
              style={{
                left,
                height,
                opacity: 0.46 + intensity * 0.48,
              }}
              title={`${onset.toFixed(2)}s · ${Math.round(intensity * 100)}% intensity`}
            />
          );
        })}
        <span className="drum-playhead" style={{ left: playheadLeft }} />
      </div>
      <div className="drum-rhythm-footer">
        <span>0:00</span>
        <span>{formatDuration(duration)}</span>
      </div>
      <section className="drum-tabs-panel" aria-label="Drum rhythm notation">
        <div className="drum-tabs-header">
          <div>
            <span className="meta-label">Drum notation</span>
            <strong>Drum Rhythm</strong>
          </div>
          {drumTabGrid ? <span>{drumTabGrid.subdivision} grid</span> : null}
        </div>
        {drumTabGrid ? (
          <div className="drum-tabs-scroll">
            <div
              className="drum-tabs-grid"
              style={{
                gridTemplateColumns: `2.8rem repeat(${drumTabGrid.slotTimes.length}, minmax(0.72rem, 1fr))`,
              }}
            >
              {drumTabGrid.lanes.map((lane) => (
                <React.Fragment key={lane.key}>
                  <span className="drum-tabs-label">{lane.label}|</span>
                  {lane.cells.map((cell, index) => (
                    <span
                      key={`${lane.key}-${index}`}
                      className={`drum-tabs-cell ${
                        index === activeTabSlot ? "active" : ""
                      } ${index % 16 === 15 ? "measure-end" : ""}`}
                      title={`${lane.label} ${formatPlaybackTime(
                        drumTabGrid.slotTimes[index] ?? 0,
                      )}`}
                    >
                      {cell}
                    </span>
                  ))}
                </React.Fragment>
              ))}
            </div>
          </div>
        ) : (
          <p className="drum-tabs-empty">
            Not enough drum hits detected to generate rhythm notation.
          </p>
        )}
      </section>
    </div>
  );
};

void DrumRhythmLane;

const DrumTabNotation = ({
  title,
  notesData,
  tempo,
  currentTime,
  onSeek,
}: {
  title: string;
  notesData: unknown;
  tempo?: number | null;
  currentTime: number;
  onSeek: (time: number) => void;
}) => {
  const hits = useMemo(() => extractDrumHits(notesData), [notesData]);
  const totalDuration = useMemo(
    () => getDrumTotalDuration(notesData, hits),
    [hits, notesData],
  );
  const drumTabGrid = useMemo(
    () => buildDrumTabGrid(hits, Math.max(totalDuration, 1), tempo),
    [hits, tempo, totalDuration],
  );
  const drumMeasures = useMemo(
    () => (drumTabGrid ? groupDrumTabMeasures(drumTabGrid) : []),
    [drumTabGrid],
  );
  const activeTime = Number.isFinite(currentTime) ? currentTime : 0;
  const duration = Math.max(totalDuration, activeTime, 1);
  const playheadLeft = `${Math.max(0, Math.min(100, (activeTime / duration) * 100))}%`;
  const activeTabSlot =
    drumTabGrid && drumTabGrid.stepDuration > 0
      ? Math.max(
          0,
          Math.min(
            drumTabGrid.slotTimes.length - 1,
            Math.round(activeTime / drumTabGrid.stepDuration),
          ),
        )
      : -1;
  const visibleTitle =
    title && title.length > 62 ? `${title.slice(0, 59)}...` : title;

  return (
    <div
      className="drum-tab-view"
      role="img"
      aria-label={`${visibleTitle} drum rhythm`}
    >
      <div className="drum-tab-view-header">
        <div>
          <span className="meta-label">Drum notation</span>
          <strong>Drum Rhythm</strong>
        </div>
        <span>
          {hits.length} hits
          {drumTabGrid ? ` · ${drumTabGrid.subdivision} grid` : ""}
        </span>
      </div>

      {drumMeasures.length > 0 ? (
        <div className="drum-tab-measure-list">
          {drumMeasures.map((measure) => {
            const isActiveMeasure =
              activeTime >= measure.startTime && activeTime < measure.endTime;

            return (
              <section
                key={measure.measure}
                className={`drum-tab-measure timed-tab-system ${
                  isActiveMeasure ? "active" : ""
                }`}
              >
                <div className="timed-tab-measure-row" aria-hidden="true">
                  <span>M{measure.measure}</span>
                </div>
                <div
                  className="drum-tab-grid"
                  style={{
                    gridTemplateColumns: `2.6rem repeat(${
                      measure.endSlot - measure.startSlot
                    }, minmax(0.58rem, 1fr))`,
                  }}
                >
                  {measure.lanes.map((lane) => (
                    <React.Fragment key={`${measure.measure}-${lane.key}`}>
                      <span className="drum-tab-label">{lane.label}|</span>
                      {lane.cells.map((cell, cellIndex) => {
                        const absoluteSlot = measure.startSlot + cellIndex;
                        const slotTime =
                          drumTabGrid?.slotTimes[absoluteSlot] ??
                          absoluteSlot * (drumTabGrid?.stepDuration ?? 0);
                        const isActive = absoluteSlot === activeTabSlot;
                        const hasHit = cell !== "-";

                        return hasHit ? (
                          <button
                            type="button"
                            key={`${lane.key}-${absoluteSlot}`}
                            className={`drum-tab-cell active-hit ${
                              isActive ? "active" : ""
                            }`}
                            title={`${lane.label} ${formatPlaybackTime(slotTime)}`}
                            onClick={() => onSeek(slotTime)}
                          >
                            {cell}
                          </button>
                        ) : (
                          <span
                            key={`${lane.key}-${absoluteSlot}`}
                            className={`drum-tab-cell ${isActive ? "active" : ""}`}
                            title={`${lane.label} ${formatPlaybackTime(slotTime)}`}
                          >
                            {cell}
                          </span>
                        );
                      })}
                    </React.Fragment>
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      ) : (
        <p className="drum-tabs-empty">
          Not enough drum hits detected to generate rhythm notation.
        </p>
      )}

      <div className="drum-hit-overview" aria-label="Drum hit overview">
        {hits.map((hit, index) => {
          const onset = Number(hit.onset ?? 0);
          const offset = Number(hit.offset ?? onset + 0.08);
          const intensity = Math.max(
            0.08,
            Math.min(1, Number(hit.intensity ?? hit.confidence ?? 0.5)),
          );
          const isActive =
            activeTime >= onset && activeTime <= Math.max(offset, onset + 0.12);

          return (
            <span
              key={`${onset}-${index}`}
              className={`drum-hit-overview-marker ${isActive ? "active" : ""}`}
              style={{
                left: `${Math.max(0, Math.min(100, (onset / duration) * 100))}%`,
                height: `${8 + intensity * 28}px`,
              }}
              title={`${formatPlaybackTime(onset)} · ${Math.round(
                intensity * 100,
              )}% intensity`}
            />
          );
        })}
        <span
          className="drum-hit-overview-playhead"
          style={{ left: playheadLeft }}
        />
      </div>
    </div>
  );
};

const TimedTabView = ({
  tablatureData,
  notesData,
  chordsData,
  tempo,
  currentTime,
  onSeek,
}: {
  tablatureData: unknown;
  notesData: unknown;
  chordsData: unknown;
  tempo?: number | null;
  currentTime: number;
  onSeek: (time: number) => void;
}) => {
  const activeNoteRef = useRef<HTMLButtonElement | null>(null);
  const tuning = useMemo(
    () => tuningFromTablature(tablatureData),
    [tablatureData],
  );
  const labels = useMemo(() => labelsForTuning(tuning), [tuning]);
  const tabNotes = useMemo(
    () => buildTimedTabNotes(tablatureData, notesData, tempo),
    [notesData, tablatureData, tempo],
  );
  const chords = useMemo(
    () => mergeChordSegments(extractChords(chordsData)),
    [chordsData],
  );
  const activeTime = Number.isFinite(currentTime) ? currentTime : 0;
  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const measureDuration = beatDuration * 4;

  const groupedSystems = useMemo(() => {
    if (tabNotes.length === 0) return [];
    const lastOffset = Math.max(...tabNotes.map((note) => note.offset), 0);
    const measureCount = Math.max(1, Math.ceil(lastOffset / measureDuration));
    const systems: Array<{
      start: number;
      end: number;
      measures: number[];
      notes: TimedTabNote[];
      chords: ChordSegment[];
    }> = [];

    for (let measureIndex = 0; measureIndex < measureCount; measureIndex += 2) {
      const start = measureIndex * measureDuration;
      const end = Math.min(
        (measureIndex + 2) * measureDuration,
        Math.max(lastOffset, start + measureDuration),
      );
      systems.push({
        start,
        end,
        measures: [measureIndex + 1, measureIndex + 2].filter(
          (measure) => measure <= measureCount,
        ),
        notes: tabNotes.filter(
          (note) => note.startTime >= start && note.startTime < end,
        ),
        chords: chords.filter((chord) => {
          const onset = Number(chord.onset ?? 0);
          return onset >= start && onset < end;
        }),
      });
    }

    return systems;
  }, [chords, measureDuration, tabNotes]);

  const activeNoteIds = useMemo(() => {
    return activeTimedNoteIdsAt(tabNotes, activeTime);
  }, [activeTime, tabNotes]);
  const activeNoteId = activeNoteIds.values().next().value ?? null;

  useEffect(() => {
    const node = activeNoteRef.current;
    if (!node) return;
    node.scrollIntoView({
      block: "nearest",
      inline: "center",
      behavior: "smooth",
    });
  }, [activeNoteId]);

  if (tabNotes.length === 0) return null;

  const timeToLeft = (time: number, start: number, end: number) => {
    const progress = (time - start) / Math.max(end - start, 0.1);
    return `${Math.max(0, Math.min(100, progress * 100))}%`;
  };

  return (
    <div className="timed-tab-view" aria-label="Synchronized tablature">
      {groupedSystems.map((system) => {
        const isActiveSystem =
          activeTime >= system.start && activeTime <= system.end;
        const playheadLeft = timeToLeft(activeTime, system.start, system.end);

        return (
          <section
            key={`${system.start}-${system.end}`}
            className={`timed-tab-system ${isActiveSystem ? "active" : ""}`}
          >
            <div className="timed-tab-measure-row" aria-hidden="true">
              {system.measures.map((measure) => (
                <span
                  key={measure}
                  style={{ left: `${((measure - 1) % 2) * 50}%` }}
                >
                  M{measure}
                </span>
              ))}
            </div>
            <div className="timed-tab-chord-row" aria-hidden="true">
              {system.chords.map((chord, index) => {
                const rawChord = chord.chord ?? chord.chord_symbol ?? "";
                if (!rawChord || rawChord === "N") return null;
                return (
                  <span
                    key={`${rawChord}-${index}`}
                    style={{
                      left: timeToLeft(
                        Number(chord.onset ?? system.start),
                        system.start,
                        system.end,
                      ),
                    }}
                  >
                    {formatChordName(rawChord)}
                  </span>
                );
              })}
            </div>
            <div className="timed-tab-grid">
              {isActiveSystem && (
                <span
                  className="timed-tab-playhead"
                  style={{ left: playheadLeft }}
                />
              )}
              {labels.map((label, stringIndex) => (
                <div
                  className="timed-tab-string"
                  key={`${label}-${stringIndex}`}
                >
                  <span className="timed-tab-string-label">{label}</span>
                  <span className="timed-tab-string-line" />
                  {system.notes
                    .filter((note) => note.string === stringIndex + 1)
                    .map((note) => {
                      const isActive = activeNoteIds.has(note.id);
                      return (
                        <button
                          type="button"
                          key={note.id}
                          ref={isActive ? activeNoteRef : undefined}
                          className={`timed-tab-note ${isActive ? "active" : ""}`}
                          style={{
                            left: timeToLeft(
                              note.startTime,
                              system.start,
                              system.end,
                            ),
                          }}
                          onClick={() => onSeek(note.startTime)}
                          title={`Measure ${note.measure}, beat ${note.beat}, ${formatPlaybackTime(note.startTime)}`}
                          aria-label={`Seek to fret ${note.fret}, measure ${note.measure}, beat ${note.beat}`}
                        >
                          {note.fret}
                        </button>
                      );
                    })}
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
};

const hasNoteEvents = (notesData: unknown): boolean => {
  const parsed = parseJsonField(notesData);
  if (Array.isArray(parsed)) return parsed.length > 0;
  if (!isRecord(parsed)) return false;
  return (
    (Array.isArray(parsed.notes) && parsed.notes.length > 0) ||
    (Array.isArray(parsed.pitch_info) && parsed.pitch_info.length > 0)
  );
};

const getNotesError = (notesData: unknown): string | null => {
  const parsed = parseJsonField(notesData);
  if (isRecord(parsed) && typeof parsed.error === "string") {
    return parsed.error;
  }
  return null;
};

const isNonBlockingProcessingWarning = (error?: string | null): boolean =>
  Boolean(
    error?.startsWith(
      "Source separation unavailable; processed the full mix instead.",
    ),
  );

const statusLabel = (status?: string): string => {
  if (!status) return "Unknown";
  if (status === "stem_ready") return "Stem Ready";
  if (status === "completed_with_warning") return "Completed with warning";
  return status.charAt(0).toUpperCase() + status.slice(1).replace("_", " ");
};

const formatPlaybackTime = (time: number): string => {
  if (!Number.isFinite(time) || time < 0) return "0:00";
  const minutes = Math.floor(time / 60);
  const seconds = Math.floor(time % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
};

const formatDisplayDuration = (duration?: number | null): string => {
  if (!duration || !Number.isFinite(duration)) return "0:00";
  const totalSeconds = Math.max(0, Math.round(duration));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
};

const formatCompletedAt = (dateValue?: string | null): string => {
  if (!dateValue) return "May 20, 2025 • 10:24 AM";
  const date = new Date(dateValue);
  if (Number.isNaN(date.getTime())) return "May 20, 2025 • 10:24 AM";
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  })
    .format(date)
    .replace(" at ", " • ");
};

const errorMessageOf = (error: unknown, fallback: string): string => {
  if (isRecord(error)) {
    const response = error.response;
    if (
      isRecord(response) &&
      isRecord(response.data) &&
      typeof response.data.detail === "string"
    ) {
      return response.data.detail;
    }
    if (typeof error.message === "string") {
      return error.message;
    }
  }
  return fallback;
};

const TranscriptionViewer: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [transcription, setTranscription] = useState<Transcription | null>(
    null,
  );
  const [instrumentTracks, setInstrumentTracks] = useState<InstrumentTrack[]>(
    [],
  );
  const [selectedTrackView, setSelectedTrackView] =
    useState<SelectedTrackView>("global");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentPlaybackTime, setCurrentPlaybackTime] = useState<number>(0);
  const [playbackDuration, setPlaybackDuration] = useState(0);
  const [playbackVolume, setPlaybackVolume] = useState(0.74);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [isSpeedMenuOpen, setIsSpeedMenuOpen] = useState(false);
  const [waveformPeaks, setWaveformPeaks] = useState<number[]>([]);
  const [notationZoomLevel, setNotationZoomLevel] = useState<number>(1.0);
  const [scoreViewMode, setScoreViewMode] = useState<"score" | "tab">("score");
  const [isRetryingTranscription, setIsRetryingTranscription] = useState(false);
  const [isGeneratingTab, setIsGeneratingTab] = useState(false);
  const [isGeneratingLyrics, setIsGeneratingLyrics] = useState(false);
  const [lyricsLanguage, setLyricsLanguage] =
    useState<LyricsLanguage>("auto");
  const [generationStatus, setGenerationStatus] = useState<string | null>(null);
  const [generationMessage, setGenerationMessage] = useState<string | null>(
    null,
  );
  const [reprocessingTrackId, setReprocessingTrackId] = useState<number | null>(
    null,
  );
  const audioElementRef = useRef<HTMLAudioElement | null>(null);
  const lyricSegmentRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const generateTabPollingRef = useRef<NodeJS.Timeout | null>(null);
  const trackReprocessPollingRef = useRef<NodeJS.Timeout | null>(null);
  const isGeneratingTabRef = useRef(false);
  const isGeneratingLyricsRef = useRef(false);
  const scoreStageRef = useRef<HTMLDivElement | null>(null);
  const navigate = useNavigate();
  const { token } = useAuth();

  const fetchTranscription = useCallback(
    async (id: number) => {
      try {
        setLoading(true);
        setError(null);
        if (!token) {
          throw new Error("Authentication error. Please log in again.");
        }

        const [result, tracks] = await Promise.all([
          audioService.getTranscriptionResult(id, token),
          audioService.listInstrumentTracks(id, token).catch(() => []),
        ]);
        setTranscription(result);
        setInstrumentTracks(tracks);
        setSelectedTrackView((current) => {
          const selectedStemTrack = tracks.find(
            (track) =>
              track.instrument_type ===
              selectedStemInstrument(result.selected_stem),
          );
          if (selectedStemTrack) return selectedStemTrack.id;
          if (tracks.length > 0 && current === "global") return tracks[0].id;
          return tracks.some((track) => track.id === current)
            ? current
            : "global";
        });
        setLoading(false);
      } catch (err: unknown) {
        setError(errorMessageOf(err, "Failed to load transcription"));
        setLoading(false);
      }
    },
    [token],
  );

  useEffect(() => {
    let cancelled = false;

    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        queueMicrotask(() => {
          if (!cancelled) {
            fetchTranscription(idNum);
          }
        });
      } else {
        queueMicrotask(() => {
          if (!cancelled) {
            setError("Invalid transcription ID");
            setLoading(false);
          }
        });
      }
    } else {
      queueMicrotask(() => {
        if (!cancelled) {
          setError("No transcription ID provided");
          setLoading(false);
        }
      });
    }

    return () => {
      cancelled = true;
    };
  }, [fetchTranscription, transcriptionId]);

  const selectedTrack = useMemo(
    () =>
      instrumentTracks.find((track) => track.id === selectedTrackView) ?? null,
    [instrumentTracks, selectedTrackView],
  );

  const refreshInstrumentTracks = useCallback(
    async (transcriptionIdValue: number) => {
      if (!token) return;
      const tracks = await audioService.listInstrumentTracks(
        transcriptionIdValue,
        token,
      );
      setInstrumentTracks(tracks);
      setSelectedTrackView((current) => {
        const selectedStemTrack = tracks.find(
          (track) =>
            track.instrument_type ===
            selectedStemInstrument(transcription?.selected_stem),
        );
        if (selectedStemTrack) return selectedStemTrack.id;
        return tracks.some((track) => track.id === current)
          ? current
          : (tracks[0]?.id ?? "global");
      });
    },
    [token, transcription?.selected_stem],
  );

  const stopGenerateTabPolling = useCallback((reason: string) => {
    if (generateTabPollingRef.current) {
      clearInterval(generateTabPollingRef.current);
      generateTabPollingRef.current = null;
    }
    console.log("polling enabled/disabled state", {
      enabled: false,
      reason,
    });
  }, []);

  const stopTrackReprocessPolling = useCallback((reason: string) => {
    if (trackReprocessPollingRef.current) {
      clearInterval(trackReprocessPollingRef.current);
      trackReprocessPollingRef.current = null;
    }
    console.log("track reprocess polling enabled/disabled state", {
      enabled: false,
      reason,
    });
  }, []);

  const startTrackReprocessPolling = useCallback(
    (transcriptionIdValue: number, trackId: number) => {
      if (!token) return;
      stopTrackReprocessPolling("restart track reprocess polling");
      console.log("track reprocess polling enabled/disabled state", {
        enabled: true,
        transcriptionId: transcriptionIdValue,
        trackId,
      });

      trackReprocessPollingRef.current = setInterval(async () => {
        try {
          const tracks = await audioService.listInstrumentTracks(
            transcriptionIdValue,
            token,
          );
          setInstrumentTracks(tracks);

          const currentTrack = tracks.find((track) => track.id === trackId);
          if (!currentTrack || currentTrack.processing_status === "processing") {
            return;
          }

          setReprocessingTrackId(null);
          stopTrackReprocessPolling("track reprocess completed");
          try {
            const result = await audioService.getTranscriptionResult(
              transcriptionIdValue,
              token,
            );
            setTranscription(result);
          } catch (resultErr) {
            console.warn(
              "Could not refresh transcription after track reprocess:",
              resultErr,
            );
          }
        } catch (pollErr) {
          console.warn("Track reprocess polling error:", pollErr);
        }
      }, 2000);
    },
    [stopTrackReprocessPolling, token],
  );

  const startGenerateTabPolling = useCallback(
    (transcriptionIdValue: number, mode: "tabs" | "rhythm" | "lyrics") => {
      if (!token) return;
      stopGenerateTabPolling("restart generation polling");
      console.log("polling enabled/disabled state", {
        enabled: true,
        transcriptionId: transcriptionIdValue,
      });

      generateTabPollingRef.current = setInterval(async () => {
        try {
          const result = await audioService.getTranscriptionResult(
            transcriptionIdValue,
            token,
          );
          const fetchedStatus = result.processing_status;
          const fetchedLyricsStatus = lyricStatusOf(result);
          const fetchedGenerationStatus = generationStatusForMode(result, mode);
          const isLyrics = mode === "lyrics";
          console.log("latest fetched transcription status", {
            transcriptionId: transcriptionIdValue,
            status: fetchedStatus,
            lyricsStatus: fetchedLyricsStatus,
            generationStatus: fetchedGenerationStatus,
            processing_error: result.processing_error,
          });

          const hasError = isLyrics
            ? fetchedLyricsStatus === "failed"
            : isGenerationFailedStatus(fetchedGenerationStatus);
          if (hasError) {
            setTranscription(result);
            setIsGeneratingTab(false);
            setIsGeneratingLyrics(false);
            isGeneratingTabRef.current = false;
            isGeneratingLyricsRef.current = false;
            setGenerationStatus(null);
            setGenerationMessage(null);
            if (!isLyrics) {
              setError(
                mode === "rhythm"
                  ? "Failed to generate rhythm from this stem"
                  : "Failed to generate tab from this stem",
              );
            }
            stopGenerateTabPolling("generation failed");
            return;
          }

          const isTerminalSuccess = isLyrics
            ? fetchedLyricsStatus === "completed" ||
              fetchedLyricsStatus === "completed_with_warning"
            : isGenerationCompleteStatus(fetchedGenerationStatus);
          if (isTerminalSuccess) {
            setTranscription(result);
            setIsGeneratingTab(false);
            setIsGeneratingLyrics(false);
            isGeneratingTabRef.current = false;
            isGeneratingLyricsRef.current = false;
            setGenerationStatus(null);
            setGenerationMessage(null);
            stopGenerateTabPolling("generation completed");
            if (!isLyrics) {
              void refreshInstrumentTracks(transcriptionIdValue);
            }
            return;
          }

          if (
            isGeneratingLyricsRef.current &&
            fetchedLyricsStatus === "processing"
          ) {
            setTranscription(result);
            return;
          }

          if (
            isGeneratingTabRef.current &&
            isGenerationInProgressStatus(fetchedGenerationStatus)
          ) {
            setTranscription(result);
            return;
          }

          setTranscription(result);
        } catch (pollErr) {
          console.warn("Polling error:", pollErr);
        }
      }, 2000);
    },
    [refreshInstrumentTracks, stopGenerateTabPolling, token],
  );

  useEffect(
    () => () => {
      stopGenerateTabPolling("transcription viewer unmounted");
      stopTrackReprocessPolling("transcription viewer unmounted");
    },
    [stopGenerateTabPolling, stopTrackReprocessPolling],
  );

  useEffect(() => {
    if (!transcription?.id || generateTabPollingRef.current) return;

    const shouldResumeTabs = isTabsGenerating(transcription);
    const shouldResumeRhythm = isRhythmGenerating(transcription);
    if (!shouldResumeTabs && !shouldResumeRhythm) return;

    isGeneratingTabRef.current = true;
    setIsGeneratingTab(true);
    setGenerationStatus(
      shouldResumeRhythm ? "Generating rhythm..." : "Generating tabs...",
    );
    setGenerationMessage("Generation is still in progress.");
    startGenerateTabPolling(
      transcription.id,
      shouldResumeRhythm ? "rhythm" : "tabs",
    );
  }, [startGenerateTabPolling, transcription]);

  const activeScoreSource: ActiveScoreSource | null = useMemo(() => {
    if (!transcription) return null;
    if (selectedTrack) {
      return {
        id: selectedTrack.id,
        title: `${transcription.title} - ${selectedTrack.display_name}`,
        label: selectedTrack.display_name,
        instrumentType: selectedTrack.instrument_type,
        tablatureData: selectedTrack.tab_json,
        notesData: selectedTrack.notes_json,
        chordsData: selectedTrack.chords_json,
        notationData: selectedTrack.notation_json,
        processingStatus: selectedTrack.processing_status,
        confidenceScore: selectedTrack.confidence_score,
        confidenceNotes: selectedTrack.confidence_notes,
        hasStemAudio: trackHasStemAudio(transcription, selectedTrack),
        isGlobal: false,
      };
    }

    return {
      id: "global",
      title: transcription.title,
      label: selectedStemLabel(transcription.selected_stem),
      instrumentType: selectedStemInstrument(transcription.selected_stem),
      tablatureData: transcription.tablature_data,
      notesData: transcription.notes_data,
      chordsData: transcription.chords_data,
      notationData: transcription.notation_data,
      processingStatus:
        transcription.processing_status ??
        (transcription.is_processed ? "completed" : "processing"),
      confidenceScore: null,
      confidenceNotes: null,
      hasStemAudio:
        hasUsableBlob(transcription.separated_audio_url) ||
        hasUsableBlob(transcription.separated_audio_file_path),
      isGlobal: true,
    };
  }, [selectedTrack, transcription]);

  const audioSrc = useMemo(() => {
    if (!transcription || !activeScoreSource) return null;

    if (!activeScoreSource.isGlobal && selectedTrack) {
      const directTrackAudio = audioService.resolvePlayableAudioUrl(
        selectedTrack.stem_audio_path,
      );
      if (directTrackAudio) return directTrackAudio;
      if (
        selectedTrack.instrument_type ===
          selectedStemInstrument(transcription.selected_stem) &&
        audioService.resolvePlayableAudioUrl(transcription.separated_audio_url)
      ) {
        return audioService.resolvePlayableAudioUrl(
          transcription.separated_audio_url,
        );
      }
      return transcription.separated_audio_url || null;
    }

    return transcription.separated_audio_url || null;
  }, [activeScoreSource, selectedTrack, transcription]);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    const loadAudio = async () => {
      if (!transcription?.id) {
        setAudioUrl(null);
        return;
      }

      try {
        setAudioError(null);
        setAudioUrl(null);
        setCurrentPlaybackTime(0);
        setPlaybackDuration(0);
        setIsPlaying(false);
        console.info(
          "viewer_audio_source transcription_id=%s separated=%s",
          transcription.id,
          transcription.separated_audio_url ?? null,
        );

        const playableAudioUrl = audioService.resolvePlayableAudioUrl(audioSrc);
        if (playableAudioUrl) {
          setAudioUrl(playableAudioUrl);
          return;
        }

        if (!token || !activeScoreSource?.hasStemAudio) {
          setAudioError(audioSrc ? null : "Audio file not available");
          return;
        }

        if (activeScoreSource.isGlobal) {
          setAudioError("Separated stem audio file not available");
          return;
        }

        const blob = await audioService.getInstrumentTrackStem(
          transcription.id,
          Number(activeScoreSource.id),
          token,
        );

        if (cancelled) return;
        objectUrl = window.URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      } catch (err: unknown) {
        if (cancelled) return;
        setAudioUrl(null);
        setAudioError(
          errorMessageOf(
            err,
            activeScoreSource?.isGlobal
              ? "Source audio file not available"
              : "Instrument stem audio file not available",
          ),
        );
      }
    };

    loadAudio();

    return () => {
      cancelled = true;
      if (objectUrl) {
        window.URL.revokeObjectURL(objectUrl);
      }
    };
  }, [
    activeScoreSource,
    audioSrc,
    token,
    transcription?.audio_file_path,
    transcription?.id,
    transcription?.original_audio_url,
    transcription?.separated_audio_file_path,
    transcription?.separated_audio_url,
  ]);

  useEffect(() => {
    const audio = audioElementRef.current;
    if (!audio) return;

    audio.volume = playbackVolume;
    audio.playbackRate = playbackRate;
  }, [playbackRate, playbackVolume]);

  useEffect(() => {
    const audio = audioElementRef.current;
    if (!audio) return;

    const handleLoadedMetadata = () => {
      setPlaybackDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
      setCurrentPlaybackTime(audio.currentTime);
      setAudioError(null);
    };
    const syncCurrentTime = () => {
      setCurrentPlaybackTime(audio.currentTime);
    };
    const handleEnded = () => {
      setIsPlaying(false);
      setCurrentPlaybackTime(
        Number.isFinite(audio.duration) ? audio.duration : audio.currentTime,
      );
    };
    const handleError = () => {
      const src = audio.currentSrc || audio.src || audioUrl || "";
      setIsPlaying(false);
      console.error("Audio element failed to load", {
        src,
        mediaError: mediaErrorDetails(audio),
      });
      void probeAudioNetwork(src);
      setAudioError("Audio file could not be loaded.");
    };

    audio.addEventListener("loadedmetadata", handleLoadedMetadata);
    audio.addEventListener("timeupdate", syncCurrentTime);
    audio.addEventListener("seeking", syncCurrentTime);
    audio.addEventListener("seeked", syncCurrentTime);
    audio.addEventListener("ended", handleEnded);
    audio.addEventListener("error", handleError);
    audio.load();

    return () => {
      audio.removeEventListener("loadedmetadata", handleLoadedMetadata);
      audio.removeEventListener("timeupdate", syncCurrentTime);
      audio.removeEventListener("seeking", syncCurrentTime);
      audio.removeEventListener("seeked", syncCurrentTime);
      audio.removeEventListener("ended", handleEnded);
      audio.removeEventListener("error", handleError);
    };
  }, [audioUrl]);

  useEffect(() => {
    if (!isPlaying) return undefined;

    let frameId = 0;
    const syncFromAudio = () => {
      const audio = audioElementRef.current;
      if (audio) {
        setCurrentPlaybackTime(audio.currentTime);
        if (Number.isFinite(audio.duration) && audio.duration > 0) {
          setPlaybackDuration(audio.duration);
        }
      }
      frameId = window.requestAnimationFrame(syncFromAudio);
    };

    frameId = window.requestAnimationFrame(syncFromAudio);
    return () => window.cancelAnimationFrame(frameId);
  }, [isPlaying]);

  // Clean up generation polling interval on unmount
  useEffect(() => {
    return () => {
      // Note: The polling interval is cleaned up in the handleGenerateTab function
      // This effect is just a safety net in case the component unmounts unexpectedly
      // while polling is active
    };
  }, []);

  useEffect(() => {
    if (!audioUrl) {
      queueMicrotask(() => setWaveformPeaks([]));
      return undefined;
    }

    const controller = new AbortController();
    let disposed = false;

    const buildPeaks = async () => {
      try {
        const response = await fetch(audioUrl, { signal: controller.signal });
        const buffer = await response.arrayBuffer();
        const context = new AudioContext();
        const decoded = await context.decodeAudioData(buffer.slice(0));
        const data = decoded.getChannelData(0);
        const barCount = 58;
        const samplesPerBar = Math.max(1, Math.floor(data.length / barCount));
        const peaks = Array.from({ length: barCount }, (_item, barIndex) => {
          const start = barIndex * samplesPerBar;
          const end = Math.min(data.length, start + samplesPerBar);
          let sum = 0;
          for (let sampleIndex = start; sampleIndex < end; sampleIndex += 1) {
            sum += Math.abs(data[sampleIndex]);
          }
          return Math.max(
            0.12,
            Math.min(1, (sum / Math.max(1, end - start)) * 5.5),
          );
        });
        await context.close();
        if (!disposed) setWaveformPeaks(peaks);
      } catch {
        if (!disposed) {
          setWaveformPeaks(
            Array.from(
              { length: 58 },
              (_item, index) => 0.32 + ((index * 13) % 42) / 70,
            ),
          );
        }
      }
    };

    buildPeaks();

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [audioUrl]);

  const seekPlaybackTo = useCallback(
    (nextTime: number) => {
      const audio = audioElementRef.current;
      const duration =
        Number.isFinite(playbackDuration) && playbackDuration > 0
          ? playbackDuration
          : Number.isFinite(audio?.duration)
            ? Number(audio?.duration)
            : nextTime;
      const boundedTime = Math.max(0, Math.min(nextTime, duration));

      if (audio) {
        audio.currentTime = boundedTime;
      }
      setCurrentPlaybackTime(boundedTime);
    },
    [playbackDuration],
  );

  const lyricsData = useMemo(
    () => parseLyricsData(transcription?.lyrics_data),
    [transcription?.lyrics_data],
  );
  const lyricsSegments = useMemo(
    () => (Array.isArray(lyricsData?.segments) ? lyricsData.segments : []),
    [lyricsData?.segments],
  );
  const activeLyricsSegmentIndex = useMemo(() => {
    if (lyricsSegments.length === 0 || !Number.isFinite(currentPlaybackTime)) {
      return -1;
    }

    return lyricsSegments.findIndex((segment, index) => {
      const start = lyricSegmentTime(segment.start);
      if (start === null || currentPlaybackTime < start) return false;

      const end = lyricSegmentTime(segment.end);
      if (end !== null) return currentPlaybackTime <= end;

      const nextStart = lyricSegmentTime(lyricsSegments[index + 1]?.start);
      return nextStart === null || currentPlaybackTime < nextStart;
    });
  }, [currentPlaybackTime, lyricsSegments]);

  useEffect(() => {
    if (activeLyricsSegmentIndex < 0) return;

    const activeSegment = lyricsSegments[activeLyricsSegmentIndex];
    const activeKey = activeSegment
      ? lyricSegmentKey(activeSegment, activeLyricsSegmentIndex)
      : null;
    const activeElement = activeKey
      ? lyricSegmentRefs.current[activeKey]
      : null;
    activeElement?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [activeLyricsSegmentIndex, lyricsSegments]);

  const handleHeaderPlayPause = async () => {
    const audio = audioElementRef.current;
    if (!audioUrl || !audio) return;

    if (isPlaying) {
      audio.pause();
      setIsPlaying(false);
      return;
    }

    try {
      await audio.play();
      setIsPlaying(true);
      setAudioError(null);
    } catch (error: unknown) {
      const src = audio.currentSrc || audio.src || audioUrl;
      setIsPlaying(false);
      console.error("Audio playback could not start", {
        src,
        playError: errorMessageOf(error, "HTMLMediaElement.play() failed"),
        mediaError: mediaErrorDetails(audio),
      });
      void probeAudioNetwork(src);
      setAudioError("Audio playback could not start.");
    }
  };

  const handleHeroSeek = (event: React.MouseEvent<HTMLButtonElement>) => {
    if (playbackDuration <= 0) return;

    const rect = event.currentTarget.getBoundingClientRect();
    const progress = Math.min(
      1,
      Math.max(0, (event.clientX - rect.left) / rect.width),
    );
    seekPlaybackTo(progress * playbackDuration);
  };

  const handleVolumeChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const volume = Number(event.target.value);
    setPlaybackVolume(volume);
    if (audioElementRef.current) {
      audioElementRef.current.volume = volume;
    }
  };

  const playbackRateOptions = [0.5, 0.75, 1, 1.25, 1.5, 2];

  const handlePlaybackRateSelect = (rate: number) => {
    setPlaybackRate(rate);
    setIsSpeedMenuOpen(false);
    if (audioElementRef.current) {
      audioElementRef.current.playbackRate = rate;
    }
  };

  const handleCopyLink = async () => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(window.location.href);
        return;
      }
      const input = document.createElement("textarea");
      input.value = window.location.href;
      input.setAttribute("readonly", "true");
      input.style.position = "fixed";
      input.style.opacity = "0";
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      input.remove();
    } catch {
      setAudioError("Could not copy the transcription link.");
    }
  };

  const handleFullscreenScore = async () => {
    const stage = scoreStageRef.current;
    if (!stage) return;

    try {
      if (document.fullscreenElement) {
        await document.exitFullscreen();
      } else {
        await stage.requestFullscreen();
      }
    } catch {
      setAudioError("Fullscreen is not available in this browser.");
    }
  };

  const handleDownload = async (format: "midi" | "musicxml" | "tab") => {
    if (!token || !transcription?.id || !activeScoreSource) return;

    try {
      const trackId = activeScoreSource.isGlobal
        ? undefined
        : Number(activeScoreSource.id);
      const blob = await audioService.downloadExport(
        transcription.id,
        format,
        token,
        trackId,
      );
      const extension = format === "midi" ? "mid" : format;
      const scope = activeScoreSource.isGlobal
        ? "full_mix"
        : exportSlug(
            activeScoreSource.instrumentType || activeScoreSource.label,
          );
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `transcription_${transcription.id}_${scope}.${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(
        errorMessageOf(
          err,
          `Failed to download ${format.toUpperCase()} export`,
        ),
      );
    }
  };

  const handleReprocessSelectedTrack = async () => {
    if (!token || !transcription?.id || !selectedTrack) return;

    try {
      setError(null);
      setReprocessingTrackId(selectedTrack.id);
      const updatedTrack = await audioService.reprocessInstrumentTrack(
        transcription.id,
        selectedTrack.id,
        token,
      );
      setInstrumentTracks((current) =>
        current.map((track) =>
          track.id === updatedTrack.id ? updatedTrack : track,
        ),
      );
      startTrackReprocessPolling(transcription.id, updatedTrack.id);
    } catch (err: unknown) {
      setError(errorMessageOf(err, "Failed to reprocess instrument track"));
      setReprocessingTrackId(null);
    }
  };

  const handleRetryTranscription = async () => {
    if (!token || !transcription?.id || transcription.is_demo) return;

    // Prevent multiple concurrent retries
    if (isRetryingTranscription) return;

    try {
      setError(null);
      setIsRetryingTranscription(true);
      await audioService.generateTab(transcription.id, token, {
        sensitivity: "high",
      });
      // Note: We don't navigate to processing screen here to stay on the transcription viewer
      // The generation completion will be handled by the existing polling mechanism in handleGenerateTab
      // or we could refactor to share logic, but for now we just update the transcription state
      const result = await audioService.getTranscriptionResult(
        transcription.id,
        token,
      );
      setTranscription(result);
    } catch (err: unknown) {
      setError(
        errorMessageOf(
          err,
          "Failed to retry tab generation with higher sensitivity",
        ),
      );
    } finally {
      setIsRetryingTranscription(false);
    }
  };

  const handleGenerateTab = async () => {
    if (!token || !transcription?.id || transcription.is_demo) return;

    // Prevent multiple concurrent generations
    if (
      isGeneratingTab ||
      isTabsGenerating(transcription) ||
      isRhythmGenerating(transcription)
    ) {
      return;
    }

    const isRhythm = transcription.selected_stem === "drums";
    const nextGenerationStatus = isRhythm
      ? "Generating rhythm..."
      : "Generating tabs...";
    console.log("generate tabs clicked", {
      transcriptionId: transcription.id,
      selectedStem: transcription.selected_stem,
    });
    stopGenerateTabPolling("new generate tabs request");
    setGenerationStatus(nextGenerationStatus);
    setGenerationMessage(
      isRhythm ? "Rhythm generation started." : "Tab generation started.",
    );
    setIsGeneratingTab(true);
    isGeneratingTabRef.current = true;
    setError(null);

    try {
      const response = await audioService.generateTab(transcription.id, token);
      console.log("API response", response);
      setGenerationMessage(
        response.message ??
          (isRhythm ? "Rhythm generation started." : "Tab generation started."),
      );
      setTranscription((current) =>
        current
          ? {
              ...current,
              is_processed: false,
              processing_error: null,
              processing_status: "processing",
              tab_generation_status: isRhythm
                ? current.tab_generation_status
                : "processing",
              rhythm_generation_status: isRhythm
                ? "processing"
                : current.rhythm_generation_status,
            }
          : current,
      );
      console.log("updated local status", {
        transcriptionId: transcription.id,
        status: "processing",
        message: response.message ?? "Tab generation started.",
      });
      startGenerateTabPolling(transcription.id, isRhythm ? "rhythm" : "tabs");
    } catch (err: unknown) {
      setError(
        errorMessageOf(
          err,
          transcription.selected_stem === "drums"
            ? "Failed to generate rhythm from this stem"
            : "Failed to generate tab from this stem",
        ),
      );
      setIsGeneratingTab(false);
      isGeneratingTabRef.current = false;
      setGenerationStatus(null);
      setGenerationMessage(null);
      stopGenerateTabPolling("generate tabs request failed");
    }
  };

  const handleGenerateLyrics = async () => {
    if (!token || !transcription?.id || transcription.is_demo) return;
    if (isGeneratingLyrics) return;

    stopGenerateTabPolling("new generate lyrics request");
    setGenerationStatus("Generating lyrics...");
    setGenerationMessage("Lyrics generation started.");
    setIsGeneratingLyrics(true);
    isGeneratingLyricsRef.current = true;
    setError(null);

    try {
      const response = await audioService.generateLyrics(
        transcription.id,
        token,
        { language: lyricsLanguage },
      );
      setGenerationMessage(response.message ?? "Lyrics generation started.");
      setTranscription((current) =>
        current
          ? {
              ...current,
              lyrics_generation_status: "processing",
              processing_error: null,
            }
          : current,
      );
      startGenerateTabPolling(transcription.id, "lyrics");
    } catch (err: unknown) {
      setError(errorMessageOf(err, "Failed to generate lyrics from this stem"));
      setIsGeneratingLyrics(false);
      isGeneratingLyricsRef.current = false;
      setGenerationStatus(null);
      setGenerationMessage(null);
      stopGenerateTabPolling("generate lyrics request failed");
    }
  };

  const handleViewExampleTab = async () => {
    if (!token) return;
    try {
      const demo = await audioService.getDemoTranscription(token);
      navigate(`/transcription/${demo.id}`);
    } catch (err: unknown) {
      setError(errorMessageOf(err, "Demo transcription is not available."));
    }
  };

  if (loading) {
    return (
      <div className="transcription-viewer-container transcription-viewer-fallback">
        <div className="transcription-viewer-content">
          <div className="loading-spinner"></div>
          <h2>Loading transcription</h2>
          <p>Preparing your score, tabs, and playback workspace.</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="transcription-viewer-container transcription-viewer-fallback">
        <div className="transcription-viewer-content">
          <h2>Error loading transcription</h2>
          <div className="alert alert-error">{error}</div>
          <div className="transcription-actions">
            <button
              className="button-secondary"
              onClick={() => navigate("/dashboard")}
            >
              Return to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!transcription) {
    return (
      <div className="transcription-viewer-container transcription-viewer-fallback">
        <div className="transcription-viewer-content">
          <h2>Transcription not found</h2>
          <div className="alert alert-error">
            Transcription not found or you don't have access to it.
          </div>
          <div className="transcription-actions">
            <button
              className="button-secondary"
              onClick={() => navigate("/dashboard")}
            >
              Return to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  const scoreSource = activeScoreSource;
  const transcriptionMetadata = buildTranscriptionMetadata(
    transcription,
    instrumentTracks,
  );
  const asciiTab = buildAsciiTab(
    scoreSource?.tablatureData,
    scoreSource?.chordsData,
  );
  const selectedTrackNotesError = scoreSource?.isGlobal
    ? null
    : getNotesError(scoreSource?.notesData);
  const notesError = scoreSource?.isGlobal
    ? isNonBlockingProcessingWarning(transcription.processing_error)
      ? getNotesError(transcription.notes_data)
      : transcription.processing_error ||
        getNotesError(transcription.notes_data)
    : selectedTrackNotesError;
  const globalAsciiTab = buildAsciiTab(
    transcription.tablature_data,
    transcription.chords_data,
  );
  const globalNoteEventsAvailable = hasNoteEvents(transcription.notes_data);
  const selectedTrackNoteEventsAvailable = hasNoteEvents(
    scoreSource?.notesData,
  );
  const availableExports = transcription.available_exports ?? [];
  const selectedTrackMidiXmlExportSupported = Boolean(
    scoreSource?.isGlobal ||
    ["guitar", "bass"].includes(
      scoreSource?.instrumentType.toLowerCase() ?? "",
    ),
  );
  const selectedTrackTabExportSupported = Boolean(
    scoreSource?.isGlobal ||
    ["guitar", "bass"].includes(
      scoreSource?.instrumentType.toLowerCase() ?? "",
    ),
  );
  const selectedTrackIsDrums =
    scoreSource?.instrumentType.toLowerCase() === "drums";
  const selectedTrackHasDrumHits =
    extractDrumHits(scoreSource?.notesData).length > 0;
  const selectedTrackReprocessSupported = Boolean(
    selectedTrack &&
    ["guitar", "bass", "drums", "vocals"].includes(
      selectedTrack.instrument_type.toLowerCase(),
    ),
  );
  const canReprocessSelectedTrack = Boolean(
    selectedTrackReprocessSupported &&
    selectedTrack?.processing_status !== "processing",
  );
  const canDownloadMidi = Boolean(
    !availableExports.includes("midi")
      ? false
      : scoreSource?.isGlobal
        ? hasUsableBlob(transcription.midi_file_path) ||
          globalNoteEventsAvailable
        : selectedTrackMidiXmlExportSupported &&
          selectedTrackNoteEventsAvailable,
  );
  const canDownloadMusicXml = Boolean(
    !availableExports.includes("musicxml")
      ? false
      : scoreSource?.isGlobal
        ? hasUsableBlob(transcription.notation_data) ||
          globalNoteEventsAvailable
        : selectedTrackMidiXmlExportSupported &&
          (hasUsableBlob(scoreSource?.notationData) ||
            selectedTrackNoteEventsAvailable),
  );
  const canDownloadTab = Boolean(
    !availableExports.includes("tab")
      ? false
      : scoreSource?.isGlobal
        ? globalAsciiTab.length > 0 || globalNoteEventsAvailable
        : selectedTrackTabExportSupported &&
          (asciiTab.length > 0 || selectedTrackNoteEventsAvailable),
  );
  const hasTrackOptions = instrumentTracks.length > 1;
  const selectedTrackHasScore =
    asciiTab.length > 0 ||
    selectedTrackNoteEventsAvailable ||
    hasUsableBlob(scoreSource?.notationData);
  const scoreGenerationAllowed = transcription.can_generate_score !== false;
  const canGenerateScore = Boolean(
    scoreSource &&
    ((scoreGenerationAllowed && selectedTrackHasScore) ||
      (selectedTrackIsDrums &&
        transcription.output_mode === "rhythm" &&
        selectedTrackHasDrumHits)),
  );
  const displayedAsciiTab = asciiTab || globalAsciiTab;
  const canShowTabView = displayedAsciiTab.length > 0;
  const activeScoreViewMode = canShowTabView ? scoreViewMode : "score";
  const scoreControlsAvailable = canGenerateScore && !selectedTrackIsDrums;
  const isDemoTranscription = Boolean(transcription.is_demo);
  const backendTabsGenerating = isTabsGenerating(transcription);
  const backendRhythmGenerating = isRhythmGenerating(transcription);
  const isGeneratingTabsView =
    isGeneratingTab || backendTabsGenerating || backendRhythmGenerating;
  const selectedTrackProcessing =
    scoreSource?.processingStatus === "processing" ||
    (selectedTrack !== null && reprocessingTrackId === selectedTrack.id);
  const isTrackReprocessingView =
    selectedTrackProcessing && !isGeneratingTabsView;
  const lyricsGenerationStatus = lyricStatusOf(transcription);
  const hasLyricsData = Boolean(lyricsData);
  const hasLyricsSegments = lyricsSegments.length > 0;
  const lyricsProcessing =
    isGeneratingLyrics || lyricsGenerationStatus === "processing";
  const lyricsCompleted =
    lyricsGenerationStatus === "completed" && hasLyricsData;
  const showGenerateLyricsButton =
    !lyricsProcessing &&
    !lyricsCompleted &&
    (!lyricsData ||
      ["pending", "failed", "completed_with_warning"].includes(
        lyricsGenerationStatus,
      ));
  const selectedStemReady =
    transcription.processing_status === "stem_ready" && !isGeneratingTabsView;
  const hasStemPlayback =
    transcription.can_play_stem !== false &&
    Boolean(
      transcription.separated_audio_url ||
      transcription.separated_audio_file_path ||
      selectedTrack?.stem_audio_path ||
      audioSrc,
    );
  const isVocalStemReady =
    selectedStemReady && transcription.selected_stem === "vocals";
  const vocalLyricsAvailable = transcription.selected_stem === "vocals";
  const tabStemSupported =
    transcription.selected_stem === "other" ||
    transcription.selected_stem === "bass";
  const rhythmStemSupported = transcription.selected_stem === "drums";
  const canGenerateTabs = Boolean(
    selectedStemReady &&
    hasStemPlayback &&
    tabStemSupported &&
    !isDemoTranscription,
  );
  const canGenerateRhythm = Boolean(
    selectedStemReady &&
    hasStemPlayback &&
    rhythmStemSupported &&
    transcription.can_generate_rhythm !== false &&
    !isDemoTranscription,
  );
  const generateTabAllowed = canGenerateTabs || canGenerateRhythm;
  const generateTabLabel =
    transcription.selected_stem === "drums"
      ? "Generate Rhythm (Experimental)"
      : "Generate Tabs (Experimental)";
  const generatingTitle =
    transcription.selected_stem === "drums"
      ? "Generating rhythm..."
      : "Generating tabs...";
  const generatingDetails =
    transcription.selected_stem === "drums"
      ? "Creating rhythm data from the isolated drum stem..."
      : "Creating tabs and score from the isolated stem...";
  const stemReadyMessage = isVocalStemReady
    ? "Vocal stem is ready for playback. Generate lyrics when you want a timestamped transcription."
    : transcription.selected_stem === "drums"
      ? "Drum stem is ready. Listen first, then generate rhythm if the stem sounds useful."
      : "Stem is ready. Listen first, then generate tabs if the stem sounds useful.";
  const displayedProcessingStatus = isGeneratingTabsView
    ? "processing"
    : selectedTrackProcessing
      ? "processing"
    : transcription.processing_status === "completed_with_warning"
      ? "completed_with_warning"
      : transcription.processing_status === "failed" ||
          scoreSource?.processingStatus === "failed"
        ? "failed"
        : (scoreSource?.processingStatus ?? "completed");
  const displayedStatusLabel = isGeneratingTabsView
    ? generationStatus || generatingTitle
    : selectedTrackProcessing
      ? "Reprocessing track"
    : transcription.processing_status === "completed_with_warning"
      ? "Stem Ready"
      : statusLabel(displayedProcessingStatus);
  const playbackProgress =
    playbackDuration > 0
      ? Math.min(1, Math.max(0, currentPlaybackTime / playbackDuration))
      : 0;
  const rawProjectTitle = transcription.title || "Untitled transcription";
  const titleWithoutExtension = rawProjectTitle.replace(
    /\.(mp3|wav|m4a|aac|flac)$/i,
    "",
  );
  const subtitleMatch = titleWithoutExtension.match(/\(([^)]+)\)\s*$/);
  const displayProjectTitle =
    (subtitleMatch
      ? titleWithoutExtension.slice(0, subtitleMatch.index).trim()
      : titleWithoutExtension) || rawProjectTitle;
  const displayProjectSubtitle = subtitleMatch ? `(${subtitleMatch[1]})` : null;
  const displayDuration = formatDisplayDuration(
    transcriptionMetadata.durationSeconds || transcription.duration,
  );
  const displayTempo = transcription.detected_tempo
    ? `${transcription.detected_tempo} BPM`
    : "Not detected";
  const displayHeaderTempo = transcription.detected_tempo
    ? `${transcription.detected_tempo}`
    : "—";
  const displayKey = transcription.detected_key || "D# major";
  const completedAt = formatCompletedAt(
    transcription.updated_at ?? transcription.created_at,
  );
  const sourceFileName = transcription.audio_file_path?.split(/[\\/]/).pop();
  const sourceLabel = transcription.audio_file_path
    ? isDemoTranscription
      ? "Bundled example stem"
      : "Loaded from upload"
    : transcription.youtube_url
      ? "Loaded from YouTube"
      : isDemoTranscription
        ? "Bundled example stem"
        : "Source not attached";
  const sourceSummary = isDemoTranscription
    ? "Example guitar riff"
    : sourceFileName ||
      (transcription.youtube_url
        ? "YouTube audio"
        : transcriptionMetadata.sourceLabel);
  const playbackSourceLabel = audioSrc
    ? transcriptionMetadata.sourceLabel
    : isDemoTranscription
      ? "Demo audio missing"
      : transcriptionMetadata.sourceLabel;
  const selectedTrackLabel =
    selectedTrack?.display_name ?? transcriptionMetadata.stemLabel;
  const selectedInstrumentLabel = selectedTrack
    ? displayInstrumentName(selectedTrack.instrument_type)
    : transcriptionMetadata.instrumentLabel;
  const selectedTuningLabel = transcriptionMetadata.tuningLabel;
  const capabilityBadges =
    transcriptionMetadata.outputBadges.length > 0
      ? transcriptionMetadata.outputBadges
      : ["PLAYBACK ONLY"];
  const heroWaveformPeaks =
    waveformPeaks.length > 0
      ? waveformPeaks
      : Array.from(
          { length: 72 },
          (_item, index) => 0.32 + ((index * 13) % 42) / 70,
        );
  const transcriptionInfoMessage =
    transcription.selected_stem === "other"
      ? "Guitar may be grouped with piano, synths, or accompaniment in the 'other' stem."
      : transcription.warning_message || transcriptionMetadata.description;
  return (
    <div className="transcription-viewer-container transcription-premium-page">
      <section
        className="premium-transcription-card"
        aria-label="Transcription result"
      >
        <header className="premium-project-hero">
          <div className="hero-line-art" aria-hidden="true" />
          <div className="premium-title-block">
            <h1>{displayProjectTitle}</h1>
            {displayProjectSubtitle && <p>{displayProjectSubtitle}</p>}
            <div className="premium-hero-chips" aria-label="Project metadata">
              <span>
                <Music2 aria-hidden="true" />
                <small>Key</small>
                <strong>{displayKey}</strong>
              </span>
              <span>
                <SlidersHorizontal aria-hidden="true" />
                <small>Tempo</small>
                <strong>{displayHeaderTempo} BPM</strong>
              </span>
              <span>
                <CheckCircle2 aria-hidden="true" />
                <small>Duration</small>
                <strong>{displayDuration}</strong>
              </span>
            </div>
            <div
              className="premium-stem-summary"
              aria-label="Selected stem metadata"
            >
              <span>
                <Music2 aria-hidden="true" />
                <small>Selected Stem</small>
                <strong>{transcriptionMetadata.stemLabel}</strong>
              </span>
              <span>
                <SlidersHorizontal aria-hidden="true" />
                <small>Instrument</small>
                <strong>{selectedInstrumentLabel}</strong>
              </span>
              <span>
                <FileDown aria-hidden="true" />
                <small>Output</small>
                <strong>{transcriptionMetadata.outputLabel}</strong>
              </span>
            </div>
            <div
              className="premium-capability-badges"
              aria-label="Output capability badges"
            >
              <span
                className={`premium-source-badge stem-tone-${transcriptionMetadata.tone}`}
              >
                {transcriptionMetadata.sourceBadge}
              </span>
              {capabilityBadges.map((badge) => (
                <span className="premium-completed-badge" key={badge}>
                  {badge}
                </span>
              ))}
            </div>
          </div>
          <div className="premium-hero-audio">
            <div className="premium-hero-audio-primary">
              <div className="premium-audio-transport">
                <button
                  type="button"
                  className={`premium-play-button ${isPlaying ? "playing" : ""}`}
                  aria-label={
                    isPlaying ? "Pause stem playback" : "Play stem playback"
                  }
                  disabled={!audioUrl}
                  onClick={handleHeaderPlayPause}
                >
                  {isPlaying ? (
                    <Pause aria-hidden="true" fill="currentColor" />
                  ) : (
                    <Play aria-hidden="true" fill="currentColor" />
                  )}
                </button>
                <button
                  type="button"
                  className={`premium-waveform premium-waveform-button ${isPlaying ? "playing" : ""}`}
                  aria-label="Seek playback"
                  disabled={!audioUrl || playbackDuration <= 0}
                  onClick={handleHeroSeek}
                  style={
                    {
                      "--progress": `${playbackProgress * 100}%`,
                    } as React.CSSProperties
                  }
                >
                  <i className="premium-waveform-playhead" aria-hidden="true" />
                  {heroWaveformPeaks.map((peak, index) => (
                    <span
                      key={index}
                      className={
                        (index + 1) / heroWaveformPeaks.length <=
                        playbackProgress
                          ? "played"
                          : ""
                      }
                      style={
                        {
                          "--bar": `${Math.round(14 + peak * 56)}px`,
                        } as React.CSSProperties
                      }
                    />
                  ))}
                </button>
              </div>
              <div className="premium-source-line">
                <span className="premium-time-display">
                  {formatPlaybackTime(currentPlaybackTime)} /{" "}
                  {formatPlaybackTime(playbackDuration)}
                </span>
                <span
                  className="premium-source-filename"
                  title={playbackSourceLabel}
                >
                  {playbackSourceLabel}
                </span>
              </div>
            </div>
            <div
              className="premium-playback-metadata"
              aria-label="Playback metadata"
            >
              <span>
                <Play aria-hidden="true" /> <small>Playback</small>
                <strong>{transcriptionMetadata.playbackLabel}</strong>
              </span>
              <span>
                <Waves aria-hidden="true" /> <small>Track</small>
                <strong>{selectedTrackLabel}</strong>
              </span>
              {transcriptionMetadata.isMultiTrack && (
                <span>
                  <SlidersHorizontal aria-hidden="true" /> <small>Tracks</small>
                  <strong>{transcriptionMetadata.trackCount}</strong>
                </span>
              )}
              <span>
                <Music2 aria-hidden="true" /> <small>Instrument</small>
                <strong>{selectedInstrumentLabel}</strong>
              </span>
              {selectedTuningLabel && (
                <span>
                  <SlidersHorizontal aria-hidden="true" /> <small>Tuning</small>
                  <strong>Standard Guitar ({selectedTuningLabel})</strong>
                </span>
              )}
              <span>
                <Volume2 aria-hidden="true" /> <small>Volume</small>
                <strong>{Math.round(playbackVolume * 100)}%</strong>
              </span>
              <span>
                <CheckCircle2 aria-hidden="true" /> <small>Speed</small>
                <strong>{playbackRate}x</strong>
              </span>
            </div>
            <div className="premium-hero-audio-controls">
              <label>
                <span>Volume</span>
                <input
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  value={playbackVolume}
                  onChange={handleVolumeChange}
                  disabled={!audioUrl}
                />
              </label>
              <div
                className="premium-speed-control"
                onBlur={(event) => {
                  if (!event.currentTarget.contains(event.relatedTarget)) {
                    setIsSpeedMenuOpen(false);
                  }
                }}
              >
                <span>Speed</span>
                <button
                  type="button"
                  className="premium-speed-trigger"
                  aria-haspopup="listbox"
                  aria-expanded={isSpeedMenuOpen}
                  disabled={!audioUrl}
                  onClick={() => setIsSpeedMenuOpen((open) => !open)}
                >
                  {playbackRate}x
                  <ChevronDown aria-hidden="true" />
                </button>
                {isSpeedMenuOpen && (
                  <div
                    className="premium-speed-menu"
                    role="listbox"
                    aria-label="Playback speed"
                  >
                    {playbackRateOptions.map((rate) => (
                      <button
                        type="button"
                        key={rate}
                        role="option"
                        aria-selected={playbackRate === rate}
                        className={playbackRate === rate ? "active" : ""}
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => handlePlaybackRateSelect(rate)}
                      >
                        {rate}x
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </header>

        <div className="premium-transcription-body">
          <section
            className="premium-info-section"
            aria-labelledby="audio-source-heading"
          >
            <h2 id="audio-source-heading">Audio Source</h2>
            <div className="premium-horizontal-card">
              <span className="premium-card-icon">
                <Waves aria-hidden="true" />
              </span>
              <div>
                <strong>{transcriptionMetadata.sourceLabel}</strong>
                <span>
                  {sourceLabel} - {sourceSummary}
                </span>
              </div>
              {isDemoTranscription && (
                <span className="premium-completed-badge premium-confidence-badge">
                  Example
                </span>
              )}
              {!isDemoTranscription && (
                <button
                  type="button"
                  className="premium-light-button"
                  onClick={() => navigate("/upload")}
                >
                  <FolderOpen aria-hidden="true" /> Change file
                </button>
              )}
            </div>
          </section>

          <section
            className="premium-info-callout"
            aria-label="Transcription information"
          >
            <Info aria-hidden="true" />
            <p>{transcriptionInfoMessage}</p>
          </section>

          {isGeneratingTabsView && (
            <section
              className="premium-stem-review-panel"
              aria-label="Tab generation"
            >
              <div>
                <span
                  className={`premium-source-badge stem-tone-${transcriptionMetadata.tone}`}
                >
                  {transcriptionMetadata.stemLabel}
                </span>
                <strong>{displayProjectTitle}</strong>
                <p>{generationMessage || "Tab generation started."}</p>
              </div>
              <div>
                <button
                  type="button"
                  className="button-primary premium-generate-tab-button"
                  disabled
                >
                  <FileDown aria-hidden="true" />
                  {generationStatus || generatingTitle}
                </button>
                <p className="generation-status-subtitle">
                  {generationStatus || generatingTitle}
                  <span className="generation-status-details">
                    {generatingDetails}
                  </span>
                </p>
              </div>
            </section>
          )}

          {selectedStemReady && (
            <section
              className="premium-stem-review-panel"
              aria-label="Stem review"
            >
              <div>
                <span
                  className={`premium-source-badge stem-tone-${transcriptionMetadata.tone}`}
                >
                  {transcriptionMetadata.stemLabel}
                </span>
                <strong>{displayProjectTitle}</strong>
                <p>{stemReadyMessage}</p>
              </div>
              {generateTabAllowed && (
                <div>
                  <button
                    type="button"
                    className="button-primary premium-generate-tab-button"
                    onClick={handleGenerateTab}
                    disabled={isGeneratingTab}
                  >
                    <FileDown aria-hidden="true" />
                    {isGeneratingTab
                      ? generationStatus || "Starting..."
                      : generateTabLabel}
                  </button>
                  {generationStatus && (
                    <p className="generation-status-subtitle">
                      {generationStatus}
                      <span className="generation-status-details">
                        {generatingDetails}
                      </span>
                    </p>
                  )}
                </div>
              )}
              {isVocalStemReady && !isDemoTranscription && (
                <div className="premium-lyrics-generate-controls">
                  {lyricsProcessing && (
                    <button
                      type="button"
                      className="button-primary premium-generate-tab-button"
                      disabled
                    >
                      <Mic aria-hidden="true" />
                      Generating lyrics...
                    </button>
                  )}
                  {lyricsCompleted && (
                    <span className="premium-completed-badge premium-lyrics-generated-badge">
                      <CheckCircle2 aria-hidden="true" />
                      Lyrics generated
                    </span>
                  )}
                  {showGenerateLyricsButton && (
                    <>
                      <label className="premium-lyrics-language-field">
                        <span>Lyrics language</span>
                        <select
                          value={lyricsLanguage}
                          onChange={(event) =>
                            setLyricsLanguage(
                              event.target.value as LyricsLanguage,
                            )
                          }
                        >
                          {lyricsLanguageOptions.map((option) => (
                            <option key={option.value} value={option.value}>
                              {option.label}
                            </option>
                          ))}
                        </select>
                      </label>
                      {lyricsLanguage === "auto" && (
                        <p className="premium-lyrics-language-helper">
                          Best for songs with mixed languages.
                        </p>
                      )}
                      <button
                        type="button"
                        className="button-primary premium-generate-tab-button"
                        onClick={handleGenerateLyrics}
                      >
                        <Mic aria-hidden="true" />
                        Transcribe Lyrics
                      </button>
                    </>
                  )}
                  {lyricsProcessing && (
                    <p className="generation-status-subtitle">
                      Generating lyrics...
                      <span className="generation-status-details">
                        Transcribing the separated vocal stem locally.
                      </span>
                    </p>
                  )}
                </div>
              )}
            </section>
          )}

          {vocalLyricsAvailable &&
            (lyricsData ||
              lyricsProcessing ||
              lyricsGenerationStatus === "failed") && (
              <section
                className="premium-info-section premium-lyrics-section"
                aria-labelledby="lyrics-heading"
              >
                <h2 id="lyrics-heading">Lyrics</h2>
                <div className="premium-lyrics-panel">
                  {lyricsData && (
                    <div className="premium-lyrics-meta">
                      <span>
                        Requested:{" "}
                        {lyricsLanguageLabel(lyricsData.requested_language)}
                      </span>
                      {lyricsData.language && (
                        <span>
                          Detected: {lyricsLanguageLabel(lyricsData.language)}
                        </span>
                      )}
                    </div>
                  )}
                  {lyricsProcessing ? (
                    <p className="premium-lyrics-status">
                      Generating lyrics...
                    </p>
                  ) : lyricsGenerationStatus === "failed" ? (
                    <div className="alert alert-error">
                      {transcription.processing_error ||
                        "Lyrics generation failed. Please try again with a clearer vocal stem."}
                    </div>
                  ) : hasLyricsSegments ? (
                    <>
                      <div
                        className="premium-lyrics-segments"
                        aria-label="Timestamped lyrics"
                      >
                        {lyricsSegments.map((segment, index) => {
                          const key = lyricSegmentKey(segment, index);
                          const isActive = index === activeLyricsSegmentIndex;

                          return (
                            <button
                              type="button"
                              key={key}
                              ref={(element) => {
                                lyricSegmentRefs.current[key] = element;
                              }}
                              className={isActive ? "is-active" : undefined}
                              aria-current={isActive ? "true" : undefined}
                              onClick={() => seekPlaybackTo(segment.start ?? 0)}
                            >
                              <span>
                                {lyricTime(segment.start)}
                                {segment.end !== undefined
                                  ? ` - ${lyricTime(segment.end)}`
                                  : ""}
                              </span>
                              <strong>
                                {segment.text?.trim() ||
                                  "Untitled lyric segment"}
                              </strong>
                            </button>
                          );
                        })}
                      </div>
                      {lyricsData?.text && (
                        <details className="premium-lyrics-transcript">
                          <summary>View full transcript</summary>
                          <pre className="premium-lyrics-text">
                            {lyricsData.text}
                          </pre>
                        </details>
                      )}
                    </>
                  ) : lyricsData?.text ? (
                    <pre className="premium-lyrics-text">{lyricsData.text}</pre>
                  ) : (
                    <p className="premium-lyrics-status">
                      {lyricsData?.message ||
                        "No clear vocals detected for lyrics generation."}
                    </p>
                  )}
                  {lyricsData && (
                    <p className="premium-lyrics-correction-note">
                      Lyrics may need correction when vocals are unclear,
                      layered, or mixed with backing vocals.
                    </p>
                  )}
                </div>
              </section>
            )}

          <section
            className="premium-info-section"
            aria-labelledby="transcription-status-heading"
          >
            <h2 id="transcription-status-heading">Transcription Status</h2>
            <div className="premium-horizontal-card premium-status-card">
              <span className="premium-check-icon">
                <CheckCircle2 aria-hidden="true" />
              </span>
              <strong>
                {scoreSource?.label ?? transcriptionMetadata.sourceLabel}
              </strong>
              <div className="premium-status-badge-row">
                <span
                  className={`premium-completed-badge status-${displayedProcessingStatus}`}
                >
                  {displayedStatusLabel}
                </span>
                {capabilityBadges.map((badge) => (
                  <span
                    className="premium-completed-badge"
                    key={`status-${badge}`}
                  >
                    {badge}
                  </span>
                ))}
                {hasConfidenceScore(scoreSource?.confidenceScore) && (
                  <span className="premium-completed-badge premium-confidence-badge">
                    {Math.round(Number(scoreSource?.confidenceScore))}%
                    confidence
                  </span>
                )}
              </div>
              <span className="premium-completed-date">
                Completed on {completedAt}
              </span>
            </div>
          </section>

          {(scoreSource?.confidenceNotes ||
            transcription.warning_message ||
            audioError ||
            (canGenerateScore && notesError)) && (
            <div className="premium-warning-stack">
              {scoreSource?.confidenceNotes && (
                <div className="alert alert-error">
                  {scoreSource.confidenceNotes}
                </div>
              )}
              {transcription.warning_message &&
                transcription.warning_message !==
                  scoreSource?.confidenceNotes && (
                  <div className="alert alert-error">
                    {transcription.warning_message}
                  </div>
                )}
              {audioError && (
                <div className="alert alert-error">{audioError}</div>
              )}
              {canGenerateScore && notesError && (
                <div className="alert alert-error">
                  {scoreSource?.instrumentType.toLowerCase() === "drums"
                    ? `Drum rhythm analysis did not produce usable hits: ${notesError}`
                    : `Pitch analysis did not produce usable notes: ${notesError}`}
                </div>
              )}
            </div>
          )}

          {!selectedStemReady && (
            <section
              className="premium-score-workspace"
              aria-label="Score viewer"
            >
              <aside className="premium-score-sidebar">
                {scoreControlsAvailable && (
                  <div
                    className="premium-view-tabs"
                    role="tablist"
                    aria-label="Score mode"
                  >
                    <button
                      type="button"
                      className={
                        activeScoreViewMode === "score" ? "active" : ""
                      }
                      role="tab"
                      aria-selected={activeScoreViewMode === "score"}
                      onClick={() => setScoreViewMode("score")}
                    >
                      <Music2 aria-hidden="true" /> Score
                    </button>
                    {canShowTabView && (
                      <button
                        type="button"
                        className={
                          activeScoreViewMode === "tab" ? "active" : ""
                        }
                        role="tab"
                        aria-selected={activeScoreViewMode === "tab"}
                        onClick={() => setScoreViewMode("tab")}
                      >
                        <SlidersHorizontal aria-hidden="true" /> Tab
                      </button>
                    )}
                  </div>
                )}

                {hasTrackOptions && (
                  <div
                    className="premium-track-list"
                    aria-label="Instrument tracks"
                  >
                    <span className="premium-sidebar-label">Tracks</span>
                    {instrumentTracks.map((track) => {
                      const isActive = selectedTrackView === track.id;
                      return (
                        <button
                          type="button"
                          key={track.id}
                          className={isActive ? "active" : ""}
                          onClick={() => setSelectedTrackView(track.id)}
                        >
                          {track.display_name}
                        </button>
                      );
                    })}
                  </div>
                )}

                {scoreControlsAvailable && (
                  <>
                    <span className="premium-sidebar-label">Zoom</span>
                    <div className="premium-sidebar-zoom">
                      <button
                        type="button"
                        onClick={() =>
                          setNotationZoomLevel(
                            Math.max(notationZoomLevel - 0.25, 0.5),
                          )
                        }
                        aria-label="Zoom out"
                      >
                        -
                      </button>
                      <span>{Math.round(notationZoomLevel * 100)}%</span>
                      <button
                        type="button"
                        onClick={() =>
                          setNotationZoomLevel(
                            Math.min(notationZoomLevel + 0.25, 3.0),
                          )
                        }
                        aria-label="Zoom in"
                      >
                        +
                      </button>
                    </div>
                  </>
                )}
                {selectedTrack &&
                  selectedTrackReprocessSupported &&
                  !isDemoTranscription && (
                    <button
                      type="button"
                      className="premium-reprocess-link"
                      onClick={handleReprocessSelectedTrack}
                      disabled={
                        !canReprocessSelectedTrack ||
                        reprocessingTrackId === selectedTrack.id
                      }
                    >
                      {reprocessingTrackId === selectedTrack.id
                        ? "Queuing..."
                        : "Reprocess track"}
                    </button>
                  )}
              </aside>

              <div className="premium-score-stage" ref={scoreStageRef}>
                {scoreControlsAvailable && (
                  <button
                    type="button"
                    className="premium-fullscreen-button"
                    aria-label="Fullscreen score"
                    onClick={handleFullscreenScore}
                  >
                    <Expand aria-hidden="true" />
                  </button>
                )}
                <div className="score-viewer premium-score-viewer">
                  {scoreSource &&
                  canGenerateScore &&
                  activeScoreViewMode === "tab" &&
                  canShowTabView ? (
                    <TimedTabView
                      tablatureData={scoreSource.tablatureData}
                      notesData={scoreSource.notesData}
                      chordsData={scoreSource.chordsData}
                      tempo={transcription.detected_tempo}
                      currentTime={currentPlaybackTime}
                      onSeek={seekPlaybackTo}
                    />
                  ) : scoreSource &&
                    canGenerateScore &&
                    selectedTrackIsDrums ? (
                    <DrumTabNotation
                      title={scoreSource.title}
                      notesData={scoreSource.notesData}
                      tempo={transcription.detected_tempo}
                      currentTime={currentPlaybackTime}
                      onSeek={seekPlaybackTo}
                    />
                  ) : scoreSource &&
                    canGenerateScore &&
                    selectedTrackHasScore ? (
                    <div
                      className="score-sheet-zoom"
                      style={{
                        transform: `scale(${notationZoomLevel})`,
                        transformOrigin: "top left",
                        width: `${100 / notationZoomLevel}%`,
                      }}
                    >
                      <AlphaTabScore
                        title={scoreSource.title}
                        tempo={transcription.detected_tempo ?? undefined}
                        tablatureData={scoreSource.tablatureData}
                        notesData={scoreSource.notesData}
                        instrumentType={scoreSource.instrumentType}
                        fallback={
                          <ScoreSheet
                            title={scoreSource.title}
                            tempo={transcription.detected_tempo ?? undefined}
                            detectedKey={
                              transcription.detected_key ?? undefined
                            }
                            currentTime={currentPlaybackTime}
                            tablatureData={scoreSource.tablatureData}
                            notesData={scoreSource.notesData}
                            chordsData={scoreSource.chordsData}
                            instrumentType={scoreSource.instrumentType}
                            onSeek={seekPlaybackTo}
                          />
                        }
                      />
                    </div>
                  ) : (
                    <div className="premium-inline-empty-state">
                      <strong>
                        {isTrackReprocessingView
                          ? "Reprocessing track..."
                          : isGeneratingTabsView
                          ? generationStatus || generatingTitle
                          : selectedStemReady
                            ? "Stem playback is ready for review."
                            : transcriptionMetadata.capabilities.playback
                              ? "Stem playback is available, but no reliable notes were detected for this stem."
                              : "No note events detected for this stem."}
                      </strong>
                      <p>
                        {isTrackReprocessingView
                          ? "Analyzing this stem again. The score will refresh when processing finishes."
                          : isGeneratingTabsView
                          ? generatingDetails
                          : selectedStemReady
                            ? stemReadyMessage
                            : transcription.selected_stem === "drums"
                              ? "This stem currently supports rhythm playback only when drum hits are detected."
                              : transcription.selected_stem === "vocals"
                                ? "Vocal stem playback is available. Vocal notation is planned for a future release."
                                : "No note events were detected for the selected stem."}
                      </p>
                      <div className="premium-inline-empty-actions">
                        {generateTabAllowed && (
                          <div>
                            <button
                              type="button"
                              className="button-primary"
                              onClick={handleGenerateTab}
                              disabled={isGeneratingTab}
                            >
                              <FileDown aria-hidden="true" />
                              {isGeneratingTab
                                ? generationStatus || "Starting..."
                                : generateTabLabel}
                            </button>
                            {generationStatus && (
                              <p className="generation-status-subtitle">
                                {generationStatus}
                                <span className="generation-status-details">
                                  {generatingDetails}
                                </span>
                              </p>
                            )}
                          </div>
                        )}
                        {!isDemoTranscription &&
                          !selectedStemReady &&
                          !isGeneratingTabsView &&
                          !isTrackReprocessingView && (
                            <button
                              type="button"
                              className="button-primary"
                              onClick={handleRetryTranscription}
                              disabled={isRetryingTranscription}
                            >
                              {isRetryingTranscription
                                ? "Retrying..."
                                : "Retry with higher sensitivity"}
                            </button>
                          )}
                        {!isDemoTranscription && (
                          <button
                            type="button"
                            className="button-secondary"
                            onClick={handleViewExampleTab}
                          >
                            View example TAB
                          </button>
                        )}
                        <button
                          type="button"
                          className="button-secondary"
                          onClick={() => navigate("/upload")}
                        >
                          Choose another stem
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </section>
          )}
        </div>
      </section>

      <audio
        ref={audioElementRef}
        src={audioUrl ?? undefined}
        preload="metadata"
        className="premium-hidden-audio"
      />
      <div className="transcription-footer premium-bottom-bar">
        <div className="transcription-meta">
          <div className="meta-item">
            <span className="meta-label">Duration</span>
            <span className="meta-value">{displayDuration}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Tempo</span>
            <span className="meta-value">{displayTempo}</span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Key</span>
            <span className="meta-value">{displayKey}</span>
          </div>
        </div>

        <div className="transcription-actions">
          <button
            className="button-secondary"
            onClick={() => navigate("/dashboard")}
          >
            Dashboard
          </button>
          <button
            type="button"
            className="premium-icon-only"
            aria-label="Copy link"
            onClick={handleCopyLink}
          >
            <LinkIcon aria-hidden="true" />
          </button>
          {availableExports.length > 0 && (
            <>
              {availableExports.includes("midi") && (
                <button
                  className="button-secondary premium-download-button"
                  onClick={() => handleDownload("midi")}
                  disabled={!canDownloadMidi}
                >
                  <Download aria-hidden="true" /> MIDI
                </button>
              )}
              {availableExports.includes("musicxml") && (
                <button
                  className="button-secondary premium-download-button"
                  onClick={() => handleDownload("musicxml")}
                  disabled={!canDownloadMusicXml}
                >
                  <FileDown aria-hidden="true" /> MusicXML
                </button>
              )}
              {availableExports.includes("tab") && (
                <button
                  className="button-secondary premium-download-button"
                  onClick={() => handleDownload("tab")}
                  disabled={!canDownloadTab}
                >
                  <Download aria-hidden="true" /> TAB
                </button>
              )}
            </>
          )}
          {!transcription.is_processed && (
            <button
              className="button-secondary"
              onClick={() => {
                // Refetch transcription status
                fetchTranscription(transcription.id);
              }}
            >
              Refresh Status
            </button>
          )}
        </div>
      </div>
    </div>
  );
};

export default TranscriptionViewer;
