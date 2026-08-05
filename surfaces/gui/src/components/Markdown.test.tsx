import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Markdown, OPEN_ARTIFACT_EVENT } from "./Markdown";

afterEach(cleanup);

// §34 (UX-016): [Title](artifact:path) renders as a chip that opens the artifact viewer via
// a window event; ordinary links keep the open-externally treatment.
describe("Markdown artifact links", () => {
  it("renders an artifact: link as a chip and dispatches the open event with the path", () => {
    const seen: string[] = [];
    const listener = (e: Event) => seen.push((e as CustomEvent).detail.path);
    window.addEventListener(OPEN_ARTIFACT_EVENT, listener);

    render(<Markdown text="Done — [Semiconductor dashboard](artifact:reports/semi.html)" />);
    const chip = screen.getByTestId("artifact-chip");
    expect(chip.textContent).toContain("Semiconductor dashboard");
    expect(chip.textContent).toContain("semi.html"); // filename shown under the title
    fireEvent.click(chip);
    expect(seen).toEqual(["reports/semi.html"]);

    window.removeEventListener(OPEN_ARTIFACT_EVENT, listener);
  });

  it("ordinary links stay external and never become chips", () => {
    const { container } = render(<Markdown text="see [the docs](https://example.com)" />);
    expect(screen.queryByTestId("artifact-chip")).toBeNull();
    const a = container.querySelector("a")!;
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("href")).toBe("https://example.com");
  });

  it("chip title falls back to the filename when the link text is empty", () => {
    vi.spyOn(window, "dispatchEvent");
    render(<Markdown text="[](artifact:out/report.pdf)" />);
    expect(screen.getByTestId("artifact-chip").textContent).toContain("report.pdf");
  });
});

// Fenced code gets the Claude-Desktop chrome: a language header, a copy button, and
// highlight.js tokens colored from our own palette.
describe("Markdown code blocks", () => {
  const fence = (lang: string, body: string) => "```" + lang + "\n" + body + "\n```";

  it("labels the language and highlights a known one", () => {
    const { container } = render(<Markdown text={fence("python", "x = 1")} />);
    expect(screen.getByTestId("codeblock")).toBeTruthy();
    expect(container.querySelector(".codeblock-lang")!.textContent).toBe("Python");
    // hljs emits token spans; the raw source must still read back verbatim.
    const code = container.querySelector(".codeblock pre code")!;
    expect(code.querySelector(".hljs-keyword, .hljs-number")).toBeTruthy();
    expect(code.textContent).toBe("x = 1");
  });

  it("renders an unknown or absent language as plain text without dropping content", () => {
    const { container } = render(<Markdown text={fence("", "just words")} />);
    expect(container.querySelector(".codeblock-lang")!.textContent).toBe("text");
    expect(container.querySelector(".codeblock pre code")!.textContent).toBe("just words");
    expect(container.querySelector(".hljs-keyword")).toBeNull();
  });

  it("copies the block's source, and only claims success once the write lands", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    render(<Markdown text={fence("js", "const a = 1;")} />);
    fireEvent.click(screen.getByTestId("codeblock-copy"));
    expect(writeText).toHaveBeenCalledWith("const a = 1;");
    await screen.findByText("Copied");
  });

  it("inline code is left alone — no block chrome", () => {
    const { container } = render(<Markdown text="use `npm run dev` to start" />);
    expect(screen.queryByTestId("codeblock")).toBeNull();
    expect(container.querySelector("code")!.textContent).toBe("npm run dev");
  });

  it("marks streamed content so the block-reveal + caret styles apply", () => {
    const { container, rerender } = render(<Markdown text="hi" streaming />);
    expect(container.querySelector(".md.md-stream")).toBeTruthy();
    rerender(<Markdown text="hi" />);
    expect(container.querySelector(".md-stream")).toBeNull();
  });
});
