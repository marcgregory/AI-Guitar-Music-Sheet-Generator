import React, { useState, useEffect, useMemo, useRef, useCallback } from "react";
import type { AlphaTabApi } from "@coderline/alphatab";
import audioService from "../services/audioService";
import type { InstrumentTrack, Transcription } from "../services/audioService";
import { useNavigate, useParams } from "react-router-dom";
import AudioPlayer from "./AudioPlayer";
import { useAuth } from "./auth/AuthContext";
import {
  CheckCircle2,
  Download,
  Expand,
  FileDown,
  FolderOpen,
  Link as LinkIcon,
  Music2,
  Play,
  SlidersHorizontal,
  Waves,
} from "lucide-react";

type TablatureNote = {
  string?: number;
  fret?: number;
  onset?: number;
  offset?: number;
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

type AlphaTexBuildResult = {
  tex: string;
  truncated: boolean;
  renderedBars: number;
};

type SelectedTrackView = "global" | number;

type StemAudioState = {
  url: string | null;
  error: string | null;
  loading: boolean;
};

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
  if (isRecord(parsed) && Array.isArray(parsed.tuning) && parsed.tuning.length > 0) {
    return parsed.tuning.map(Number).filter((note: number) => Number.isFinite(note));
  }
  return [40, 45, 50, 55, 59, 64];
};

const labelsForTuning = (tuning: number[]): string[] => {
  if (tuning.length === 4) return ["G", "D", "A", "E"];
  return ["e", "B", "G", "D", "A", "E"].slice(0, Math.max(1, tuning.length));
};

const midiNoteToAlphaTexPitch = (midiNote: number): string => {
  const noteNames = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const roundedNote = Math.round(midiNote);
  const noteName = noteNames[((roundedNote % 12) + 12) % 12];
  const octave = Math.floor(roundedNote / 12) - 1;
  return `${noteName}${octave}`;
};

const escapeAlphaTexText = (value: string): string =>
  value.replace(/\\/g, "\\\\").replace(/"/g, "\\\"");

const displayInstrumentName = (instrumentType: string): string => {
  if (!instrumentType) return "Track";
  return instrumentType.charAt(0).toUpperCase() + instrumentType.slice(1).replace("_", " ");
};

const exportSlug = (value: string): string =>
  value.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "track";

const buildAsciiTab = (tablatureData: unknown, chordsData: unknown): string => {
  const parsed = parseJsonField(tablatureData);
  const notes: TablatureNote[] = isRecord(parsed) && Array.isArray(parsed.tablature)
    ? parsed.tablature as TablatureNote[]
    : [];
  const parsedChords = parseJsonField(chordsData);
  const chords: ChordSegment[] = isRecord(parsedChords) && Array.isArray(parsedChords.chords)
    ? parsedChords.chords as ChordSegment[]
    : isRecord(parsedChords) && Array.isArray(parsedChords.chord_charts)
      ? parsedChords.chord_charts as ChordSegment[]
      : [];

  if (notes.length === 0) return "";

  const maxOffset = Math.max(
    ...notes.map((note) => Number(note.offset ?? note.onset ?? 0)),
    0.1,
  );
  const blockTime = 0.1;
  const columnsPerBlock = 2;
  const totalColumns = Math.max(24, Math.ceil(maxOffset / blockTime) * columnsPerBlock);
  const tuning = tuningFromTablature(tablatureData);
  const labels = labelsForTuning(tuning);
  const rows = labels.map(() => Array(totalColumns).fill("-"));
  const chordRow = Array(totalColumns).fill(" ");

  notes.forEach((note) => {
    const stringNumber = Number(note.string);
    const fret = Number(note.fret);
    const onset = Number(note.onset ?? 0);
    if (!Number.isFinite(stringNumber) || stringNumber < 1 || stringNumber > labels.length) return;
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

const extractTabNotes = (tablatureData: unknown): ScoreNote[] => {
  const parsed = parseJsonField(tablatureData);
  return isRecord(parsed) && Array.isArray(parsed.tablature) ? parsed.tablature as ScoreNote[] : [];
};

const extractChords = (chordsData: unknown): ChordSegment[] => {
  const parsed = parseJsonField(chordsData);
  if (isRecord(parsed) && Array.isArray(parsed.chords)) return parsed.chords as ChordSegment[];
  if (isRecord(parsed) && Array.isArray(parsed.chord_charts)) return parsed.chord_charts as ChordSegment[];
  return [];
};

const pitchFromTabNote = (note: TablatureNote, tuning: number[] = [40, 45, 50, 55, 59, 64]) => {
  const stringNumber = Number(note.string);
  const fret = Number(note.fret);
  if (!Number.isFinite(stringNumber) || !Number.isFinite(fret)) return undefined;
  if (stringNumber < 1 || stringNumber > tuning.length || fret < 0) return undefined;
  return tuning[tuning.length - stringNumber] + fret;
};

const buildScoreNotes = (tablatureData: unknown, notesData: unknown): ScoreNote[] => {
  const tabNotes = extractTabNotes(tablatureData);
  const noteEvents = extractNoteEvents(notesData);
  const tuning = tuningFromTablature(tablatureData);

  if (tabNotes.length === 0) {
    return noteEvents
      .map((note) => ({
        ...note,
        pitch: Number(note.pitch),
      }))
      .filter((note) => Number.isFinite(Number(note.onset)) && Number.isFinite(Number(note.pitch)));
  }

  return tabNotes
    .map((tabNote) => {
      const onset = Number(tabNote.onset ?? 0);
      const matchingEvent = noteEvents.find((event) => {
        const eventOnset = Number(event.onset ?? 0);
        return Math.abs(eventOnset - onset) < 0.03;
      });

      return {
        ...tabNote,
        pitch: Number(matchingEvent?.pitch ?? pitchFromTabNote(tabNote, tuning)),
      };
    })
    .filter((note) => Number.isFinite(Number(note.onset)) && Number.isFinite(Number(note.fret)));
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
  const sixteenthDuration = (60 / safeTempo) / 4;
  const maxSlots = 3072;
  const slotMap = new Map<number, string[]>();
  let highestSlot = 0;

  notes.forEach((note) => {
    const slot = Math.max(0, Math.round(Number(note.onset ?? 0) / sixteenthDuration));
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

  const slotCount = Math.min(maxSlots, Math.max(16, Math.ceil((highestSlot + 1) / 16) * 16));
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

const prepareDisplayNotes = (notes: ScoreNote[], tempo?: number): DisplayScoreNote[] => {
  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const gridSize = Math.max(0.08, beatDuration / 4);
  const bestBySlot = new Map<string, DisplayScoreNote>();

  notes.forEach((note) => {
    const onset = Number(note.onset ?? 0);
    const stringNumber = Number(note.string);
    const pitch = Number(note.pitch);
    if (!Number.isFinite(onset)) return;
    if (!Number.isFinite(stringNumber) && !Number.isFinite(pitch)) return;

    const slot = Math.round(onset / gridSize);
    const displayOnset = slot * gridSize;
    const key = `${slot}:${Number.isFinite(stringNumber) ? `s${stringNumber}` : `p${pitch}`}`;
    const candidate = { ...note, displayOnset };
    const existing = bestBySlot.get(key);
    if (!existing || confidenceOf(candidate.confidence) >= confidenceOf(existing.confidence)) {
      bestBySlot.set(key, candidate);
    }
  });

  return Array.from(bestBySlot.values()).sort(
    (a, b) => a.displayOnset - b.displayOnset || Number(a.string ?? a.pitch ?? 0) - Number(b.string ?? b.pitch ?? 0),
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

      if (last && lastRaw === rawChord && Number(chord.onset ?? 0) - Number(last.offset ?? last.onset ?? 0) < 0.18) {
        last.offset = Math.max(Number(last.offset ?? 0), Number(chord.offset ?? chord.onset ?? 0));
        last.confidence = Math.max(confidenceOf(last.confidence), confidenceOf(chord.confidence));
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
  let start = Math.max(0, Math.floor(notes[0].displayOnset / measureDuration) * measureDuration);
  let current: DisplayScoreNote[] = [];

  notes.forEach((note) => {
    const onset = note.displayOnset;
    const isFull = current.length >= maxNotesPerSystem;
    const isTooWide = onset - start >= maxDurationPerSystem && current.length > 0;
    if (isFull || isTooWide) {
      const end = Math.max(start + measureDuration, current[current.length - 1].displayOnset + beatDuration);
      systems.push({
        start,
        end,
        measureStarts: [],
        notes: current,
        chords: [],
      });
      start = Math.max(0, Math.floor(onset / measureDuration) * measureDuration);
      current = [];
    }
    current.push(note);
  });

  if (current.length > 0) {
    const end = Math.max(start + measureDuration, current[current.length - 1].displayOnset + beatDuration);
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
      { length: Math.max(2, Math.ceil((end - system.start) / measureDuration) + 1) },
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
}: {
  title: string;
  tempo?: number;
  detectedKey?: string;
  currentTime: number;
  tablatureData: unknown;
  notesData: unknown;
  chordsData: unknown;
  instrumentType: string;
}) => {
  const frameRef = useRef<HTMLDivElement>(null);
  const systemRefs = useRef<Array<SVGGElement | null>>([]);
  const tuning = useMemo(() => tuningFromTablature(tablatureData), [tablatureData]);
  const hasTablature = useMemo(() => extractTabNotes(tablatureData).length > 0, [tablatureData]);
  const stringCount = Math.max(1, tuning.length);
  const scoreNotes = useMemo(
    () => prepareDisplayNotes(buildScoreNotes(tablatureData, notesData), tempo),
    [tablatureData, notesData, tempo],
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

  useEffect(() => {
    if (activeSystemIndex < 0) return;

    const activeSystem = systemRefs.current[activeSystemIndex];
    const scrollContainer = frameRef.current?.closest(".score-viewer");
    if (!activeSystem || !(scrollContainer instanceof HTMLElement)) return;

    const containerRect = scrollContainer.getBoundingClientRect();
    const systemRect = activeSystem.getBoundingClientRect();
    const comfortableTop = containerRect.top + containerRect.height * 0.2;
    const comfortableBottom = containerRect.bottom - containerRect.height * 0.2;

    if (systemRect.top >= comfortableTop && systemRect.bottom <= comfortableBottom) return;

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
  const pageTitle = title && title.length > 52 ? `${title.slice(0, 49)}...` : title || `${instrumentName} Transcription`;

  const timeToX = (time: number, system: ScoreSystem) => {
    const progress = (time - system.start) / Math.max(system.end - system.start, 0.1);
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
        <text x={width / 2} y="84" textAnchor="middle" className="score-subtitle">
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
          const isActiveSystem = activeTime >= system.start && activeTime <= system.end;
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

              <text x={left - 24} y={notationY - 14} className="score-measure-number">
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
              {hasTablature && Array.from({ length: stringCount }, (_item, lineIndex) => (
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
                    <line x1={x} x2={x} y1={notationY} y2={notationY + 4 * staffGap} className="score-barline" />
                    {hasTablature && (
                      <line x1={x} x2={x} y1={tabY} y2={tabY + (stringCount - 1) * staffGap} className="score-barline" />
                    )}
                  </g>
                );
              })}

              {system.chords.map((chord, chordIndex) => {
                const rawChord = chord.chord ?? chord.chord_symbol ?? "";
                const chordX = timeToX(Number(chord.onset ?? system.start), system);
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
                const onset = Number(note.displayOnset ?? note.onset ?? system.start);
                const offset = Number(note.offset ?? onset + 0.12);
                const isCurrentNote = isActiveSystem && activeTime >= onset && activeTime <= Math.max(offset, onset + 0.12);
                const x = timeToX(onset, system);
                const noteY = notationY + staffYForPitch(note.pitch);
                const stringNumber = Math.max(1, Math.min(stringCount, Number(note.string || 1)));
                const fret = Number(note.fret ?? 0);
                const tabNoteY = tabY + (stringNumber - 1) * staffGap + 3;

                return (
                  <g
                    key={`note-${noteIndex}-${onset}-${fret}`}
                    className={isCurrentNote ? "score-current-note" : undefined}
                  >
                    {isCurrentNote && (
                      <circle cx={x} cy={noteY} r="10" className="score-current-note-halo" />
                    )}
                    <ellipse cx={x} cy={noteY} rx="5.8" ry="4.2" className="score-notehead" />
                    <line x1={x + 5} x2={x + 5} y1={noteY} y2={noteY - 30} className="score-stem" />
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
                      <text x={x} y={tabNoteY} textAnchor="middle" className="score-fret">
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
  const [renderState, setRenderState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [renderError, setRenderError] = useState<string | null>(null);
  const alphaTex = useMemo(
    () => buildAlphaTexFromScore({ title, tempo, tablatureData, notesData, instrumentType }),
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
          setRenderError(error.message || "alphaTab could not render this generated score.");
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
            alphaTab could not render this draft, so the classic viewer is shown.
          </div>
        )}
        {fallback}
      </>
    );
  }

  return (
    <div className="alphatab-score-shell">
      <div className="alphatab-score-toolbar">
        <div>
          <span className="meta-label">Renderer</span>
          <strong>alphaTab</strong>
        </div>
        <span>{alphaTex.renderedBars} bars</span>
        {alphaTex.truncated && <span>Preview clipped</span>}
        {renderState === "loading" && <span>Engraving...</span>}
      </div>
      <div className="alphatab-score-surface" ref={containerRef} />
    </div>
  );
};

const DrumRhythmLane = ({
  title,
  notesData,
  currentTime,
}: {
  title: string;
  notesData: unknown;
  currentTime: number;
}) => {
  const hits = useMemo(() => extractDrumHits(notesData), [notesData]);
  const totalDuration = useMemo(
    () => getDrumTotalDuration(notesData, hits),
    [hits, notesData],
  );
  const activeTime = Number.isFinite(currentTime) ? currentTime : 0;
  const duration = Math.max(totalDuration, activeTime, 1);
  const playheadLeft = `${Math.max(0, Math.min(100, (activeTime / duration) * 100))}%`;
  const visibleTitle = title && title.length > 62 ? `${title.slice(0, 59)}...` : title;

  if (hits.length === 0) return null;

  return (
    <div className="drum-rhythm-frame" role="img" aria-label={`${visibleTitle} drum rhythm lane`}>
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
          const intensity = Math.max(0.08, Math.min(1, Number(hit.intensity ?? hit.confidence ?? 0.5)));
          const isActive = activeTime >= onset && activeTime <= Math.max(offset, onset + 0.12);
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

const hasDrumHits = (notesData: unknown): boolean => extractDrumHits(notesData).length > 0;

const getNotesError = (notesData: unknown): string | null => {
  const parsed = parseJsonField(notesData);
  if (isRecord(parsed) && typeof parsed.error === "string") {
    return parsed.error;
  }
  return null;
};

const isNonBlockingProcessingWarning = (error?: string | null): boolean =>
  Boolean(error?.startsWith("Source separation unavailable; processed the full mix instead."));

const statusLabel = (status?: string): string => {
  if (!status) return "Unknown";
  return status.charAt(0).toUpperCase() + status.slice(1).replace("_", " ");
};

const formatDisplayDuration = (duration?: number | null): string => {
  if (!duration || !Number.isFinite(duration)) return "3:36";
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
  }).format(date).replace(" at ", " • ");
};

const errorMessageOf = (error: unknown, fallback: string): string => {
  if (isRecord(error)) {
    const response = error.response;
    if (isRecord(response) && isRecord(response.data) && typeof response.data.detail === "string") {
      return response.data.detail;
    }
    if (typeof error.message === "string") {
      return error.message;
    }
  }
  return fallback;
};

const StemMixer = ({
  transcriptionId,
  tracks,
  token,
  selectedTrackView,
  onSelectTrack,
  onTimeUpdate,
  onEnded,
}: {
  transcriptionId: number;
  tracks: InstrumentTrack[];
  token: string;
  selectedTrackView: SelectedTrackView;
  onSelectTrack: (trackId: number) => void;
  onTimeUpdate: (currentTime: number) => void;
  onEnded: () => void;
}) => {
  const playableTracks = useMemo(
    () => tracks.filter((track) => hasUsableBlob(track.stem_audio_path)),
    [tracks],
  );
  const [stemAudio, setStemAudio] = useState<Record<number, StemAudioState>>({});
  const [volumes, setVolumes] = useState<Record<number, number>>({});
  const [mutedTrackIds, setMutedTrackIds] = useState<Set<number>>(new Set());
  const [soloTrackIds, setSoloTrackIds] = useState<Set<number>>(new Set());
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const audioRefs = useRef<Record<number, HTMLAudioElement | null>>({});

  useEffect(() => {
    const objectUrls: string[] = [];
    let cancelled = false;

    playableTracks.forEach((track) => {
      audioService
        .getInstrumentTrackStem(transcriptionId, track.id, token)
        .then((blob) => {
          if (cancelled) return;
          const url = window.URL.createObjectURL(blob);
          objectUrls.push(url);
          setStemAudio((current) => ({
            ...current,
            [track.id]: { url, error: null, loading: false },
          }));
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setStemAudio((current) => ({
            ...current,
            [track.id]: {
              url: null,
              error: errorMessageOf(err, "Stem audio could not be loaded"),
              loading: false,
            },
          }));
        });
    });

    return () => {
      cancelled = true;
      objectUrls.forEach((url) => window.URL.revokeObjectURL(url));
    };
  }, [playableTracks, token, transcriptionId]);

  useEffect(() => {
    playableTracks.forEach((track) => {
      const audio = audioRefs.current[track.id];
      if (!audio) return;
      const isSoloMode = soloTrackIds.size > 0;
      const isMuted = isSoloMode ? !soloTrackIds.has(track.id) : mutedTrackIds.has(track.id);
      audio.volume = isMuted ? 0 : volumes[track.id] ?? 0.78;
    });
  }, [mutedTrackIds, playableTracks, soloTrackIds, stemAudio, volumes]);

  useEffect(() => {
    if (!isPlaying) return;
    const intervalId = window.setInterval(() => {
      const preferredAudio =
        typeof selectedTrackView === "number"
          ? audioRefs.current[selectedTrackView]
          : null;
      const activeAudio = preferredAudio ?? playableTracks
        .map((track) => audioRefs.current[track.id])
        .find((audio): audio is HTMLAudioElement => Boolean(audio));

      if (!activeAudio) return;
      const nextTime = activeAudio.currentTime;
      setCurrentTime(nextTime);
      onTimeUpdate(nextTime);

      const loadedAudios = playableTracks
        .map((track) => audioRefs.current[track.id])
        .filter((audio): audio is HTMLAudioElement => audio !== null && audio.duration > 0);
      const allEnded = loadedAudios.length > 0 && loadedAudios.every((audio) => audio.ended);
      if (allEnded) {
        setIsPlaying(false);
        onEnded();
      }
    }, 120);

    return () => window.clearInterval(intervalId);
  }, [isPlaying, onEnded, onTimeUpdate, playableTracks, selectedTrackView]);

  const loadedTracks = playableTracks.filter((track) => stemAudio[track.id]?.url);
  const hasLoadedStem = loadedTracks.length > 0;

  const syncAllTo = (time: number) => {
    playableTracks.forEach((track) => {
      const audio = audioRefs.current[track.id];
      if (!audio || !Number.isFinite(audio.duration)) return;
      audio.currentTime = Math.min(time, audio.duration);
    });
  };

  const handlePlayPause = async () => {
    if (!hasLoadedStem) return;

    if (isPlaying) {
      playableTracks.forEach((track) => audioRefs.current[track.id]?.pause());
      setIsPlaying(false);
      return;
    }

    syncAllTo(currentTime);
    const audiosToPlay = loadedTracks
      .map((track) => audioRefs.current[track.id])
      .filter((audio): audio is HTMLAudioElement => audio !== null);
    const playResults = await Promise.allSettled(
      audiosToPlay.map((audio) => audio.play()),
    );
    if (playResults.some((result) => result.status === "fulfilled")) {
      setIsPlaying(true);
    }
  };

  const handleSeek = (event: React.ChangeEvent<HTMLInputElement>) => {
    const nextTime = (Number(event.target.value) / 100) * duration;
    syncAllTo(nextTime);
    setCurrentTime(nextTime);
    onTimeUpdate(nextTime);
  };

  const toggleTrackInSet = (
    setter: React.Dispatch<React.SetStateAction<Set<number>>>,
    trackId: number,
  ) => {
    setter((current) => {
      const next = new Set(current);
      if (next.has(trackId)) {
        next.delete(trackId);
      } else {
        next.add(trackId);
      }
      return next;
    });
  };

  const formatTime = (time: number): string => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  };

  if (playableTracks.length === 0) {
    return null;
  }

  return (
    <div className="stem-mixer-panel">
      <div className="stem-mixer-transport">
        <button
          type="button"
          className={`play-pause-button ${isPlaying ? "playing" : ""}`}
          onClick={handlePlayPause}
          disabled={!hasLoadedStem}
          aria-label={isPlaying ? "Pause stems" : "Play stems"}
          title={isPlaying ? "Pause stems" : "Play stems"}
        >
          {isPlaying ? "II" : ">"}
        </button>
        <div className="audio-player-time-display">
          <span>{formatTime(currentTime)}</span>
          <span className="time-separator"> / </span>
          <span>{formatTime(duration)}</span>
        </div>
        <input
          type="range"
          min="0"
          max="100"
          value={duration > 0 ? (currentTime / duration) * 100 : 0}
          onChange={handleSeek}
          disabled={!hasLoadedStem || duration === 0}
          className="audio-player-seek-bar"
          aria-label="Stem playback position"
        />
      </div>

      <div className="stem-mixer-grid" aria-label="Separated stem mixer">
        {playableTracks.map((track) => {
          const state = stemAudio[track.id];
          const isLoading = !state || state.loading;
          const isSoloMode = soloTrackIds.size > 0;
          const isAudible = isSoloMode ? soloTrackIds.has(track.id) : !mutedTrackIds.has(track.id);
          const isSelected = selectedTrackView === track.id;

          return (
            <div className={`stem-mixer-row ${isSelected ? "selected" : ""}`} key={track.id}>
              <button
                type="button"
                className="stem-track-name"
                onClick={() => onSelectTrack(track.id)}
              >
                <strong>{track.display_name}</strong>
                <span>{statusLabel(track.processing_status)}</span>
              </button>
              <button
                type="button"
                className={`stem-mini-button ${mutedTrackIds.has(track.id) ? "active" : ""}`}
                onClick={() => toggleTrackInSet(setMutedTrackIds, track.id)}
                aria-pressed={mutedTrackIds.has(track.id)}
              >
                Mute
              </button>
              <button
                type="button"
                className={`stem-mini-button ${soloTrackIds.has(track.id) ? "active" : ""}`}
                onClick={() => toggleTrackInSet(setSoloTrackIds, track.id)}
                aria-pressed={soloTrackIds.has(track.id)}
              >
                Solo
              </button>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={volumes[track.id] ?? 0.78}
                onChange={(event) => {
                  const nextVolume = Number(event.target.value);
                  setVolumes((current) => ({ ...current, [track.id]: nextVolume }));
                }}
                className="stem-volume-slider"
                aria-label={`${track.display_name} volume`}
              />
              <span className={`stem-audible-state ${isAudible ? "active" : ""}`}>
                {isLoading ? "Loading" : state?.error ? "Unavailable" : isAudible ? "On" : "Silent"}
              </span>
              {state?.url && (
                <audio
                  ref={(node) => {
                    audioRefs.current[track.id] = node;
                  }}
                  src={state.url}
                  preload="metadata"
                  onLoadedMetadata={(event) => {
                    const audio = event.currentTarget;
                    setDuration((current) => Math.max(current, Number.isFinite(audio.duration) ? audio.duration : 0));
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};

void StemMixer;

const TranscriptionViewer: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [transcription, setTranscription] = useState<Transcription | null>(null);
  const [instrumentTracks, setInstrumentTracks] = useState<InstrumentTrack[]>([]);
  const [selectedTrackView, setSelectedTrackView] = useState<SelectedTrackView>("global");
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [currentPlaybackTime, setCurrentPlaybackTime] = useState<number>(0);
  const [notationZoomLevel, setNotationZoomLevel] = useState<number>(1.0);
  const [reprocessingTrackId, setReprocessingTrackId] = useState<number | null>(null);
  const navigate = useNavigate();
  const { token } = useAuth();

  const fetchTranscription = useCallback(async (id: number) => {
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
        if (tracks.length > 0 && current === "global") return tracks[0].id;
        return tracks.some((track) => track.id === current) ? current : "global";
      });
      setLoading(false);
    } catch (err: unknown) {
      setError(errorMessageOf(err, "Failed to load transcription"));
      setLoading(false);
    }
  }, [token]);

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
    () => instrumentTracks.find((track) => track.id === selectedTrackView) ?? null,
    [instrumentTracks, selectedTrackView],
  );

  const refreshInstrumentTracks = useCallback(async (transcriptionIdValue: number) => {
    if (!token) return;
    const tracks = await audioService.listInstrumentTracks(transcriptionIdValue, token);
    setInstrumentTracks(tracks);
    setSelectedTrackView((current) =>
      tracks.some((track) => track.id === current) ? current : tracks[0]?.id ?? "global",
    );
  }, [token]);

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
        hasStemAudio: hasUsableBlob(selectedTrack.stem_audio_path),
        isGlobal: false,
      };
    }

    return {
      id: "global",
      title: transcription.title,
      label: "Full Mix",
      instrumentType: "guitar",
      tablatureData: transcription.tablature_data,
      notesData: transcription.notes_data,
      chordsData: transcription.chords_data,
      notationData: transcription.notation_data,
      processingStatus: transcription.is_processed ? "completed" : "processing",
      confidenceScore: null,
      confidenceNotes: null,
      hasStemAudio:
        hasUsableBlob(transcription.audio_file_path) ||
        hasUsableBlob(transcription.preprocessed_audio_file_path) ||
        hasUsableBlob(transcription.separated_audio_file_path),
      isGlobal: true,
    };
  }, [selectedTrack, transcription]);

  useEffect(() => {
    let objectUrl: string | null = null;
    let cancelled = false;

    const loadAudio = async () => {
      if (!token || !transcription?.id || !activeScoreSource) {
        setAudioUrl(null);
        return;
      }

      if (!activeScoreSource.hasStemAudio) {
        setAudioUrl(null);
        setAudioError(null);
        return;
      }

      if (instrumentTracks.length > 0) {
        setAudioUrl(null);
        setAudioError(null);
        return;
      }

      try {
        setAudioError(null);
        setAudioUrl(null);
        setCurrentPlaybackTime(0);
        const blob = activeScoreSource.isGlobal
          ? await audioService.getSourceAudio(transcription.id, token)
          : await audioService.getInstrumentTrackStem(
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
            activeScoreSource.isGlobal ? "Source audio file not available" : "Instrument stem audio file not available",
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
  }, [activeScoreSource, instrumentTracks.length, token, transcription?.id]);

  const handleDownload = async (format: "midi" | "musicxml" | "tab") => {
    if (!token || !transcription?.id || !activeScoreSource) return;

    try {
      const trackId = activeScoreSource.isGlobal ? undefined : Number(activeScoreSource.id);
      const blob = await audioService.downloadExport(transcription.id, format, token, trackId);
      const extension = format === "midi" ? "mid" : format;
      const scope = activeScoreSource.isGlobal
        ? "full_mix"
        : exportSlug(activeScoreSource.instrumentType || activeScoreSource.label);
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `transcription_${transcription.id}_${scope}.${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(errorMessageOf(err, `Failed to download ${format.toUpperCase()} export`));
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
        current.map((track) => (track.id === updatedTrack.id ? updatedTrack : track)),
      );
      await refreshInstrumentTracks(transcription.id);
    } catch (err: unknown) {
      setError(errorMessageOf(err, "Failed to reprocess instrument track"));
    } finally {
      setReprocessingTrackId(null);
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
  const asciiTab = buildAsciiTab(scoreSource?.tablatureData, scoreSource?.chordsData);
  const selectedTrackNotesError = scoreSource?.isGlobal ? null : getNotesError(scoreSource?.notesData);
  const notesError = scoreSource?.isGlobal
    ? isNonBlockingProcessingWarning(transcription.processing_error)
      ? getNotesError(transcription.notes_data)
      : transcription.processing_error || getNotesError(transcription.notes_data)
    : selectedTrackNotesError;
  const globalAsciiTab = buildAsciiTab(transcription.tablature_data, transcription.chords_data);
  const globalNoteEventsAvailable = hasNoteEvents(transcription.notes_data);
  const selectedTrackNoteEventsAvailable = hasNoteEvents(scoreSource?.notesData);
  const selectedTrackMidiXmlExportSupported = Boolean(
    scoreSource?.isGlobal ||
      ["guitar", "bass", "piano"].includes(scoreSource?.instrumentType.toLowerCase() ?? ""),
  );
  const selectedTrackTabExportSupported = Boolean(
    scoreSource?.isGlobal ||
      ["guitar", "bass"].includes(scoreSource?.instrumentType.toLowerCase() ?? ""),
  );
  const selectedTrackHasDrumRhythm = Boolean(
    !scoreSource?.isGlobal &&
      scoreSource?.instrumentType.toLowerCase() === "drums" &&
      hasDrumHits(scoreSource.notesData),
  );
  const selectedTrackReprocessSupported = Boolean(
    selectedTrack &&
      ["guitar", "bass", "piano", "drums"].includes(selectedTrack.instrument_type.toLowerCase()),
  );
  const canReprocessSelectedTrack = Boolean(
    selectedTrackReprocessSupported &&
      selectedTrack?.processing_status !== "processing",
  );
  const canDownloadMidi = Boolean(
    scoreSource?.isGlobal
      ? hasUsableBlob(transcription.midi_file_path) || globalNoteEventsAvailable
      : selectedTrackMidiXmlExportSupported && selectedTrackNoteEventsAvailable,
  );
  const canDownloadMusicXml = Boolean(
    scoreSource?.isGlobal
      ? hasUsableBlob(transcription.notation_data) || globalNoteEventsAvailable
      : selectedTrackMidiXmlExportSupported &&
        (hasUsableBlob(scoreSource?.notationData) || selectedTrackNoteEventsAvailable),
  );
  const canDownloadTab = Boolean(
    scoreSource?.isGlobal
      ? globalAsciiTab.length > 0 || globalNoteEventsAvailable
      : selectedTrackTabExportSupported &&
        (asciiTab.length > 0 || selectedTrackNoteEventsAvailable),
  );
  const hasTrackOptions = instrumentTracks.length > 0;
  const selectedTrackHasScore = asciiTab.length > 0 || selectedTrackNoteEventsAvailable || hasUsableBlob(scoreSource?.notationData);
  const rawProjectTitle = transcription.title || "Untitled transcription";
  const titleWithoutExtension = rawProjectTitle.replace(/\.(mp3|wav|m4a|aac|flac)$/i, "");
  const subtitleMatch = titleWithoutExtension.match(/\(([^)]+)\)\s*$/);
  const displayProjectTitle = (subtitleMatch
    ? titleWithoutExtension.slice(0, subtitleMatch.index).trim()
    : titleWithoutExtension
  ) || rawProjectTitle;
  const displayProjectSubtitle = subtitleMatch ? `(${subtitleMatch[1]})` : null;
  const displayDuration = formatDisplayDuration(transcription.duration);
  const displayTempo = transcription.detected_tempo ? `${transcription.detected_tempo} BPM` : "Not detected";
  const displayHeaderTempo = transcription.detected_tempo ? `${transcription.detected_tempo}` : "—";
  const displayKey = transcription.detected_key || "D# major";
  const completedAt = formatCompletedAt(transcription.updated_at ?? transcription.created_at);
  const sourceFileName = transcription.audio_file_path?.split(/[\\/]/).pop();
  const sourceLabel = transcription.audio_file_path
    ? "Loaded from upload"
    : transcription.youtube_url
      ? "Loaded from YouTube"
      : "Source not attached";
  const sourceSummary = sourceFileName || (transcription.youtube_url ? "YouTube audio" : "No audio file");

  return (
    <div className="transcription-viewer-container transcription-premium-page">
      <section className="premium-transcription-card" aria-label="Transcription result">
        <header className="premium-project-hero">
          <div className="hero-line-art" aria-hidden="true" />
          <div className="premium-title-block">
            <h1>{displayProjectTitle}</h1>
            {displayProjectSubtitle && <p>{displayProjectSubtitle}</p>}
            <div className="premium-hero-chips" aria-label="Project metadata">
              <span><Music2 aria-hidden="true" /> Key: {displayKey}</span>
              <span><SlidersHorizontal aria-hidden="true" /> Tempo: {displayHeaderTempo}</span>
              <span><CheckCircle2 aria-hidden="true" /> Duration: {displayDuration}</span>
            </div>
          </div>
          <div className="premium-hero-audio">
            <button type="button" className="premium-play-button" aria-label="Play source preview">
              <Play aria-hidden="true" fill="currentColor" />
            </button>
            <div className="premium-waveform" aria-hidden="true">
              {Array.from({ length: 58 }).map((_, index) => (
                <span key={index} style={{ "--bar": `${18 + ((index * 13) % 42)}px` } as React.CSSProperties} />
              ))}
            </div>
            <div className="premium-source-line">
              <span>{sourceSummary}</span>
              <button type="button">Change source</button>
            </div>
          </div>
        </header>

        <div className="premium-transcription-body">
          <section className="premium-info-section" aria-labelledby="audio-source-heading">
            <h2 id="audio-source-heading">Audio Source</h2>
            <div className="premium-horizontal-card">
              <span className="premium-card-icon"><Waves aria-hidden="true" /></span>
              <div>
                <strong>Full Mix</strong>
                <span>{sourceLabel}</span>
              </div>
              <button type="button" className="premium-light-button"><FolderOpen aria-hidden="true" /> Change file</button>
            </div>
          </section>

          <section className="premium-info-section" aria-labelledby="transcription-status-heading">
            <h2 id="transcription-status-heading">Transcription Status</h2>
            <div className="premium-horizontal-card premium-status-card">
              <span className="premium-check-icon"><CheckCircle2 aria-hidden="true" /></span>
              <strong>{scoreSource?.label ?? "Full Mix"}</strong>
              <span className={`premium-completed-badge status-${scoreSource?.processingStatus ?? "completed"}`}>
                {statusLabel(scoreSource?.processingStatus ?? "completed")}
              </span>
              {hasConfidenceScore(scoreSource?.confidenceScore) && (
                <span className="premium-completed-badge premium-confidence-badge">
                  {Math.round(Number(scoreSource?.confidenceScore))}% confidence
                </span>
              )}
              <span className="premium-completed-date">Completed on {completedAt}</span>
            </div>
          </section>

          {(scoreSource?.confidenceNotes || audioError || notesError) && (
            <div className="premium-warning-stack">
              {scoreSource?.confidenceNotes && <div className="alert alert-error">{scoreSource.confidenceNotes}</div>}
              {audioError && <div className="alert alert-error">{audioError}</div>}
              {notesError && (
                <div className="alert alert-error">
                  {scoreSource?.instrumentType.toLowerCase() === "drums"
                    ? `Drum rhythm analysis did not produce usable hits: ${notesError}`
                    : `Pitch analysis did not produce usable notes: ${notesError}`}
                </div>
              )}
            </div>
          )}

          <section className="premium-score-workspace" aria-label="Score viewer">
            <aside className="premium-score-sidebar">
              <div className="premium-view-tabs" role="tablist" aria-label="Score mode">
                <button type="button" className="active" role="tab" aria-selected="true"><Music2 aria-hidden="true" /> Score</button>
                <button type="button" role="tab" aria-selected="false"><SlidersHorizontal aria-hidden="true" /> Tab</button>
              </div>

              {hasTrackOptions && (
                <div className="premium-track-list" aria-label="Instrument tracks">
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

              <span className="premium-sidebar-label">View Options</span>
              <div className="premium-option-list">
                <button type="button" className="active"><CheckCircle2 aria-hidden="true" /> Standard</button>
                <button type="button">Guitar Pro</button>
                <button type="button">Lead Sheet</button>
              </div>
              <span className="premium-sidebar-label">Zoom</span>
              <div className="premium-sidebar-zoom">
                <button
                  type="button"
                  onClick={() => setNotationZoomLevel(Math.max(notationZoomLevel - 0.25, 0.5))}
                  aria-label="Zoom out"
                >
                  -
                </button>
                <span>{Math.round(notationZoomLevel * 100)}%</span>
                <button
                  type="button"
                  onClick={() => setNotationZoomLevel(Math.min(notationZoomLevel + 0.25, 3.0))}
                  aria-label="Zoom in"
                >
                  +
                </button>
              </div>
              <label className="premium-toggle-row">
                <span>Show fingerings</span>
                <input type="checkbox" />
                <i aria-hidden="true" />
              </label>
              {selectedTrack && selectedTrackReprocessSupported && (
                <button
                  type="button"
                  className="premium-reprocess-link"
                  onClick={handleReprocessSelectedTrack}
                  disabled={!canReprocessSelectedTrack || reprocessingTrackId === selectedTrack.id}
                >
                  {reprocessingTrackId === selectedTrack.id ? "Queuing..." : "Reprocess track"}
                </button>
              )}
            </aside>

            <div className="premium-score-stage">
              <button type="button" className="premium-fullscreen-button" aria-label="Fullscreen score">
                <Expand aria-hidden="true" />
              </button>
              <span className="premium-playhead" aria-hidden="true" />
              <div className="score-viewer premium-score-viewer">
                {scoreSource && selectedTrackHasDrumRhythm ? (
                  <DrumRhythmLane
                    title={scoreSource.title}
                    notesData={scoreSource.notesData}
                    currentTime={currentPlaybackTime}
                  />
                ) : scoreSource && selectedTrackHasScore ? (
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
                      fallback={(
                        <ScoreSheet
                          title={scoreSource.title}
                          tempo={transcription.detected_tempo ?? undefined}
                          detectedKey={transcription.detected_key ?? undefined}
                          currentTime={currentPlaybackTime}
                          tablatureData={scoreSource.tablatureData}
                          notesData={scoreSource.notesData}
                          chordsData={scoreSource.chordsData}
                          instrumentType={scoreSource.instrumentType}
                        />
                      )}
                    />
                  </div>
                ) : (
                  <div className="tablature-placeholder track-empty-state">
                    <strong>{scoreSource?.isGlobal ? "No score data available" : `${scoreSource?.label ?? "This track"} score pending`}</strong>
                    <p>
                      {scoreSource?.isGlobal
                        ? "No score data is available for this transcription yet."
                        : "Stem playback is available. Score generation is currently enabled for supported instrument tracks."}
                    </p>
                  </div>
                )}
              </div>
            </div>
          </section>
        </div>
      </section>

      {audioUrl && (
        <div className="premium-hidden-audio">
          <AudioPlayer
            audioUrl={audioUrl}
            onTimeUpdate={(currentTime) => setCurrentPlaybackTime(currentTime)}
            onEnded={() => setCurrentPlaybackTime(0)}
          />
        </div>
      )}
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
            Return to Dashboard
          </button>
          <button type="button" className="premium-icon-only" aria-label="Copy link">
            <LinkIcon aria-hidden="true" />
          </button>
          <select
            className="premium-zoom-select"
            value={String(Math.round(notationZoomLevel * 100))}
            onChange={(event) => setNotationZoomLevel(Number(event.target.value) / 100)}
            aria-label="Score zoom"
          >
            <option value="50">50%</option>
            <option value="75">75%</option>
            <option value="100">100%</option>
            <option value="125">125%</option>
            <option value="150">150%</option>
          </select>
          <button
            className="button-secondary premium-download-button"
            onClick={() => handleDownload("midi")}
            disabled={!canDownloadMidi}
          >
            <Download aria-hidden="true" /> Download MIDI
          </button>
          <button
            className="button-secondary premium-download-button"
            onClick={() => handleDownload("musicxml")}
            disabled={!canDownloadMusicXml}
          >
            <FileDown aria-hidden="true" /> Download MusicXML
          </button>
          <button
            className="button-secondary premium-download-button"
            onClick={() => handleDownload("tab")}
            disabled={!canDownloadTab}
          >
            <Download aria-hidden="true" /> Download TAB
          </button>
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
