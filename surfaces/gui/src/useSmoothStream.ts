import { useEffect, useRef, useState } from "react";

// Smooth out the model's delivery. Providers emit deltas in lumpy bursts — a few characters,
// then 300ms of nothing, then a whole paragraph — which reads as text *jumping* onto the
// screen. This releases the buffered text at a steady per-frame rate instead, the way Claude
// Desktop reads: words flow, and each new block fades in as it lands (see `.md-stream`).
//
// The rate is proportional to the backlog, so a burst drains faster than a trickle and the
// render never falls meaningfully behind the model. Two invariants matter more than the feel:
//
//   1. Nothing is ever withheld at the end. When `active` goes false the full text snaps in
//      on the same render — a finished turn must never sit half-shown.
//   2. A shrinking target (new turn, retry, interrupt) resets rather than rewinding
//      character by character.
const MIN_CHARS_PER_FRAME = 2;
const BACKLOG_DIVISOR = 6; // ~60fps → drains a 600-char burst in about 0.6s

export function useSmoothStream(target: string, active: boolean): string {
  const [shown, setShown] = useState(target.length);
  const shownRef = useRef(shown);
  shownRef.current = shown;
  const frame = useRef(0);

  useEffect(() => {
    // Finished (or never started): show everything, immediately.
    if (!active) {
      if (shownRef.current !== target.length) setShown(target.length);
      return;
    }
    // The stream restarted or was truncated — don't animate backwards.
    if (shownRef.current > target.length) {
      setShown(target.length);
      return;
    }
    if (shownRef.current === target.length) return;

    const step = () => {
      const backlog = target.length - shownRef.current;
      if (backlog <= 0) return;
      const advance = Math.max(MIN_CHARS_PER_FRAME, Math.ceil(backlog / BACKLOG_DIVISOR));
      setShown(Math.min(target.length, shownRef.current + advance));
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => cancelAnimationFrame(frame.current);
  }, [target, active]);

  return active ? target.slice(0, shown) : target;
}
