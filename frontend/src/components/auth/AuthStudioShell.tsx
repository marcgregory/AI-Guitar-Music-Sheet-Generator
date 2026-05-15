import { useLayoutEffect, useRef, type ReactNode } from "react";
import { Link } from "react-router-dom";
import gsap from "gsap";
import { Icon } from "../Icon";

const authHighlights = [
  { title: "AI transcription", subtitle: "Accurate & reliable", icon: "waveform" as const },
  { title: "Tab clarity", subtitle: "Clean & easy to read", icon: "key" as const },
  { title: "Export ready", subtitle: "MIDI, MusicXML, TAB", icon: "download" as const },
  { title: "Practice smarter", subtitle: "Improve with insights", icon: "gauge" as const },
];

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type AuthStudioShellProps = {
  children: ReactNode;
  eyebrow: string;
  formSubtitle: string;
  formTitle: string;
  heroSubtitle: string;
};

export const AuthStudioShell = ({
  children,
  eyebrow,
  formSubtitle,
  formTitle,
  heroSubtitle,
}: AuthStudioShellProps) => {
  const shellRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const shell = shellRef.current;
    if (!shell || prefersReducedMotion()) return;

    let removePointerListeners: (() => void) | undefined;

    const ctx = gsap.context(() => {
      const q = gsap.utils.selector(shell);
      const heroGlow = q(".auth-hero-glow")[0] as HTMLElement | undefined;
      const waveform = q(".auth-wavefield")[0] as HTMLElement | undefined;
      const formCard = q(".auth-form-panel")[0] as HTMLElement | undefined;

      const intro = gsap.timeline({ defaults: { ease: "power4.out" } });
      intro
        .fromTo(q(".cinematic-auth-shell"), { autoAlpha: 0, y: 34 }, { autoAlpha: 1, y: 0, duration: 1.05 }, 0)
        .fromTo(
          q(".auth-brand, .auth-title-line, .auth-subtitle, .auth-highlight"),
          { autoAlpha: 0, y: 28, filter: "blur(14px)" },
          { autoAlpha: 1, y: 0, filter: "blur(0px)", duration: 0.9, stagger: 0.08 },
          0.14,
        )
        .fromTo(
          q(".auth-portal-outline"),
          { autoAlpha: 0, scale: 0.92, x: -24 },
          { autoAlpha: 1, scale: 1, x: 0, duration: 1.2, ease: "expo.out" },
          0.24,
        )
        .fromTo(
          q(".auth-form-panel"),
          { autoAlpha: 0, x: 42, scale: 0.97, filter: "blur(16px)" },
          { autoAlpha: 1, x: 0, scale: 1, filter: "blur(0px)", duration: 1.05 },
          0.34,
        )
        .fromTo(
          q(".auth-form-panel h2, .auth-form-panel > p, .auth-form .form-group, .auth-form-options, .submit-button, .auth-divider, .auth-social-button, .auth-footer, .error-message"),
          { autoAlpha: 0, y: 18 },
          { autoAlpha: 1, y: 0, duration: 0.72, stagger: 0.055 },
          0.62,
        );

      gsap.to(q(".auth-wave-line"), {
        xPercent: 7,
        y: () => gsap.utils.random(-8, 8),
        duration: () => gsap.utils.random(4.5, 7.2),
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
        stagger: 0.18,
      });

      gsap.to(q(".auth-hero-glow"), {
        scale: 1.05,
        opacity: 0.82,
        duration: 5.8,
        ease: "sine.inOut",
        yoyo: true,
        repeat: -1,
      });

      gsap.to(q(".auth-portal-sweep"), {
        xPercent: 160,
        duration: 6.2,
        ease: "sine.inOut",
        repeat: -1,
        repeatDelay: 1.4,
      });

      const glowX = heroGlow ? gsap.quickTo(heroGlow, "x", { duration: 1.2, ease: "power4.out" }) : null;
      const glowY = heroGlow ? gsap.quickTo(heroGlow, "y", { duration: 1.2, ease: "power4.out" }) : null;
      const waveX = waveform ? gsap.quickTo(waveform, "x", { duration: 1.4, ease: "power4.out" }) : null;
      const cardY = formCard ? gsap.quickTo(formCard, "y", { duration: 1, ease: "power4.out" }) : null;

      const move = (event: PointerEvent) => {
        const bounds = shell.getBoundingClientRect();
        const x = (event.clientX - bounds.left) / bounds.width - 0.5;
        const y = (event.clientY - bounds.top) / bounds.height - 0.5;
        glowX?.(x * 22);
        glowY?.(y * 18);
        waveX?.(x * -18);
        cardY?.(y * 8);
      };

      const leave = () => {
        glowX?.(0);
        glowY?.(0);
        waveX?.(0);
        cardY?.(0);
      };

      shell.addEventListener("pointermove", move);
      shell.addEventListener("pointerleave", leave);
      removePointerListeners = () => {
        shell.removeEventListener("pointermove", move);
        shell.removeEventListener("pointerleave", leave);
      };
    }, shell);

    return () => {
      removePointerListeners?.();
      ctx.revert();
    };
  }, []);

  return (
    <div className="auth-page cinematic-auth-page" ref={shellRef}>
      <div className="auth-container cinematic-auth-shell">
        <aside className="auth-header cinematic-auth-hero">
          <div className="auth-hero-glow" aria-hidden="true" />
          <div className="auth-portal-outline" aria-hidden="true">
            <span className="auth-portal-sweep" />
          </div>
          <div className="auth-wavefield" aria-hidden="true">
            {Array.from({ length: 9 }, (_item, index) => (
              <span className="auth-wave-line" key={index} />
            ))}
          </div>

          <div className="auth-topbar">
            <Link to="/" className="auth-brand" aria-label="Guitar AI Studio home">
              <Icon name="music" />
              <span>{eyebrow}</span>
            </Link>
            <Link to="/" className="auth-home-link">
              <Icon name="arrow" />
              <span>Back to home</span>
            </Link>
          </div>

          <h1 aria-label="Music Sheet Generator">
            <span className="auth-title-line">Music</span>
            <span className="auth-title-line">Sheet</span>
            <em className="auth-title-line">Generator</em>
          </h1>
          <p className="auth-subtitle">{heroSubtitle}</p>

          <div className="auth-highlight-rail" aria-label="Studio benefits">
            {authHighlights.map((highlight) => (
              <span className="auth-highlight" key={highlight.title}>
                <Icon name={highlight.icon} />
                <strong>{highlight.title}</strong>
                <small>{highlight.subtitle}</small>
              </span>
            ))}
          </div>
        </aside>

        <section className="auth-form-panel" aria-labelledby="auth-form-title">
          <div className="auth-security-pill">
            <Icon name="check" />
            Secure & private
          </div>
          <h2 id="auth-form-title">{formTitle}</h2>
          <p>{formSubtitle}</p>
          {children}
        </section>
      </div>
    </div>
  );
};
