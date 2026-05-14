import { Link } from "react-router-dom";
import { Icon } from "./Icon";

const services = [
  {
    label: "01",
    title: "Upload",
    text: "Bring in a local MP3, WAV, or a public YouTube performance.",
    icon: "upload" as const,
  },
  {
    label: "02",
    title: "Analyze",
    text: "Detect timing, notes, chords, tempo, and key from the source audio.",
    icon: "waveform" as const,
  },
  {
    label: "03",
    title: "Score",
    text: "Review a playable guitar score with tab, chords, and synchronized playback.",
    icon: "score" as const,
  },
  {
    label: "04",
    title: "Export",
    text: "Download MIDI, MusicXML, and TAB files for practice or arrangement.",
    icon: "download" as const,
  },
];

const workflow = [
  "Source audio",
  "Pitch analysis",
  "Chord map",
  "Guitar tab",
  "Export pack",
];

const marqueeItems = [
  "Strategy for practice",
  "Score generation",
  "Tab clarity",
  "Export workflow",
];

const LandingPage = () => (
  <main className="landing-page">
    <section className="landing-hero">
      <div className="landing-hero-copy">
        <p className="landing-kicker">
          <Icon name="flag" />
          AI guitar transcription studio
        </p>
        <h1>Hear it. See it. Play it.</h1>
        <p className="landing-lede">
          MusicSheet Studio turns rough guitar recordings into clean notation, playable tabs, chord insight, and
          export-ready files with a focused studio workflow.
        </p>
        <div className="landing-actions">
          <Link to="/register" className="landing-primary">
            <Icon name="arrow" />
            Start your first score
          </Link>
          <Link to="/login" className="landing-secondary">
            Sign in
          </Link>
        </div>
        <div className="landing-proof" aria-label="Studio highlights">
          <span>Audio to notation</span>
          <span>Synced playback</span>
          <span>MIDI + MusicXML export</span>
        </div>
      </div>

      <div className="landing-hero-visual" aria-label="Example transcription workflow">
        <div className="hero-signal" aria-hidden="true">
          {Array.from({ length: 18 }, (_item, index) => (
            <span key={index}></span>
          ))}
        </div>
        <div className="landing-score-board">
          <div className="score-board-topline">
            <span>Standard tuning</span>
            <span>q = 124</span>
          </div>
          <div className="score-board-title">Midnight Riff Study</div>
          <div className="score-lines" aria-hidden="true">
            {Array.from({ length: 5 }, (_item, index) => (
              <span key={index}></span>
            ))}
          </div>
          <div className="tab-lines" aria-hidden="true">
            {["e", "B", "G", "D", "A", "E"].map((label) => (
              <span key={label}>{label}|--0---3---5---7---</span>
            ))}
          </div>
          <div className="score-board-tags">
            <span>
              <Icon name="key" />
              Key: Em
            </span>
            <span>
              <Icon name="check" />
              Export ready
            </span>
          </div>
        </div>
        <div className="hero-cue-card">
          <span>Detected</span>
          <strong>Em / 124 BPM</strong>
        </div>
      </div>
    </section>

    <section className="landing-marquee" aria-label="Core capabilities">
      <div className="landing-marquee-track">
        {[...marqueeItems, ...marqueeItems].map((item, index) => (
          <span key={`${item}-${index}`}>{item}</span>
        ))}
      </div>
    </section>

    <section className="landing-services">
      <div className="landing-section-heading">
        <p>(How it works)</p>
        <h2>From signal to sheet in one focused flow.</h2>
      </div>
      <div className="service-grid">
        {services.map((service) => (
          <article key={service.title} className="service-card">
            <div className="service-card-label">
              <span>{service.label}</span>
              <Icon name={service.icon} />
            </div>
            <h3>{service.title}</h3>
            <p>{service.text}</p>
          </article>
        ))}
      </div>
    </section>

    <section className="landing-workflow">
      <div className="workflow-heading">
        <p>(Selected workflow)</p>
        <h2>A transcription pipeline built for guitar decisions.</h2>
      </div>
      <div className="workflow-list">
        {workflow.map((step, index) => (
          <div key={step} className="workflow-row">
            <span>{String(index + 1).padStart(2, "0")}</span>
            <strong>{step}</strong>
            <Icon name="arrow" />
          </div>
        ))}
      </div>
    </section>
  </main>
);

export default LandingPage;
