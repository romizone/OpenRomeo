import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useSmoothStream } from "./useSmoothStream";

// Drive requestAnimationFrame by hand so the pacing is deterministic.
let frames: FrameRequestCallback[] = [];
beforeEach(() => {
  frames = [];
  vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
    frames.push(cb);
    return frames.length;
  });
  vi.stubGlobal("cancelAnimationFrame", () => {});
});
afterEach(() => vi.unstubAllGlobals());

const tick = (n = 1) => {
  for (let i = 0; i < n; i++) {
    const pending = frames;
    frames = [];
    act(() => pending.forEach((cb) => cb(0)));
  }
};

describe("useSmoothStream", () => {
  it("releases a burst progressively instead of all at once", () => {
    const text = "x".repeat(600);
    const { result, rerender } = renderHook(
      ({ t, a }) => useSmoothStream(t, a),
      { initialProps: { t: "", a: true } },
    );
    rerender({ t: text, a: true });
    tick();
    const first = result.current.length;
    expect(first).toBeGreaterThan(0);
    expect(first).toBeLessThan(text.length); // not dumped in one frame
    tick(3);
    expect(result.current.length).toBeGreaterThan(first); // and it keeps catching up
    expect(text.startsWith(result.current)).toBe(true); // always a clean prefix
  });

  it("snaps to the full text the moment streaming ends — nothing is ever withheld", () => {
    const text = "y".repeat(500);
    const { result, rerender } = renderHook(
      ({ t, a }) => useSmoothStream(t, a),
      { initialProps: { t: "", a: true } },
    );
    rerender({ t: text, a: true });
    tick();
    expect(result.current.length).toBeLessThan(text.length);
    rerender({ t: text, a: false });
    expect(result.current).toBe(text);
  });

  it("a shorter target (new turn / interrupt) resets rather than rewinding", () => {
    const { result, rerender } = renderHook(
      ({ t, a }) => useSmoothStream(t, a),
      { initialProps: { t: "a".repeat(400), a: true } },
    );
    tick(20);
    rerender({ t: "fresh", a: true });
    tick();
    expect(result.current).toBe("fresh");
  });

  it("is a pass-through when nothing is streaming", () => {
    const { result } = renderHook(() => useSmoothStream("already done", false));
    expect(result.current).toBe("already done");
  });
});
