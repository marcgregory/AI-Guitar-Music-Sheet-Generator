import React, { useState, useEffect } from 'react';
import audioService from '../services/audioService';
import { useNavigate, useParams } from 'react-router-dom';
import AudioPlayer from './AudioPlayer';

const TranscriptionViewer: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [transcription, setTranscription] = useState<any>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [currentPlaybackTime, setCurrentPlaybackTime] = useState<number>(0);
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [notationZoomLevel, setNotationZoomLevel] = useState<number>(1.0);
  const navigate = useNavigate();

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        fetchTranscription(idNum);
      } else {
        setError('Invalid transcription ID');
        setLoading(false);
      }
    } else {
      setError('No transcription ID provided');
      setLoading(false);
    }
  }, [transcriptionId]);

  const fetchTranscription = async (id: number) => {
    try {
      setLoading(true);
      setError(null);
      const response = await audioService.getTranscriptionResult(id);
      setTranscription(response);
      setLoading(false);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load transcription');
      setLoading(false);
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
          <div className="alert alert-error">
            {error}
          </div>
          <div className="transcription-actions">
            <button
              className="button-secondary"
              onClick={() => navigate('/dashboard')}
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
              onClick={() => navigate('/dashboard')}
            >
              Return to Dashboard
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="transcription-viewer-container">
      <div className="transcription-viewer-header">
        <h2>{transcription.title}</h2>
        <p className="transcription-subtitle">
          {transcription.audio_file_path
            ? `Audio file: ${transcription.audio_file_path.split(/[\\/]/).pop()}`
            : 'No audio file'}
          {transcription.youtube_url ? ` | YouTube: ${transcription.youtube_url}` : ''}
        </p>
      </div>

      <div className="transcription-viewer-content">
        {/* Audio Player Section */}
        {transcription.audio_file_path && (
          <div className="transcription-audio-player">
            <AudioPlayer
              audioUrl={`/audio-files/${transcription.audio_file_path.split(/[\\/]/).pop()}`}
              onTimeUpdate={(currentTime) => {
                // Update highlighting based on current time
                setCurrentPlaybackTime(currentTime);
              }}
              onEnded={() => {
                // Handle audio ended
                setIsPlaying(false);
              }}
            />
          </div>
        )}

        <div className="transcription-tabs">
          <div className="transcription-tab-panel">
            <h3>Guitar Tablature</h3>
            {transcription.tablature_data ? (
              <div className="tablature-display">
                {/* Simplified highlighting - in real app, this would be based on actual note timing */}
                <div className="tablature-code-container">
                  <pre className="tablature-code">
                    {transcription.tablature_data.split('\n').map((line, index) => {
                      // Simple heuristic: highlight lines based on playback position
                      const lineProgress = index / 10; // Assuming ~10 lines for demo
                      const isHighlighted = currentPlaybackTime > (lineProgress * 10) &&
                                          currentPlaybackTime < ((lineProgress + 1) * 10);
                      return (
                        <span key={index} className={isHighlighted ? 'highlighted-line' : ''}>
                          {line}\n
                        </span>
                      );
                    })}
                  </pre>
                </div>
              </div>
            ) : (
              <div className="tablature-placeholder">
                <p>No tablature data available</p>
              </div>
            )}
          </div>

          <div className="transcription-tab-panel">
            <h3>Music Notation</h3>
            {transcription.notation_data ? (
              <div className="notation-display">
                <div className="notation-header">
                  <span>MusicXML Format</span>
                  <button
                    className="button-sm"
                    onClick={() => {
                      // In a real app, this would download the MusicXML file
                      navigator.clipboard.writeText(transcription.notation_data || '');
                      alert('MusicXML copied to clipboard!');
                    }}
                  >
                    Copy MusicXML
                  </button>
                </div>
                <div className="notation-placeholder">
                  <p>MusicXML notation data available</p>
                  <p className="notation-info">
                    In a full implementation, this would render as standard musical notation.
                    For now, the raw MusicXML data is available below.
                  </p>
                  <div className="notation-code-container"
     style={{
       transform: `scale(${notationZoomLevel})`,
       transformOrigin: 'top left',
       width: `${100 / notationZoomLevel}%`,
       marginBottom: `${(notationZoomLevel - 1) * 20}px`
     }}
>
                    {/* Simplified highlighting for notation */}
                    <div className="notation-highlight-overlay"
                         style={{
                           height: `${Math.min(currentPlaybackTime / 10, 100)}%`,
                           backgroundColor: 'rgba(170, 59, 255, 0.2)',
                           pointerEvents: 'none'
                         }}
                    />
                    <pre className="notation-code"><code>{transcription.notation_data}</code></pre>
                  </div>
                </div>
              </div>
            ) : (
              <div className="notation-placeholder">
                <p>No notation data available</p>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="transcription-footer">
        <div className="transcription-meta">
          <div className="meta-item">
            <span className="meta-label">Duration:</span>
            <span className="meta-value">
              {transcription.duration
                ? `${Math.floor(transcription.duration / 60)}:${String(transcription.duration % 60).padStart(2, '0')}`
                : 'Unknown'}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Tempo:</span>
            <span className="meta-value">
              {transcription.detected_tempo
                ? `${transcription.detected_tempo} BPM`
                : 'Not detected'}
            </span>
          </div>
          <div className="meta-item">
            <span className="meta-label">Key:</span>
            <span className="meta-value">
              {transcription.detected_key
                ? transcription.detected_key
                : 'Not detected'}
            </span>
          </div>
        </div>

        <div className="transcription-actions">
          <button
            className="button-secondary"
            onClick={() => navigate('/dashboard')}
          >
            Return to Dashboard
          </button>
          <div className="notation-zoom-controls">
            <button
              className={`zoom-button ${notationZoomLevel < 1.0 ? 'active' : ''}`}
              onClick={() => setNotationZoomLevel(Math.max(notationZoomLevel - 0.25, 0.5)))
              title="Zoom Out"
            >
              🔍−
            </button>
            <span className="zoom-level">{Math.round(notationZoomLevel * 100)}%</span>
            <button
              className={`zoom-button ${notationZoomLevel > 2.0 ? 'active' : ''}`}
              onClick={() => setNotationZoomLevel(Math.min(notationZoomLevel + 0.25, 3.0))}
              title="Zoom In"
            >
              🔍+
            </button>
          </div>
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