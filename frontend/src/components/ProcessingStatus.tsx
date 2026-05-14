import React, { useState, useEffect } from 'react';
import audioService from '../services/audioService';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from './auth/AuthContext';

const ProcessingStatus: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [status, setStatus] = useState<'idle' | 'processing' | 'completed' | 'failed'>('idle');
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [transcriptionIdNum, setTranscriptionIdNum] = useState<number | null>(null);
  const navigate = useNavigate();
  const { token } = useAuth();

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        setTranscriptionIdNum(idNum);
        checkTranscriptionStatus(idNum);

        // Set up polling to check status every 2 seconds
        const interval = setInterval(() => {
          checkTranscriptionStatus(idNum);
        }, 2000);

        return () => clearInterval(interval);
      }
    }
    navigate('/dashboard');
  }, [transcriptionId, token, navigate]);

  const checkTranscriptionStatus = async (id: number) => {
    if (!token) return;

    try {
      setStatus('processing');
      const response = await audioService.getTranscriptionStatus(id, token);

      if (response.status === 'completed') {
        setStatus('completed');
        setProgress(100);
        // Navigate to transcription result after a short delay
        setTimeout(() => {
          navigate(`/transcription/${id}`);
        }, 1500);
      } else if (response.status === 'failed') {
        setStatus('failed');
        setError(response.error || 'Processing failed');
      } else {
        setStatus('processing');
        setProgress(typeof response.progress === 'number' ? response.progress : null);
      }
    } catch (err: any) {
      setStatus('failed');
      setError(err.response?.data?.detail || 'Failed to check transcription status');
    }
  };

  if (status === 'idle') {
    return (
      <div className="processing-status-container">
        <div className="processing-status-header">
          <h2>Processing Your Audio</h2>
          <p>We're analyzing your audio file to generate guitar tabs</p>
        </div>
        <div className="processing-status-content">
          <div className="processing-spinner"></div>
          <p className="processing-text">Preparing upload...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="processing-status-container">
      <div className="processing-status-header">
        <h2>Processing Your Audio</h2>
        <p>We're analyzing your audio file to generate guitar tabs</p>
      </div>

      {status === 'processing' && (
        <div className="processing-status-content">
          <div className="processing-info">
            <div className="progress-section">
              <div className="progress-label">Processing Progress</div>
              <div className="progress-bar">
                <div
                  className={`progress-fill ${progress === null ? 'indeterminate' : ''}`}
                  style={{ width: progress === null ? undefined : `${progress}%` }}
                ></div>
              </div>
              <p className="progress-percent">
                {progress === null ? 'Processing...' : `${progress}%`}
              </p>
            </div>

            {progress !== null && (
              <div className="estimated-time">
                <div className="time-label">Estimated Time Remaining</div>
                <div className="time-value">
                  <span>~{Math.max(1, Math.round((100 - progress) / 10))} min</span>
                </div>
              </div>
            )}
          </div>

          <div className="processing-details">
            <p>This process may take several minutes depending on the length and complexity of your audio file.</p>
            <p>You can safely close this tab and return later - we'll notify you when processing is complete.</p>
          </div>
        </div>
      )}

      {status === 'completed' && (
        <div className="processing-status-content processing-success">
          <div className="success-icon" aria-hidden="true"></div>
          <h3>Processing complete</h3>
          <p>Your audio has been successfully processed and transcribed into guitar tabs.</p>
          <div className="processing-actions">
            <button
              className="button-primary"
              onClick={() => navigate(`/transcription/${transcriptionIdNum}`)}
            >
              View Transcription
            </button>
          </div>
        </div>
      )}

      {status === 'failed' && (
        <div className="processing-status-content processing-error">
          <div className="error-icon" aria-hidden="true"></div>
          <h3>Processing failed</h3>
          <p>{error || 'An error occurred during processing'}</p>
          <div className="processing-actions">
            <button
              className="button-secondary"
              onClick={() => navigate('/dashboard')}
            >
              Return to Dashboard
            </button>
            <button
              className="button-primary"
              onClick={() => {
                // Retry processing - in a real app, this would restart the process
                navigate(`/upload`);
              }}
            >
              Try Again
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default ProcessingStatus;
