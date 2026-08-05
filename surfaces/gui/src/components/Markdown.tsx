import { useMemo, useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";
import hljs from "highlight.js/lib/common";
import { Icon } from "./Icon";
import { useSmoothStream } from "../useSmoothStream";

// §34 (UX-016): the agent ends a deliverable turn with plain markdown —
// [Title](artifact:relative/path) — and the renderer turns it into a chip that opens the
// artifact viewer in place. Plumbing is a window event (the viewer lives in RightRail;
// this component renders deep inside the transcript): RightRail resolves the path against
// the session's artifact list, App un-hides the rail.
export const OPEN_ARTIFACT_EVENT = "ocw-open-artifact";

// Markdown escapes spaces and parens in a link target, so `artifact:` hrefs arrive
// percent-encoded ("Deck%20%28final%29.pptx"). The server accepts either form; the chip
// shows the readable one. Decoding can throw on a stray "%", hence the fallback.
function prettyPath(path: string): string {
  try {
    return decodeURIComponent(path);
  } catch {
    return path;
  }
}

function ArtifactChip({ path, title }: { path: string; title: string }) {
  const pretty = prettyPath(path);
  const file = pretty.split("/").pop() || pretty;
  return (
    <button
      className="art-chip"
      data-testid="artifact-chip"
      title={pretty}
      onClick={() =>
        window.dispatchEvent(new CustomEvent(OPEN_ARTIFACT_EVENT, { detail: { path } }))
      }
    >
      <span className="art-chip-ico">
        <Icon name="file" size={14} />
      </span>
      <span className="art-chip-meta">
        <b>{title || file}</b>
        {title && title !== file && <span>{file}</span>}
      </span>
      <span className="art-chip-open">Open ›</span>
    </button>
  );
}

// Language ids we show a friendlier label for; anything else prints as written.
const LANG_LABEL: Record<string, string> = {
  js: "JavaScript",
  javascript: "JavaScript",
  ts: "TypeScript",
  typescript: "TypeScript",
  jsx: "JSX",
  tsx: "TSX",
  py: "Python",
  python: "Python",
  rb: "Ruby",
  rs: "Rust",
  sh: "Shell",
  bash: "Shell",
  zsh: "Shell",
  json: "JSON",
  yml: "YAML",
  yaml: "YAML",
  md: "Markdown",
  sql: "SQL",
  html: "HTML",
  css: "CSS",
};

// A fenced code block with the chrome Claude Desktop has: a header carrying the language
// and a copy button, then the highlighted body. Highlighting is explicit-language only —
// `highlightAuto` costs real time and guesses badly, and this re-runs on every streaming
// delta while a block is still being written. Token colors come from our own palette
// (styles.css) rather than a highlight.js theme, so both themes stay correct.
function CodeBlock({ className, raw }: { className?: string; raw: string }) {
  const [copied, setCopied] = useState(false);
  const lang = (/language-([\w-]+)/.exec(className || "")?.[1] || "").toLowerCase();
  const body = raw.replace(/\n$/, "");
  const html = useMemo(() => {
    if (!lang || !hljs.getLanguage(lang)) return null;
    try {
      return hljs.highlight(body, { language: lang, ignoreIllegals: true }).value;
    } catch {
      return null;
    }
  }, [body, lang]);

  const copy = () => {
    // Same rule as the message copy button: only claim success once the write lands.
    navigator.clipboard
      ?.writeText(body)
      .then(() => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1200);
      })
      .catch(() => {});
  };

  return (
    <div className="codeblock" data-testid="codeblock">
      <div className="codeblock-head">
        <span className="codeblock-lang">{LANG_LABEL[lang] || lang || "text"}</span>
        <button
          className="codeblock-copy"
          data-testid="codeblock-copy"
          title="Copy code"
          onClick={copy}
        >
          {copied ? "Copied" : <Icon name="copy" size={12} />}
        </button>
      </div>
      <pre>
        {html !== null ? (
          <code className="hljs" dangerouslySetInnerHTML={{ __html: html }} />
        ) : (
          <code className="hljs">{body}</code>
        )}
      </pre>
    </div>
  );
}

// Assistant messages rendered as GitHub-flavored markdown (headings, lists, tables, code,
// links). Links open externally — never navigate the app shell — except artifact: links,
// which open the session's artifact viewer.
//
// `streaming` adds the class that fades each block in as it arrives. The animation fires on
// DOM insertion, so it lands exactly once per genuinely-new block: React mutates the trailing
// paragraph in place as it grows (no re-animation) and mounts a fresh node when the model
// starts the next one.
export function Markdown({ text, streaming }: { text: string; streaming?: boolean }) {
  return (
    <div className={"md" + (streaming ? " md-stream" : "")}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        // artifact: is ours — keep it through the sanitizer (everything else gets the default
        // http/https/mailto policy).
        urlTransform={(url) => (url.startsWith("artifact:") ? url : defaultUrlTransform(url))}
        components={{
          a: ({ node: _n, href, children, ...props }) => {
            if (href?.startsWith("artifact:")) {
              const title = Array.isArray(children) ? children.join("") : String(children ?? "");
              return <ArtifactChip path={href.slice("artifact:".length)} title={title} />;
            }
            return (
              <a href={href} {...props} target="_blank" rel="noreferrer">
                {children}
              </a>
            );
          },
          // react-markdown v10 dropped the `inline` prop on `code`, so the block case is
          // taken here at the `pre` wrapper and the inner `code` element is never rendered;
          // inline code keeps the default `<code>` and its own styling.
          pre: ({ children }) => {
            const child: any = Array.isArray(children) ? children[0] : children;
            const props = child?.props ?? {};
            const raw = Array.isArray(props.children)
              ? props.children.join("")
              : String(props.children ?? "");
            return <CodeBlock className={props.className} raw={raw} />;
          },
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

// The live half of an answer: paced by `useSmoothStream`, block-faded by `.md-stream`, and
// carrying the caret that `.md-stream` parks at the end of the last block. Both places that
// render streamed assistant text — the answer bubble in App and the quiet line inside a live
// TurnGroup — go through this, so the two can't drift apart.
export function StreamingMarkdown({ text }: { text: string }) {
  return <Markdown text={useSmoothStream(text, true)} streaming />;
}
