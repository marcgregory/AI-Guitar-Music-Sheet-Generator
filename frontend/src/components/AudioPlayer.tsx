import React, { useState, useEffect, useRef } from 'react';

interface AudioPlayerProps {
  audioUrl: string;
  onTimeUpdate?: (currentTime: number) => void;
  onEnded?: () => void;
}

type PlayerIconName = "play" | "pause" | "volume" | "mute";

const PlayerIcon = ({ name }: { name: PlayerIconName }) => {
  const paths: Record<PlayerIconName, React.ReactNode> = {
    play: <path d="m8 5 11 7-11 7V5Z" />,
    pause: (
      <>
        <path d="M8 5v14" />
        <path d="M16 5v14" />
      </>
    ),
    volume: (
      <>
        <path d="M11 5 6 9H3v6h3l5 4V5Z" />
        <path d="M15.5 8.5a5 5 0 0 1 0 7" />
        <path d="M18.5 5.5a9 9 0 0 1 0 13" />
      </>
    ),
    mute: (
      <>
        <path d="M11 5 6 9H3v6h3l5 4V5Z" />
        <path d="m16 9 5 5" />
        <path d="m21 9-5 5" />
      </>
    ),
  };

  return (
    <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  );
};

const AudioPlayer: React.FC<AudioPlayerProps> = ({
  audioUrl,
  onTimeUpdate,
  onEnded
}) => {
  const [isPlaying, setIsPlaying] = useState<boolean>(false);
  const [currentTime, setCurrentTime] = useState<number>(0);
  const [duration, setDuration] = useState<number>(0);
  const [volume, setVolume] = useState<number>(0.7);
  const [playbackRate, setPlaybackRate] = useState<number>(1.0);
  const [loadError, setLoadError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const [isSeeking, setIsSeeking] = useState<boolean>(false);

  useEffect(() => {
    setIsPlaying(false);
    setCurrentTime(0);
    setDuration(0);
    setLoadError(null);
    audioRef.current?.load();
  }, [audioUrl]);

  useEffect(() => {
    if (!audioRef.current) return;

    const audio = audioRef.current;

    // Set initial volume
    audio.volume = volume;
    // Set initial playback rate
    audio.playbackRate = playbackRate;

    // Listen for duration change
    const handleLoadedMetadata = () => {
      setDuration(Number.isFinite(audio.duration) ? audio.duration : 0);
      setLoadError(null);
    };

    // Listen for time updates
    const handleTimeUpdate = () => {
      if (!isSeeking) {
        setCurrentTime(audio.currentTime);
        onTimeUpdate?.(audio.currentTime);
      }
    };

    // Listen for ended
    const handleEnded = () => {
      setIsPlaying(false);
      onEnded?.();
    };

    const handleError = () => {
      setIsPlaying(false);
      setDuration(0);
      setLoadError("Audio file could not be loaded.");
    };

    audio.addEventListener('loadedmetadata', handleLoadedMetadata);
    audio.addEventListener('timeupdate', handleTimeUpdate);
    audio.addEventListener('ended', handleEnded);
    audio.addEventListener('error', handleError);

    return () => {
      audio.removeEventListener('loadedmetadata', handleLoadedMetadata);
      audio.removeEventListener('timeupdate', handleTimeUpdate);
      audio.removeEventListener('ended', handleEnded);
      audio.removeEventListener('error', handleError);
    };
  }, [volume, playbackRate, onTimeUpdate, onEnded]);

  const handlePlayPause = async () => {
    if (!audioRef.current) return;

    if (isPlaying) {
      audioRef.current.pause();
      setIsPlaying(false);
    } else {
      try {
        await audioRef.current.play();
        setIsPlaying(true);
        setLoadError(null);
      } catch {
        setIsPlaying(false);
        setLoadError("Audio playback could not start.");
      }
    }
  };

  const handleSeek = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!audioRef.current) return;

    setIsSeeking(true);
    const seekTime = (Number(e.target.value) / 100) * duration;
    audioRef.current.currentTime = seekTime;
    setCurrentTime(seekTime);
  };

  const handleSeekEnd = () => {
    setIsSeeking(false);
  };

  const handleVolumeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const vol = Number(e.target.value);
    setVolume(vol);
    if (audioRef.current) {
      audioRef.current.volume = vol;
    }
  };

  const handlePlaybackRateChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const rate = Number(e.target.value);
    setPlaybackRate(rate);
    if (audioRef.current) {
      audioRef.current.playbackRate = rate;
    }
  };

  const formatTime = (time: number): string => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  return (
    <div className="audio-player-container">
      <div className="audio-player-header">
        <h3>Audio Playback</h3>
      </div>

      <div className="audio-player-controls">
        <div className="audio-player-main-controls">
          <button
            className={`play-pause-button ${isPlaying ? 'playing' : ''}`}
            onClick={handlePlayPause}
            aria-label={isPlaying ? 'Pause' : 'Play'}
            title={isPlaying ? 'Pause' : 'Play'}
          >
            <PlayerIcon name={isPlaying ? 'pause' : 'play'} />
          </button>

          <div className="audio-player-time-display">
            <span className="current-time">{formatTime(currentTime)}</span>
            <span className="time-separator">/</span>
            <span className="duration-time">{formatTime(duration)}</span>
          </div>

          <input
            type="range"
            min="0"
            max="100"
            value={duration > 0 ? (currentTime / duration) * 100 : 0}
            onChange={handleSeek}
            onMouseUp={handleSeekEnd}
            onMouseLeave={handleSeekEnd}
            disabled={duration === 0}
            className="audio-player-seek-bar"
          />
        </div>

        <div className="audio-player-volume-controls">
          <button
            className="volume-button icon-button"
            aria-label={volume === 0 ? 'Unmute' : 'Mute'}
            title="Mute/Unmute"
            onClick={() => {
              setVolume(volume > 0 ? 0 : 0.7);
              if (audioRef.current) {
                audioRef.current.volume = volume > 0 ? 0 : 0.7;
              }
            }}
          >
            <PlayerIcon name={volume === 0 ? 'mute' : 'volume'} />
          </button>
          <input
            type="range"
            min="0"
            max="1"
            step="0.1"
            value={volume}
            onChange={handleVolumeChange}
            className="audio-player-volume-bar"
          />

          <div className="audio-player-speed-controls">
            <span className="speed-label">Speed:</span>
            <select
              value={playbackRate.toString()}
              onChange={handlePlaybackRateChange}
              className="audio-player-speed-select"
            >
              <option value="0.5">0.5x</option>
              <option value="0.75">0.75x</option>
              <option value="1.0">1.0x</option>
              <option value="1.25">1.25x</option>
              <option value="1.5">1.5x</option>
              <option value="1.75">1.75x</option>
              <option value="2.0">2.0x</option>
            </select>
          </div>
        </div>
      </div>

      <audio
        ref={audioRef}
        src={audioUrl}
        preload="metadata"
      />
      {loadError && <p className="audio-player-error">{loadError}</p>}
    </div>
  );
};

export default AudioPlayer;
