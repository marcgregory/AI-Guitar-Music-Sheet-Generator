import React, { useState, useEffect, useMemo, useRef } from "react";
import audioService from "../services/audioService";
import { useNavigate, useParams } from "react-router-dom";
import AudioPlayer from "./AudioPlayer";
import { useAuth } from "./auth/AuthContext";

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

const parseJsonField = (value: unknown): any => {
  if (!value) return null;
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value);
  } catch {
    return null;
  }
};

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

const buildAsciiTab = (tablatureData: unknown, chordsData: unknown): string => {
  const parsed = parseJsonField(tablatureData);
  const notes: TablatureNote[] = Array.isArray(parsed?.tablature)
    ? parsed.tablature
    : [];
  const parsedChords = parseJsonField(chordsData);
  const chords: ChordSegment[] = Array.isArray(parsedChords?.chords)
    ? parsedChords.chords
    : Array.isArray(parsedChords?.chord_charts)
      ? parsedChords.chord_charts
      : [];

  if (notes.length === 0) return "";

  const maxOffset = Math.max(
    ...notes.map((note) => Number(note.offset ?? note.onset ?? 0)),
    0.1,
  );
  const blockTime = 0.1;
  const columnsPerBlock = 2;
  const totalColumns = Math.max(24, Math.ceil(maxOffset / blockTime) * columnsPerBlock);
  const labels = ["e", "B", "G", "D", "A", "E"];
  const rows = labels.map(() => Array(totalColumns).fill("-"));
  const chordRow = Array(totalColumns).fill(" ");

  notes.forEach((note) => {
    const stringNumber = Number(note.string);
    const fret = Number(note.fret);
    const onset = Number(note.onset ?? 0);
    if (!Number.isFinite(stringNumber) || stringNumber < 1 || stringNumber > 6) return;
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
  if (!parsed || typeof parsed !== "object") return [];
  if (Array.isArray(parsed.notes)) return parsed.notes;
  if (Array.isArray(parsed.pitch_info)) return parsed.pitch_info;
  return [];
};

const extractTabNotes = (tablatureData: unknown): ScoreNote[] => {
  const parsed = parseJsonField(tablatureData);
  return Array.isArray(parsed?.tablature) ? parsed.tablature : [];
};

const extractChords = (chordsData: unknown): ChordSegment[] => {
  const parsed = parseJsonField(chordsData);
  if (Array.isArray(parsed?.chords)) return parsed.chords;
  if (Array.isArray(parsed?.chord_charts)) return parsed.chord_charts;
  return [];
};

const pitchFromTabNote = (note: TablatureNote, tuning: number[] = [40, 45, 50, 55, 59, 64]) => {
  const stringNumber = Number(note.string);
  const fret = Number(note.fret);
  if (!Number.isFinite(stringNumber) || !Number.isFinite(fret)) return undefined;
  if (stringNumber < 1 || stringNumber > 6 || fret < 0) return undefined;
  return tuning[6 - stringNumber] + fret;
};

const buildScoreNotes = (tablatureData: unknown, notesData: unknown): ScoreNote[] => {
  const tabNotes = extractTabNotes(tablatureData);
  const noteEvents = extractNoteEvents(notesData);

  return tabNotes
    .map((tabNote) => {
      const onset = Number(tabNote.onset ?? 0);
      const matchingEvent = noteEvents.find((event) => {
        const eventOnset = Number(event.onset ?? 0);
        return Math.abs(eventOnset - onset) < 0.03;
      });

      return {
        ...tabNote,
        pitch: Number(matchingEvent?.pitch ?? pitchFromTabNote(tabNote)),
      };
    })
    .filter((note) => Number.isFinite(Number(note.onset)) && Number.isFinite(Number(note.fret)));
};

const confidenceOf = (value?: number) =>
  Number.isFinite(Number(value)) ? Number(value) : 0;

const prepareDisplayNotes = (notes: ScoreNote[], tempo?: number): DisplayScoreNote[] => {
  const beatDuration = tempo && tempo > 0 ? 60 / tempo : 0.5;
  const gridSize = Math.max(0.08, beatDuration / 4);
  const bestBySlot = new Map<string, DisplayScoreNote>();

  notes.forEach((note) => {
    const onset = Number(note.onset ?? 0);
    const stringNumber = Number(note.string);
    const fret = Number(note.fret);
    if (!Number.isFinite(onset) || !Number.isFinite(stringNumber) || !Number.isFinite(fret)) return;

    const slot = Math.round(onset / gridSize);
    const displayOnset = slot * gridSize;
    const key = `${slot}:${stringNumber}`;
    const candidate = { ...note, displayOnset };
    const existing = bestBySlot.get(key);
    if (!existing || confidenceOf(candidate.confidence) >= confidenceOf(existing.confidence)) {
      bestBySlot.set(key, candidate);
    }
  });

  return Array.from(bestBySlot.values()).sort(
    (a, b) => a.displayOnset - b.displayOnset || Number(a.string ?? 0) - Number(b.string ?? 0),
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

const ScoreSheet = ({
  title,
  tempo,
  detectedKey,
  currentTime,
  tablatureData,
  notesData,
  chordsData,
}: {
  title: string;
  tempo?: number;
  detectedKey?: string;
  currentTime: number;
  tablatureData: unknown;
  notesData: unknown;
  chordsData: unknown;
}) => {
  const frameRef = useRef<HTMLDivElement>(null);
  const systemRefs = useRef<Array<SVGGElement | null>>([]);
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
  const systemHeight = 248;
  const pageHeight = 214 + systems.length * systemHeight;
  const pageTitle = title && title.length > 52 ? `${title.slice(0, 49)}...` : title || "Guitar Transcription";

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
        aria-label={`${pageTitle} guitar score`}
      >
        <rect width={width} height={pageHeight} fill="#fff" />
        <text x={width / 2} y="58" textAnchor="middle" className="score-title">
          {pageTitle}
        </text>
        <text x={width / 2} y="84" textAnchor="middle" className="score-subtitle">
          Guitar transcription
        </text>
        <text x={left} y="118" className="score-meta">
          Standard tuning
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
                  height={tabY - notationY + 5 * staffGap + 84}
                  fill="transparent"
                />
              </g>
              {isActiveSystem && (
                <g className="score-playback-layer">
                  <rect
                    x={left - 8}
                    y={notationY - 32}
                    width={right - left + 16}
                    height={tabY - notationY + 5 * staffGap + 48}
                    className="score-active-system"
                  />
                  <line
                    x1={playheadX}
                    x2={playheadX}
                    y1={notationY - 38}
                    y2={tabY + 5 * staffGap + 18}
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
              <text
                x={left - 34}
                y={tabY + 27}
                className="score-tab-label"
                transform={`rotate(-90 ${left - 34} ${tabY + 27})`}
              >
                TAB
              </text>

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
              {Array.from({ length: 6 }, (_item, lineIndex) => (
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
                    <line x1={x} x2={x} y1={tabY} y2={tabY + 5 * staffGap} className="score-barline" />
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
                const stringNumber = Math.max(1, Math.min(6, Number(note.string || 1)));
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
                    {isCurrentNote && (
                      <rect
                        x={x - 11}
                        y={tabNoteY - 14}
                        width="22"
                        height="18"
                        rx="3"
                        className="score-current-fret-bg"
                      />
                    )}
                    <text x={x} y={tabNoteY} textAnchor="middle" className="score-fret">
                      {fret}
                    </text>
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

const hasNoteEvents = (notesData: unknown): boolean => {
  const parsed = parseJsonField(notesData);
  if (Array.isArray(parsed)) return parsed.length > 0;
  if (!parsed || typeof parsed !== "object") return false;
  return (
    (Array.isArray(parsed.notes) && parsed.notes.length > 0) ||
    (Array.isArray(parsed.pitch_info) && parsed.pitch_info.length > 0)
  );
};

const getNotesError = (notesData: unknown): string | null => {
  const parsed = parseJsonField(notesData);
  if (parsed && typeof parsed === "object" && typeof parsed.error === "string") {
    return parsed.error;
  }
  return null;
};

const TranscriptionViewer: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [transcription, setTranscription] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [currentPlaybackTime, setCurrentPlaybackTime] = useState<number>(0);
  const [notationZoomLevel, setNotationZoomLevel] = useState<number>(1.0);
  const navigate = useNavigate();
  const { token } = useAuth();

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        fetchTranscription(idNum);
      } else {
        setError("Invalid transcription ID");
        setLoading(false);
      }
    } else {
      setError("No transcription ID provided");
      setLoading(false);
    }
  }, [transcriptionId]);

  useEffect(() => {
    let objectUrl: string | null = null;

    const loadSourceAudio = async () => {
      if (!token || !transcription?.id || !transcription.audio_file_path) {
        setAudioUrl(null);
        return;
      }

      try {
        setAudioError(null);
        const blob = await audioService.getSourceAudio(transcription.id, token);
        objectUrl = window.URL.createObjectURL(blob);
        setAudioUrl(objectUrl);
      } catch (err: any) {
        setAudioUrl(null);
        setAudioError(err.response?.data?.detail || "Source audio file not available");
      }
    };

    loadSourceAudio();

    return () => {
      if (objectUrl) {
        window.URL.revokeObjectURL(objectUrl);
      }
    };
  }, [token, transcription?.id, transcription?.audio_file_path]);

  const fetchTranscription = async (id: number) => {
    try {
      setLoading(true);
      setError(null);
      if (!token) {
        throw new Error("Authentication error. Please log in again.");
      }
      const response = await audioService.getTranscriptionResult(id, token);
      setTranscription(response);
      setLoading(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || "Failed to load transcription");
      setLoading(false);
    }
  };

  const handleDownload = async (format: "midi" | "musicxml" | "tab") => {
    if (!token || !transcription?.id) return;

    try {
      const blob = await audioService.downloadExport(transcription.id, format, token);
      const extension = format === "midi" ? "mid" : format;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `transcription_${transcription.id}.${extension}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
    } catch (err: any) {
      setError(err.message || err.response?.data?.detail || `Failed to download ${format.toUpperCase()} export`);
    }
  };

  if (loading) {
    return (
      <div className="transcription-viewer-container">
        <div className="transcription-viewer-header">
          <h2>Loading Transcription...</h2>
        </div>
        <div className="transcription-viewer-content">
          <div className="loading-spinner"></div>
          <p>Loading your transcription...</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="transcription-viewer-container">
        <div className="transcription-viewer-header">
          <h2>Error Loading Transcription</h2>
        </div>
        <div className="transcription-viewer-content">
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
      <div className="transcription-viewer-container">
        <div className="transcription-viewer-header">
          <h2>Transcription Not Found</h2>
        </div>
        <div className="transcription-viewer-content">
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

  const asciiTab = buildAsciiTab(transcription.tablature_data, transcription.chords_data);
  const noteEventsAvailable = hasNoteEvents(transcription.notes_data);
  const notesError = transcription.processing_error || getNotesError(transcription.notes_data);
  const canDownloadMidi = hasUsableBlob(transcription.midi_file_path) || noteEventsAvailable;
  const canDownloadMusicXml = hasUsableBlob(transcription.notation_data) || noteEventsAvailable;
  const canDownloadTab = asciiTab.length > 0 || noteEventsAvailable;

  return (
    <div className="transcription-viewer-container">
      <div className="transcription-viewer-header">
        <h2>{transcription.title}</h2>
        <p className="transcription-subtitle">
          {transcription.audio_file_path
            ? `Audio file: ${transcription.audio_file_path.split(/[\\/]/).pop()}`
            : "No audio file"}
          {transcription.youtube_url
            ? ` | YouTube: ${transcription.youtube_url}`
            : ""}
        </p>
      </div>

      <div className="transcription-viewer-content">
        {/* Audio Player Section */}
        {audioUrl && (
          <div className="transcription-audio-player">
            <AudioPlayer
              audioUrl={audioUrl}
              onTimeUpdate={(currentTime) => {
                // Update highlighting based on current time
                setCurrentPlaybackTime(currentTime);
              }}
              onEnded={() => setCurrentPlaybackTime(0)}
            />
          </div>
        )}
        {audioError && (
          <div className="alert alert-error">{audioError}</div>
        )}
        {notesError && (
          <div className="alert alert-error">
            Pitch analysis did not produce usable notes: {notesError}
          </div>
        )}

        <div className="score-viewer">
          {asciiTab ? (
            <div
              className="score-sheet-zoom"
              style={{
                transform: `scale(${notationZoomLevel})`,
                transformOrigin: "top left",
                width: `${100 / notationZoomLevel}%`,
              }}
            >
              <ScoreSheet
                title={transcription.title}
                tempo={transcription.detected_tempo}
                detectedKey={transcription.detected_key}
                currentTime={currentPlaybackTime}
                tablatureData={transcription.tablature_data}
                notesData={transcription.notes_data}
                chordsData={transcription.chords_data}
              />
            </div>
          ) : (
            <div className="tablature-placeholder">
              <p>
                {hasUsableBlob(transcription.notes_data)
                  ? "No usable note events were detected, so a score cannot be generated for this transcription."
                  : "No score data available"}
              </p>
            </div>
          )}
        </div>
      </div>

      <div className="transcription-footer">
        <div className="transcription-meta">
          <div className="meta-item">
            <span className="meta-label">Duration:</span>
            <span className="meta-value">
              {transcription.duration
                ? `${Math.floor(transcription.duration / 60)}:${String(transcription.duration % 60).padStart(2, "0")}`
                : "Unknown"}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Tempo:</span>
            <span className="meta-value">
              {transcription.detected_tempo
                ? `${transcription.detected_tempo} BPM`
                : "Not detected"}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Key:</span>
            <span className="meta-value">
              {transcription.detected_key
                ? transcription.detected_key
                : "Not detected"}
            </span>
          </div>
        </div>

        <div className="transcription-actions">
          <button
            className="button-secondary"
            onClick={() => navigate("/dashboard")}
          >
            Return to Dashboard
          </button>
          <div className="notation-zoom-controls">
            <button
              className={`zoom-button ${notationZoomLevel < 1.0 ? "active" : ""}`}
              onClick={() =>
                setNotationZoomLevel(Math.max(notationZoomLevel - 0.25, 0.5))
              }
              title="Zoom Out"
            >
              -
            </button>
            <span className="zoom-level">
              {Math.round(notationZoomLevel * 100)}%
            </span>
            <button
              className={`zoom-button ${notationZoomLevel > 2.0 ? "active" : ""}`}
              onClick={() =>
                setNotationZoomLevel(Math.min(notationZoomLevel + 0.25, 3.0))
              }
              title="Zoom In"
            >
              +
            </button>
          </div>
          <button
            className="button-secondary"
            onClick={() => handleDownload("midi")}
            disabled={!canDownloadMidi}
          >
            Download MIDI
          </button>
          <button
            className="button-secondary"
            onClick={() => handleDownload("musicxml")}
            disabled={!canDownloadMusicXml}
          >
            Download MusicXML
          </button>
          <button
            className="button-secondary"
            onClick={() => handleDownload("tab")}
            disabled={!canDownloadTab}
          >
            Download TAB
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
