import { useEffect } from "react";

/** Scroll-in reveals for [data-reveal] elements. Adds .is-revealed when the
 *  element first enters the viewport. No-ops under reduced motion or in
 *  environments without IntersectionObserver (tests). */
export function useReveal() {
  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      for (const el of document.querySelectorAll("[data-reveal]")) {
        el.classList.add("is-revealed");
      }
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-revealed");
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -8% 0px" },
    );
    for (const el of document.querySelectorAll("[data-reveal]")) {
      observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);
}
