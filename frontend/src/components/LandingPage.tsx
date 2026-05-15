import { useLayoutEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { MotionPathPlugin } from "gsap/MotionPathPlugin";
import { ScrollTrigger } from "gsap/ScrollTrigger";
import { Icon } from "./Icon";

gsap.registerPlugin(MotionPathPlugin, ScrollTrigger);

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

const workflow = ["Source audio", "Pitch analysis", "Chord map", "Guitar tab", "Export pack"];

const capabilityRail = [
  { title: "AI transcription", subtitle: "Accurate & reliable", icon: "waveform" as const },
  { title: "Tab clarity", subtitle: "Clean & easy to read", icon: "key" as const },
  { title: "Export workflow", subtitle: "MIDI, MusicXML, TAB", icon: "download" as const },
  { title: "Strategy for practice", subtitle: "Insights that help you improve", icon: "gauge" as const },
  { title: "Score generation", subtitle: "Notation in seconds", icon: "music" as const },
];

const workflowDetails = [
  {
    title: "Source audio",
    text: "Import a local performance or public YouTube link, then normalize the source so the transcription engine has a cleaner signal to read.",
    chips: [
      { label: "MP3 / WAV", sublabel: "Local upload", icon: "upload" as const },
      { label: "YouTube", sublabel: "Public links", icon: "music" as const },
      { label: "Prep pass", sublabel: "Cleaner signal", icon: "waveform" as const },
    ],
  },
  {
    title: "Pitch analysis",
    text: "We break down the audio to detect each note with precision, capturing bends, slides, and articulations so nothing gets lost.",
    chips: [
      { label: "High resolution", sublabel: "Note detection", icon: "waveform" as const },
      { label: "Bend & slide", sublabel: "Recognition", icon: "gauge" as const },
      { label: "Key & scale", sublabel: "Estimation", icon: "key" as const },
    ],
  },
  {
    title: "Chord map",
    text: "Detected notes become musical context, grouping tones into chord changes and giving you a practical map for practice.",
    chips: [
      { label: "Chord timing", sublabel: "Bar aligned", icon: "clock" as const },
      { label: "Harmony", sublabel: "Context pass", icon: "music" as const },
      { label: "Practice cues", sublabel: "Faster review", icon: "gauge" as const },
    ],
  },
  {
    title: "Guitar tab",
    text: "The score is shaped into playable guitar notation with string and fret choices that are easier to read and rehearse.",
    chips: [
      { label: "String choice", sublabel: "Playable tab", icon: "score" as const },
      { label: "Synced score", sublabel: "Playback ready", icon: "clock" as const },
      { label: "Clean layout", sublabel: "Easy reading", icon: "check" as const },
    ],
  },
  {
    title: "Export pack",
    text: "Package the result for practice, editing, or arranging with MIDI, MusicXML, and tab-focused output.",
    chips: [
      { label: "MIDI", sublabel: "DAW ready", icon: "download" as const },
      { label: "MusicXML", sublabel: "Notation apps", icon: "score" as const },
      { label: "TAB", sublabel: "Practice file", icon: "key" as const },
    ],
  },
];

const waveformBars = [
  26, 44, 34, 62, 38, 72, 46, 86, 42, 68, 56, 94, 48, 78, 40, 63, 50, 88, 58, 76, 44, 70, 36, 52,
  31, 60, 43, 82, 54, 74, 39, 66, 47, 91, 58, 72, 36, 61, 46, 83, 52, 69, 41, 58, 34, 50,
];

const featurePills = [
  { label: "Audio to notation", icon: "waveform" as const },
  { label: "Synced playback", icon: "music" as const },
  { label: "MIDI + MusicXML export", icon: "download" as const },
];

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const LandingPage = () => {
  const heroRef = useRef<HTMLElement>(null);
  const workflowRef = useRef<HTMLElement>(null);
  const [activeWorkflowIndex, setActiveWorkflowIndex] = useState(1);
  const activeWorkflow = workflowDetails[activeWorkflowIndex];

  useLayoutEffect(() => {
    const hero = heroRef.current;
    if (!hero || prefersReducedMotion()) return;

    let removePointerListeners: (() => void) | undefined;

    const ctx = gsap.context(() => {
      const q = gsap.utils.selector(hero);
      const card = q(".studio-card")[0] as HTMLElement | undefined;
      const ribbon = q(".hero-light-ribbon")[0] as HTMLElement | undefined;
      const glow = q(".hero-ambient-glow")[0] as HTMLElement | undefined;

      // Initial page load: soft editorial reveal, from nav through the studio card.
      const intro = gsap.timeline({ defaults: { ease: "power4.out" } });
      intro
        .fromTo(
          ".public-site-nav",
          { y: -22, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.85 },
          0,
        )
        .fromTo(
          q(".landing-kicker"),
          { y: 18, opacity: 0, filter: "blur(16px)" },
          { y: 0, opacity: 1, filter: "blur(0px)", duration: 0.95 },
          0.14,
        )
        .fromTo(
          q(".hero-title-line"),
          { yPercent: 105, opacity: 0, filter: "blur(10px)" },
          { yPercent: 0, opacity: 1, filter: "blur(0px)", duration: 1.15, stagger: 0.12 },
          0.26,
        )
        .fromTo(
          q(".landing-lede"),
          { y: 24, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.85 },
          0.72,
        )
        .fromTo(
          q(".landing-actions a"),
          { y: 22, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.82, stagger: 0.08 },
          0.86,
        )
        .fromTo(
          q(".landing-proof span"),
          { y: 18, opacity: 0, filter: "blur(8px)" },
          { y: 0, opacity: 1, filter: "blur(0px)", duration: 0.74, stagger: 0.07 },
          1.02,
        )
        .fromTo(
          q(".studio-card"),
          {
            x: 78,
            opacity: 0,
            scale: 0.92,
            rotateX: 13,
            rotateY: -18,
            rotateZ: 5,
            filter: "blur(16px)",
          },
          {
            x: 0,
            opacity: 1,
            scale: 1,
            rotateX: 5,
            rotateY: -8,
            rotateZ: -2,
            filter: "blur(0px)",
            duration: 1.35,
          },
          0.42,
        )
        .fromTo(
          q(".hero-bpm-card"),
          { y: 34, opacity: 0, filter: "blur(12px)" },
          { y: 0, opacity: 1, filter: "blur(0px)", duration: 0.9 },
          1.08,
        );

      // Continuous loops: quiet movement, waveform life, playhead scanning, and glow pulses.
      gsap.to(q(".studio-card-float"), {
        y: -16,
        duration: 4.8,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".studio-card-breath"), {
        rotateX: 7,
        rotateY: -5,
        rotateZ: -1.2,
        duration: 6.8,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".hero-light-ribbon"), {
        rotate: 360,
        xPercent: 6,
        yPercent: -4,
        duration: 30,
        ease: "none",
        repeat: -1,
      });

      gsap.to(q(".wave-bar"), {
        scaleY: () => gsap.utils.random(0.45, 1.35),
        opacity: () => gsap.utils.random(0.45, 1),
        duration: 0.9,
        ease: "sine.inOut",
        stagger: { each: 0.035, repeat: -1, yoyo: true },
      });

      gsap.to(q(".studio-playhead"), {
        xPercent: 104,
        duration: 5.8,
        ease: "none",
        repeat: -1,
      });

      gsap.to(q(".bpm-glow-dot"), {
        scale: 1.45,
        opacity: 0.46,
        duration: 1.7,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".guitar-sweep"), {
        xPercent: 135,
        duration: 7.5,
        ease: "sine.inOut",
        repeat: -1,
        repeatDelay: 1.2,
      });

      // Mouse parallax: write to a wrapper so it stays separate from the card floating loop.
      const tiltX = gsap.quickTo(q(".studio-card-parallax"), "rotateY", { duration: 0.75, ease: "power4.out" });
      const tiltY = gsap.quickTo(q(".studio-card-parallax"), "rotateX", { duration: 0.75, ease: "power4.out" });
      const ribbonX = ribbon ? gsap.quickTo(ribbon, "x", { duration: 1.2, ease: "power4.out" }) : null;
      const ribbonY = ribbon ? gsap.quickTo(ribbon, "y", { duration: 1.2, ease: "power4.out" }) : null;
      const glowX = glow ? gsap.quickTo(glow, "x", { duration: 1.6, ease: "power4.out" }) : null;
      const glowY = glow ? gsap.quickTo(glow, "y", { duration: 1.6, ease: "power4.out" }) : null;

      const handlePointerMove = (event: PointerEvent) => {
        const bounds = hero.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width - 0.5;
        const y = (event.clientY - bounds.top) / bounds.height - 0.5;
        tiltX(x * 7);
        tiltY(y * -5);
        ribbonX?.(x * 34);
        ribbonY?.(y * 24);
        glowX?.(x * 22);
        glowY?.(y * 18);
      };

      const handlePointerLeave = () => {
        tiltX(0);
        tiltY(0);
        ribbonX?.(0);
        ribbonY?.(0);
        glowX?.(0);
        glowY?.(0);
      };

      hero.addEventListener("pointermove", handlePointerMove);
      hero.addEventListener("pointerleave", handlePointerLeave);
      removePointerListeners = () => {
        hero.removeEventListener("pointermove", handlePointerMove);
        hero.removeEventListener("pointerleave", handlePointerLeave);
      };

      // ScrollTrigger: cinematic retreat as the hero leaves the viewport.
      if (card) {
        gsap.to(q(".studio-card-depth"), {
          scale: 0.94,
          z: -120,
          opacity: 0.8,
          ease: "none",
          scrollTrigger: {
            trigger: hero,
            start: "top top",
            end: "bottom top",
            scrub: true,
          },
        });
      }

      gsap.to(q(".landing-hero-copy"), {
        yPercent: -10,
        opacity: 0.18,
        ease: "none",
        scrollTrigger: {
          trigger: hero,
          start: "45% top",
          end: "bottom top",
          scrub: true,
        },
      });

      gsap.to(q(".hero-background-depth"), {
        yPercent: 18,
        ease: "none",
        scrollTrigger: {
          trigger: hero,
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });

    }, hero);

    return () => {
      removePointerListeners?.();
      ctx.revert();
    };
  }, []);

  useLayoutEffect(() => {
    const section = workflowRef.current;
    if (!section || prefersReducedMotion()) return;

    const cleanupHandlers: Array<() => void> = [];

    const ctx = gsap.context(() => {
      const q = gsap.utils.selector(section);
      const rail = q(".workflow-capability-rail")[0] as HTMLElement | undefined;
      const railTrack = q(".workflow-capability-track")[0] as HTMLElement | undefined;
      const guitarBody = q(".workflow-guitar-body")[0] as HTMLElement | undefined;
      const guitarNeck = q(".workflow-guitar-neck")[0] as HTMLElement | undefined;
      const sceneGlow = q(".workflow-scene-glow")[0] as HTMLElement | undefined;
      const signalLine = q(".workflow-signal-line")[0] as HTMLElement | undefined;
      const cards = q(".workflow-step-card") as HTMLElement[];

      // Cinematic section entrance: slow, soft, and intentionally restrained.
      const entrance = gsap.timeline({
        defaults: { ease: "power4.out" },
        scrollTrigger: {
          trigger: section,
          start: "top 78%",
          once: true,
        },
      });

      entrance
        .fromTo(section, { autoAlpha: 0, y: 42 }, { autoAlpha: 1, y: 0, duration: 1.15 }, 0)
        .fromTo(
          q(".workflow-scene-glow, .workflow-scene::before"),
          { autoAlpha: 0, scale: 0.94 },
          { autoAlpha: 1, scale: 1, duration: 1.6 },
          0.12,
        )
        .fromTo(
          q(".workflow-capability-rail"),
          { y: 18, autoAlpha: 0, filter: "blur(14px)" },
          { y: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1 },
          0.16,
        )
        .fromTo(
          q(".workflow-hero-copy p:first-child"),
          { y: 14, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.72 },
          0.32,
        )
        .fromTo(
          q(".workflow-title-line"),
          { yPercent: 72, autoAlpha: 0, filter: "blur(16px)" },
          { yPercent: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1.08, stagger: 0.13 },
          0.42,
        )
        .fromTo(
          q(".workflow-focus-word"),
          { autoAlpha: 0, y: 22, filter: "blur(18px)" },
          { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 1.35, ease: "expo.out" },
          0.86,
        )
        .fromTo(
          q(".workflow-focus-sweep"),
          { xPercent: -135, autoAlpha: 0 },
          { xPercent: 135, autoAlpha: 1, duration: 1.2, ease: "sine.inOut" },
          1.06,
        )
        .fromTo(
          q(".workflow-hero-lede"),
          { y: 20, autoAlpha: 0 },
          { y: 0, autoAlpha: 1, duration: 0.86 },
          0.92,
        )
        .fromTo(
          cards,
          { y: 44, rotateX: 10, autoAlpha: 0, filter: "blur(16px)", transformOrigin: "50% 100%" },
          { y: 0, rotateX: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1, stagger: 0.1 },
          1.02,
        )
        .fromTo(
          q(".workflow-detail-panel"),
          { y: 34, autoAlpha: 0, filter: "blur(14px)" },
          { y: 0, autoAlpha: 1, filter: "blur(0px)", duration: 1 },
          1.24,
        )
        .fromTo(
          q(".workflow-graph-line"),
          { strokeDashoffset: 560 },
          { strokeDashoffset: 0, duration: 1.55, stagger: 0.12, ease: "expo.out" },
          1.32,
        );

      // Top strip: premium dashboard ticker, with pause on hover.
      if (railTrack) {
        const marquee = gsap.to(railTrack, {
          xPercent: -50,
          duration: 34,
          ease: "none",
          repeat: -1,
        });

        if (rail) {
          const pause = () => marquee.pause();
          const resume = () => marquee.resume();
          rail.addEventListener("pointerenter", pause);
          rail.addEventListener("pointerleave", resume);
          cleanupHandlers.push(() => {
            rail.removeEventListener("pointerenter", pause);
            rail.removeEventListener("pointerleave", resume);
          });
        }
      }

      gsap.to(q(".workflow-capability-item .ui-icon"), {
        scale: 1.14,
        opacity: 0.72,
        duration: 2.8,
        ease: "sine.inOut",
        stagger: { each: 0.42, repeat: -1, yoyo: true },
      });

      // Guitar, glow, and waveform atmosphere.
      gsap.to(q(".workflow-guitar-body, .workflow-guitar-neck"), {
        y: -12,
        duration: 6.5,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".workflow-string-sweep"), {
        xPercent: 180,
        duration: 5.6,
        ease: "sine.inOut",
        repeat: -1,
        repeatDelay: 1.1,
      });

      gsap.to(q(".workflow-signal-line"), {
        x: 18,
        opacity: 0.92,
        duration: 4.8,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".workflow-scene-glow"), {
        scale: 1.04,
        opacity: 0.82,
        duration: 5.2,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".workflow-graph-line"), {
        y: -6,
        duration: 3.9,
        ease: "sine.inOut",
        stagger: { each: 0.28, repeat: -1, yoyo: true },
      });

      const primaryGraphPath = q(".workflow-graph-line.primary")[0] as unknown as SVGPathElement | undefined;
      if (primaryGraphPath) {
        gsap.to(q(".workflow-graph-particle"), {
          motionPath: {
            path: primaryGraphPath,
            align: primaryGraphPath,
            autoRotate: false,
          },
          duration: 4.2,
          ease: "none",
          repeat: -1,
          stagger: 0.75,
        });
      }

      // Scroll depth: subtle parallax only.
      gsap.to(q(".workflow-hero-copy"), {
        yPercent: -8,
        opacity: 0.72,
        ease: "none",
        scrollTrigger: {
          trigger: section,
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });

      gsap.to(q(".workflow-scene"), {
        yPercent: 14,
        ease: "none",
        scrollTrigger: {
          trigger: section,
          start: "top bottom",
          end: "bottom top",
          scrub: true,
        },
      });

      cards.forEach((card, index) => {
        gsap.to(card, {
          y: index % 2 === 0 ? -5 : 5,
          duration: 5.4 + index * 0.45,
          ease: "sine.inOut",
          yoyo: true,
          repeat: -1,
        });

        const icon = card.querySelector(".workflow-step-icon");
        const button = card.querySelector(".workflow-step-arrow");
        const setGlowX = gsap.quickSetter(card, "--card-glow-x");
        const setGlowY = gsap.quickSetter(card, "--card-glow-y");
        const tiltX = gsap.quickTo(card, "rotateX", { duration: 0.55, ease: "power4.out" });
        const tiltY = gsap.quickTo(card, "rotateY", { duration: 0.55, ease: "power4.out" });
        const iconScale = icon ? gsap.quickTo(icon, "scale", { duration: 0.38, ease: "power4.out" }) : null;
        const buttonX = button ? gsap.quickTo(button, "x", { duration: 0.45, ease: "power4.out" }) : null;
        const buttonRotate = button ? gsap.quickTo(button, "rotate", { duration: 0.45, ease: "power4.out" }) : null;

        const move = (event: PointerEvent) => {
          const bounds = card.getBoundingClientRect();
          const px = (event.clientX - bounds.left) / bounds.width;
          const py = (event.clientY - bounds.top) / bounds.height;
          setGlowX(`${px * 100}%`);
          setGlowY(`${py * 100}%`);
          tiltX((py - 0.5) * -5);
          tiltY((px - 0.5) * 6);
          buttonX?.((px - 0.5) * 8);
          buttonRotate?.((px - 0.5) * 10);
        };

        const enter = () => {
          card.classList.add("is-hovering");
          iconScale?.(1.08);
        };

        const leave = () => {
          card.classList.remove("is-hovering");
          tiltX(0);
          tiltY(0);
          iconScale?.(1);
          buttonX?.(0);
          buttonRotate?.(0);
        };

        card.addEventListener("pointermove", move);
        card.addEventListener("pointerenter", enter);
        card.addEventListener("pointerleave", leave);
        cleanupHandlers.push(() => {
          card.removeEventListener("pointermove", move);
          card.removeEventListener("pointerenter", enter);
          card.removeEventListener("pointerleave", leave);
        });

        gsap.to(card, {
          yPercent: index % 2 === 0 ? -8 : -4,
          ease: "none",
          scrollTrigger: {
            trigger: section,
            start: "top bottom",
            end: "bottom top",
            scrub: true,
          },
        });
      });

      // Section-level parallax uses quickTo for smooth interpolation.
      const glowX = sceneGlow ? gsap.quickTo(sceneGlow, "x", { duration: 1.15, ease: "power4.out" }) : null;
      const glowY = sceneGlow ? gsap.quickTo(sceneGlow, "y", { duration: 1.15, ease: "power4.out" }) : null;
      const guitarX = guitarBody ? gsap.quickTo(guitarBody, "x", { duration: 1.1, ease: "power4.out" }) : null;
      const guitarY = guitarBody ? gsap.quickTo(guitarBody, "y", { duration: 1.1, ease: "power4.out" }) : null;
      const neckX = guitarNeck ? gsap.quickTo(guitarNeck, "x", { duration: 1.1, ease: "power4.out" }) : null;
      const signalX = signalLine ? gsap.quickTo(signalLine, "x", { duration: 1.25, ease: "power4.out" }) : null;

      const sectionMove = (event: PointerEvent) => {
        const bounds = section.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width - 0.5;
        const y = (event.clientY - bounds.top) / bounds.height - 0.5;
        glowX?.(x * 34);
        glowY?.(y * 24);
        guitarX?.(x * 18);
        guitarY?.(y * 12);
        neckX?.(x * 28);
        signalX?.(x * -16);
      };

      const sectionLeave = () => {
        glowX?.(0);
        glowY?.(0);
        guitarX?.(0);
        guitarY?.(0);
        neckX?.(0);
        signalX?.(0);
      };

      section.addEventListener("pointermove", sectionMove);
      section.addEventListener("pointerleave", sectionLeave);
      cleanupHandlers.push(() => {
        section.removeEventListener("pointermove", sectionMove);
        section.removeEventListener("pointerleave", sectionLeave);
      });
    }, section);

    return () => {
      cleanupHandlers.forEach((cleanup) => cleanup());
      ctx.revert();
    };
  }, []);

  useLayoutEffect(() => {
    const section = workflowRef.current;
    if (!section || prefersReducedMotion()) return;

    const ctx = gsap.context(() => {
      const q = gsap.utils.selector(section);
      const activeRow = q(".workflow-row.active");
      const copyTargets = q(".workflow-detail-copy h3, .workflow-detail-copy p");
      const chips = q(".workflow-detail-chips span");
      const graphLines = q(".workflow-graph-line");

      gsap.fromTo(
        activeRow,
        { backgroundColor: "rgba(240, 138, 69, 0.02)" },
        { backgroundColor: "rgba(240, 138, 69, 0.08)", duration: 0.55, ease: "sine.inOut" },
      );

      gsap.fromTo(
        copyTargets,
        { y: 18, autoAlpha: 0, filter: "blur(10px)" },
        { y: 0, autoAlpha: 1, filter: "blur(0px)", duration: 0.58, stagger: 0.07, ease: "power4.out" },
      );

      gsap.fromTo(
        chips,
        { y: 14, scale: 0.96, autoAlpha: 0 },
        { y: 0, scale: 1, autoAlpha: 1, duration: 0.52, stagger: 0.06, ease: "power4.out" },
      );

      gsap.fromTo(
        graphLines,
        { strokeDashoffset: 560 },
        { strokeDashoffset: 0, duration: 0.82, stagger: 0.08, ease: "expo.out" },
      );
    }, section);

    return () => ctx.revert();
  }, [activeWorkflowIndex]);

  return (
    <main className="landing-page">
      <section className="landing-hero cinematic-hero" ref={heroRef}>
        <div className="hero-background-depth" aria-hidden="true">
          <span className="hero-ambient-glow" />
          <span className="hero-studio-dust" />
          <span className="guitar-silhouette">
            <span className="guitar-sweep" />
          </span>
        </div>

        <div className="landing-hero-copy">
          <p className="landing-kicker">
            <span className="kicker-dot" />
            AI powered. Musician approved.
          </p>
          <h1 aria-label="Hear it. See it. Play it.">
            {["Hear it.", "See it.", "Play it."].map((line) => (
              <span className="hero-title-mask" key={line}>
                <span className="hero-title-line">{line}</span>
              </span>
            ))}
          </h1>
          <p className="landing-lede">
            MusicSheet Studio turns rough guitar recordings into clean notation, playable tabs, chord insight, and
            export-ready files with a focused studio workflow.
          </p>
          <div className="landing-actions">
            <Link to="/register" className="landing-primary">
              Start your first score
              <Icon name="arrow" />
            </Link>
            <Link to="/login" className="landing-secondary">
              Watch demo
              <span className="demo-play-dot">
                <Icon name="arrow" />
              </span>
            </Link>
          </div>
          <div className="landing-proof" aria-label="Studio highlights">
            {featurePills.map((pill) => (
              <span key={pill.label}>
                <Icon name={pill.icon} />
                {pill.label}
              </span>
            ))}
          </div>
        </div>

        <div className="landing-hero-visual" aria-label="Example transcription workflow">
          <div className="hero-light-ribbon" aria-hidden="true" />
          <div className="studio-card-parallax">
            <div className="studio-card-depth">
              <div className="studio-card-float">
                <div className="studio-card-breath">
                  <div className="studio-card">
                <div className="studio-card-header">
                  <span className="studio-mini-wave">
                    <Icon name="waveform" />
                  </span>
                  <div>
                    <div className="score-board-title">Midnight Riff Study</div>
                    <div className="score-board-topline">
                      <span>Em Standard Tuning</span>
                      <span>124 BPM</span>
                    </div>
                  </div>
                  <span className="studio-key-pill">
                    <Icon name="key" />
                    Key: Em
                  </span>
                </div>

                <div className="studio-waveform">
                  <span className="studio-timecode">00:07.42</span>
                  <span className="studio-playhead" />
                  {waveformBars.map((height, index) => (
                    <span
                      className="wave-bar"
                      key={index}
                      style={{ height: `${height}%` }}
                    />
                  ))}
                </div>

                <div className="studio-tab-grid">
                  <div className="tab-lines" aria-hidden="true">
                    {["e", "B", "G", "D", "A", "E"].map((label) => (
                      <span key={label}>{label}|--0---3---5---7---------------</span>
                    ))}
                  </div>
                  <div className="chord-box">
                    <strong>Em</strong>
                    <div className="chord-diagram" aria-hidden="true">
                      {Array.from({ length: 6 }, (_item, index) => (
                        <span key={`v-${index}`} />
                      ))}
                      {Array.from({ length: 5 }, (_item, index) => (
                        <i key={`h-${index}`} />
                      ))}
                      <b className="finger-one" />
                      <b className="finger-two" />
                      <b className="finger-three" />
                    </div>
                  </div>
                </div>

                <div className="studio-card-footer">
                  <button type="button" className="studio-play-button" aria-label="Play preview">
                    <Icon name="arrow" />
                  </button>
                  <div className="studio-progress">
                    <span />
                  </div>
                  <span className="studio-bpm-pill">124 BPM</span>
                </div>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div className="hero-bpm-card">
            <span className="bpm-glow-dot" aria-hidden="true" />
            <span>Detected</span>
            <strong>Em / 124 BPM</strong>
            <div className="mini-wave" aria-hidden="true">
              {waveformBars.slice(0, 28).map((height, index) => (
                <i key={index} style={{ height: `${Math.max(12, height * 0.52)}%` }} />
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="landing-services studio-workflow-section" id="features" ref={workflowRef}>
        <div className="workflow-capability-rail" aria-label="Core capabilities">
          <div className="workflow-capability-track">
            {[...capabilityRail, ...capabilityRail].map((item, index) => (
              <div className="workflow-capability-item" key={`${item.title}-${index}`}>
                <Icon name={item.icon} />
                <span>
                  <strong>{item.title}</strong>
                  <small>{item.subtitle}</small>
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="workflow-scene" aria-hidden="true">
          <span className="workflow-scene-glow" />
          <span className="workflow-guitar-body">
            <span className="workflow-string-sweep" />
          </span>
          <span className="workflow-guitar-neck" />
          <span className="workflow-signal-line" />
        </div>

        <div className="landing-section-heading workflow-hero-copy">
          <p>(How it works)</p>
          <h2>
            <span className="workflow-title-line">From signal to</span>
            <span className="workflow-title-line">sheet in one</span>
            <span className="workflow-title-line">
              <em className="workflow-focus-word">
                focused
                <span className="workflow-focus-sweep" aria-hidden="true" />
              </em>{" "}
              flow.
            </span>
          </h2>
          <p className="workflow-hero-lede">
            MusicSheet Studio analyzes your audio and turns it into clear, playable guitar music so you can practice
            smarter and create faster.
          </p>
        </div>

        <div className="service-grid workflow-step-grid">
          {services.map((service, index) => (
            <article
              key={service.title}
              className={`service-card workflow-step-card${activeWorkflowIndex === index ? " active" : ""}`}
            >
              <div className="service-card-label">
                <span>{service.label}</span>
                <Icon name={service.icon} />
              </div>
              <div className="workflow-step-icon">
                <Icon name={service.icon} />
              </div>
              <div>
                <h3>{service.title}</h3>
                <p>{service.text}</p>
              </div>
              <button
                type="button"
                className="workflow-step-arrow"
                aria-label={`Show ${service.title} workflow details`}
                aria-pressed={activeWorkflowIndex === index}
                onClick={() => setActiveWorkflowIndex(index)}
              >
                <Icon name="arrow" />
              </button>
            </article>
          ))}
        </div>

        <div className="landing-workflow workflow-detail-panel" id="how-it-works">
          <div className="workflow-panel-kicker">(Detailed workflow)</div>
          <div className="workflow-list">
            {workflow.map((step, index) => (
              <button
                type="button"
                key={step}
                className={`workflow-row${activeWorkflowIndex === index ? " active" : ""}`}
                onClick={() => setActiveWorkflowIndex(index)}
              >
                <span>{String(index + 1).padStart(2, "0")}</span>
                <strong>{step}</strong>
              </button>
            ))}
          </div>
          <div className="workflow-visual" data-step={activeWorkflowIndex} aria-hidden="true">
            <svg className="workflow-graph" viewBox="0 0 560 240" preserveAspectRatio="none">
              <defs>
                <filter id="workflowGraphGlow" x="-20%" y="-80%" width="140%" height="260%">
                  <feGaussianBlur stdDeviation="4" result="blur" />
                  <feMerge>
                    <feMergeNode in="blur" />
                    <feMergeNode in="SourceGraphic" />
                  </feMerge>
                </filter>
              </defs>
              <path
                className="workflow-graph-line primary"
                pathLength="560"
                d="M18 130 C88 72 140 174 208 112 S316 82 378 120 S474 154 542 104"
              />
              <path
                className="workflow-graph-line secondary"
                pathLength="560"
                d="M18 154 C84 108 144 142 208 134 S318 178 376 96 S476 62 542 86"
              />
              <path
                className="workflow-graph-line tertiary"
                pathLength="560"
                d="M18 176 C96 122 152 214 236 156 S354 138 420 168 S502 190 542 158"
              />
              <circle className="workflow-graph-particle" r="3.5" />
              <circle className="workflow-graph-particle" r="2.5" />
            </svg>
          </div>
          <div className="workflow-detail-copy">
            <h3>{activeWorkflow.title}</h3>
            <p>{activeWorkflow.text}</p>
            <div className="workflow-detail-chips">
              {activeWorkflow.chips.map((chip) => (
                <span key={chip.label}>
                  <Icon name={chip.icon} />
                  <strong>{chip.label}</strong>
                  <small>{chip.sublabel}</small>
                </span>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
};

export default LandingPage;
