import React, { useState, useEffect } from 'react';
import audioService from '../services/audioService';
import { useNavigate, useParams } from 'react-router-dom';

const ProcessingStatus: React.FC = () => {
  const { transcriptionId } = useParams<{ transcriptionId: string }>();
  const [status, setStatus] = useState<'idle' | 'processing' | 'completed' | 'failed'>('idle');
  const [progress, setProgress] = useState<number>(0);
  const [error, setError] = useState<string | null>(null);
  const [transcriptionIdNum, setTranscriptionIdNum] = useState<number | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    if (transcriptionId) {
      const idNum = parseInt(transcriptionId, 10);
      if (!isNaN(idNum)) {
        setTranscriptionIdNum(idNum);
        checkTranscriptionStatus();

        // Set up polling to check status every 2 seconds
        const interval = setInterval(() => {
          checkTranscriptionStatus();
        }, 2000);

        return () => clearInterval(interval);
      }
    }
  }, [transcriptionId]);

  const checkTranscriptionStatus = async () => {
    if (!transcriptionIdNum) return;

    try {
      setStatus('processing');
      const response = await audioService.getTranscriptionStatus(transcriptionIdNum);

      if (response.status === 'completed') {
        setStatus('completed');
        setProgress(100);
        // Navigate to transcription result after a short delay
        setTimeout(() => {
          navigate(`/transcription/${transcriptionIdNum}`);
        }, 1500);
      } else if (response.status === 'failed') {
        setStatus('failed');
        setError(response.error || 'Processing failed');
      } else {
        // Still processing
        setStatus('processing');
        // Simulate progress based on time elapsed or use actual progress if available from backend
        setProgress(Math.min(progress + 5, 95)); // Increment progress slowly
      }
    } catch (err: any) {
      setStatus('failed');
      setError(err.response?.data?.detail || 'Failed to check transcription status');
    }
  };

  // If we somehow got here without a valid ID, go back to dashboard
  useEffect(() => {
    if (!transcriptionIdNum) {
      navigate('/dashboard');
    }
  }, [transcriptionIdNum, navigate]);

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
                <div className="progress-fill" style={{ width: `${progress}%` }}></div>
              </div>
              <p className="progress-percent">{progress}%</p>
            </div>

            <div className="estimated-time">
              <div className="time-label">Estimated Time Remaining</div>
              <div className="time-value">
                {/* In a real app, this would be calculated based on actual processing time */}
                <span>~{Math.max(1, Math.round((100 - progress) / 10))} min</span>
              </div>
            </div>
          </div>

          <div classname="processing-details">
            <p>This process may take several minutes depending on the length and complexity of your audio file.</p>
            <p>You can safely close this tab and return later - we'll notify you when processing is complete.</p>
          </div>
        </div>
      )}

      {status === 'completed' && (
        <div className="processing-status-content processing-success">
          <div className="success-icon">✅</div>
          <h3>Processing Complete!</h3>
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
          <div className="error-icon">❌</div>
          <h3>Processing Failed</h3>
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
              onCheck={() => {
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