import { useEffect, useState } from "react";
import {
  deleteSkill,
  importSkill,
  listSkills,
  revealSkillsFolder,
  type SkillInfo,
} from "../api";
import { chooseFolder } from "../tauri";
import { Icon } from "./Icon";
import { PanelHead } from "./IntegrationsView";

// The Skills panel: lists builtin + user skills, imports a SKILL.md folder via the
// universal folder picker, reveals the user skills folder, and deletes user skills.
// Builtins (docx/pptx/xlsx/pdf) are read-only; a user skill of the same name shadows one.
export function SkillsSection() {
  const [skills, setSkills] = useState<SkillInfo[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const refresh = () => listSkills().then(setSkills).catch(() => {});
  useEffect(() => {
    refresh();
  }, []);

  const onImport = async () => {
    setMsg(null);
    const path = await chooseFolder();
    if (!path) return;
    setBusy(true);
    const res = await importSkill(path);
    setBusy(false);
    if (res.ok) {
      setSkills(res.skills ?? []);
      setMsg({ kind: "ok", text: `Imported “${res.name}”.` });
    } else {
      setMsg({ kind: "err", text: res.error ?? "Import failed." });
    }
  };

  const onDelete = async (name: string) => {
    if (!confirm(`Remove the “${name}” skill? Its folder will be deleted.`)) return;
    const res = await deleteSkill(name);
    if (res.ok) setSkills(res.skills ?? []);
    else setMsg({ kind: "err", text: res.error ?? "Delete failed." });
  };

  const builtins = skills.filter((s) => s.source === "builtin");
  const userSkills = skills.filter((s) => s.source === "user");

  return (
    <section>
      <PanelHead
        title="Skills"
        sub="Reusable instructions the coworker loads on demand (Anthropic SKILL.md format). Skills written for Claude Desktop or Claude Code work here too."
      />

      <div className="flex items-center gap-2 mb-4">
        <button
          className="text-[12.5px] px-3 py-2 rounded-lg bg-accent text-white shrink-0 disabled:opacity-40 flex items-center gap-1.5"
          onClick={onImport}
          disabled={busy}
        >
          <Icon name="plus" size={14} /> Import skill…
        </button>
        <button
          className="text-[12.5px] px-3 py-2 rounded-lg border border-line bg-paper hover:border-lineStrong shrink-0 flex items-center gap-1.5"
          onClick={() => revealSkillsFolder()}
        >
          <Icon name="folder" size={14} /> Open skills folder
        </button>
      </div>

      {msg && (
        <div
          className={
            "text-[12.5px] mb-4 px-3 py-2 rounded-lg border " +
            (msg.kind === "ok"
              ? "border-line bg-panel text-ink"
              : "border-red-300 bg-red-50 text-red-700")
          }
        >
          {msg.text}
        </div>
      )}

      {userSkills.length > 0 && (
        <SkillGroup label="Your skills">
          {userSkills.map((s) => (
            <SkillRow key={s.name} skill={s} onDelete={() => onDelete(s.name)} />
          ))}
        </SkillGroup>
      )}

      <SkillGroup label="Builtin">
        {builtins.map((s) => (
          <SkillRow key={s.name} skill={s} />
        ))}
      </SkillGroup>

      <p className="text-[12px] text-muted mt-5 leading-relaxed">
        A skill is a folder with a <code>SKILL.md</code> file (YAML frontmatter:{" "}
        <code>name</code>, <code>description</code>). Drop folders straight into the skills
        folder above, or Import one — changes apply to new sessions immediately, no restart.
        A user skill named the same as a builtin overrides it.
      </p>
    </section>
  );
}

function SkillGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted mb-2">
        {label}
      </div>
      <div className="rounded-xl2 border border-line bg-panel divide-y divide-line">
        {children}
      </div>
    </div>
  );
}

function SkillRow({ skill, onDelete }: { skill: SkillInfo; onDelete?: () => void }) {
  return (
    <div className="flex items-start gap-3 px-3.5 py-3">
      <div className="mt-0.5 text-muted shrink-0">
        <Icon name="file" size={16} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="text-[13px] font-medium text-ink">{skill.name}</div>
        <div className="text-[12px] text-muted leading-relaxed">{skill.description}</div>
      </div>
      {onDelete ? (
        <button
          className="text-muted hover:text-red-600 shrink-0 p-1"
          title="Remove skill"
          onClick={onDelete}
        >
          <Icon name="trash" size={15} />
        </button>
      ) : (
        <span className="text-[11px] text-muted shrink-0 mt-0.5">builtin</span>
      )}
    </div>
  );
}
