// A persona is "project-scoped" only when it's code-family: an explicit directory the user
// picks, sessions grouped by project in the sidebar. Everything else (knowledge, chat) runs on
// a transparent per-conversation scratch dir, with real folders added as roots when needed —
// no folder gate, ever. (The old workspace enum — git/project/deliverable/none — collapsed
// into family; owner decision 2026-07-03, UX-DECISIONS §16.)
export function isProjectScoped(p?: { workspace?: string; family?: string }): boolean {
  return p?.family === "code";
}

// Persona naming: the two first-party surfaces are "OpenWorker" (agentic) and "OpenChat"
// (direct chat); third-party personas stay a "Coworker" family (Ops Coworker, …). In
// lists/chrome we use the SHORT label; the persona detail page uses the FULL family name.
// Backend names are left untouched; this is purely the display layer.

// Short label for the sidebar + top bar: "OpenWorker" / "OpenChat" / "Code" / "Ops".
export function shortPersonaName(name?: string, id?: string): string {
  if (id === "cowork") return "OpenWorker";
  const n = (name || id || "").trim();
  return n.replace(/\s*coworker$/i, "").trim() || n;
}

// Full family name for the persona detail page: "OpenWorker" / "Code Coworker" /
// "Ops Coworker". OpenChat isn't a coworker — left as-is.
export function fullPersonaName(name?: string, id?: string): string {
  if (id === "cowork") return "OpenWorker";
  const n = (name || id || "").trim();
  if (id === "chat" || !n) return n;
  return /coworker$/i.test(n) ? n : `${n} Coworker`;
}
