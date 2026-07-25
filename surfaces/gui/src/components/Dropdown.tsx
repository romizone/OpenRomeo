import { useState } from "react";
import { Icon } from "./Icon";

export interface Option {
  value: string;
  label: string;
  description?: string;
}

interface Props {
  prefix?: string;
  value: string;
  options: Option[];
  onChange: (value: string) => void;
  align?: "left" | "right";
  // Extra classes appended to the trigger pill (e.g. "chip" for a bordered composer-head chip).
  className?: string;
  // Fixed trigger text that HIDES the current value (owner ask 2026-07-25: the model chip
  // shows a neutral "Model" — the menu's ✓ is where the active choice reads). The tooltip
  // matches so the value doesn't leak on hover.
  triggerLabel?: string;
  // Stable hook for tests — the visible text is no longer unique once triggerLabel is set.
  testId?: string;
}

export function Dropdown({ prefix, value, options, onChange, align = "left", className, triggerLabel, testId }: Props) {
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value);
  const label = triggerLabel ?? (prefix ? `${prefix}: ` : "") + (current?.label || value);
  return (
    <div className="dd">
      <button
        className={"pill" + (className ? " " + className : "")}
        onClick={() => setOpen((v) => !v)}
        title={label}
        data-testid={testId}
      >
        <span className="pill-label">{label}</span>
        <Icon name="chevronDown" size={13} className="caret" />
      </button>
      {open && (
        <>
          <div className="dd-backdrop" onClick={() => setOpen(false)} />
          <div className={"dd-menu " + align}>
            {options.map((o) => (
              <div
                key={o.value}
                className={"dd-item" + (o.value === value ? " sel" : "")}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
              >
                <div className="dd-label">
                  {o.label}
                  {o.value === value && <span className="chk">✓</span>}
                </div>
                {o.description && <div className="dd-desc">{o.description}</div>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
