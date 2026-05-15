import { useLayoutEffect } from "react";
import { useLocation } from "react-router-dom";
import gsap from "gsap";
import { ScrollTrigger } from "gsap/ScrollTrigger";

gsap.registerPlugin(ScrollTrigger);

const prefersReducedMotion = () =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const MotionDirector = () => {
  const location = useLocation();

  useLayoutEffect(() => {
    if (prefersReducedMotion()) return;
    const isLandingPage = location.pathname === "/";

    const ctx = gsap.context(() => {
      if (!isLandingPage) {
        gsap.fromTo(
          ".site-nav",
          { y: -18, opacity: 0 },
          { y: 0, opacity: 1, duration: 0.7, ease: "power3.out" },
        );
      }

      gsap.fromTo(
        [
          ".auth-container",
          ".dashboard-content",
          ".audio-upload-header",
          ".audio-upload-tabs",
          ".file-upload-section",
          ".youtube-upload-section",
          ".processing-status-header",
          ".processing-status-content",
          ".transcription-viewer-header",
          ".transcription-viewer-content",
          ".transcription-footer",
        ].join(","),
        { y: 28, opacity: 0, filter: "blur(10px)" },
        {
          y: 0,
          opacity: 1,
          filter: "blur(0px)",
          duration: 0.9,
          stagger: 0.08,
          ease: "expo.out",
        },
      );

      gsap.fromTo(
        ".stat-card, .project-card, .project-list-item, .quick-action-button, .form-group, .selected-file, .alert",
        { y: 18, opacity: 0 },
        {
          y: 0,
          opacity: 1,
          duration: 0.72,
          stagger: 0.045,
          ease: "power3.out",
          delay: 0.12,
        },
      );
    });

    return () => ctx.revert();
  }, [location.pathname]);

  useLayoutEffect(() => {
    if (prefersReducedMotion()) return;
    if (location.pathname === "/") return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ".landing-kicker, .landing-hero h1, .landing-lede, .landing-actions, .landing-proof",
        { y: 34, opacity: 0, filter: "blur(12px)" },
        {
          y: 0,
          opacity: 1,
          filter: "blur(0px)",
          duration: 1,
          stagger: 0.08,
          ease: "expo.out",
        },
      );

      gsap.fromTo(
        ".landing-hero-visual",
        { x: 44, rotateY: -10, opacity: 0 },
        { x: 0, rotateY: 0, opacity: 1, duration: 1.15, ease: "expo.out", delay: 0.18 },
      );

      gsap.to(".landing-score-board", {
        yPercent: -10,
        rotateZ: -1.4,
        ease: "none",
        scrollTrigger: {
          trigger: ".landing-hero",
          start: "top top",
          end: "bottom top",
          scrub: 0.8,
        },
      });

      gsap.to(".hero-signal", {
        yPercent: 34,
        xPercent: -8,
        ease: "none",
        scrollTrigger: {
          trigger: ".landing-hero",
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });

      gsap.to(".hero-cue-card", {
        yPercent: -42,
        xPercent: 12,
        ease: "none",
        scrollTrigger: {
          trigger: ".landing-hero",
          start: "top top",
          end: "bottom top",
          scrub: true,
        },
      });

      gsap.utils.toArray<HTMLElement>(".landing-section-heading, .workflow-heading").forEach((element) => {
        gsap.fromTo(
          element.children,
          { y: 42, opacity: 0 },
          {
            y: 0,
            opacity: 1,
            duration: 0.9,
            stagger: 0.12,
            ease: "power3.out",
            scrollTrigger: {
              trigger: element,
              start: "top 76%",
            },
          },
        );
      });

      gsap.utils.toArray<HTMLElement>(".service-card, .workflow-row").forEach((element, index) => {
        gsap.fromTo(
          element,
          { y: 54, opacity: 0, clipPath: "inset(0 0 100% 0)" },
          {
            y: 0,
            opacity: 1,
            clipPath: "inset(0 0 0% 0)",
            duration: 0.9,
            delay: (index % 4) * 0.06,
            ease: "expo.out",
            scrollTrigger: {
              trigger: element,
              start: "top 82%",
            },
          },
        );
      });
    });

    return () => ctx.revert();
  }, [location.pathname]);

  return null;
};

export default MotionDirector;
