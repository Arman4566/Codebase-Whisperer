import { useEffect, useState } from "react";

export function useMedia(query) {
  const [m, setM] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const h = () => setM(mq.matches);
    mq.addEventListener("change", h);
    h();
    return () => mq.removeEventListener("change", h);
  }, [query]);
  return m;
}

/** Three linked stars: the product mark. */
export function Glyph({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" className="glyph">
      <path d="M4.5 17 11 6.5 19.5 14" fill="none" stroke="currentColor" strokeWidth="1" opacity=".55" />
      <circle cx="4.5" cy="17" r="2" fill="currentColor" />
      <circle cx="11" cy="6.5" r="2.6" fill="var(--gold)" />
      <circle cx="19.5" cy="14" r="1.6" fill="currentColor" />
    </svg>
  );
}

const ICONS = {
  ask: <path d="M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v6a2.5 2.5 0 0 1-2.5 2.5H11l-4 3.5V15h-.5A2.5 2.5 0 0 1 4 12.5z" />,
  repos: <><circle cx="6" cy="7" r="2" /><circle cx="17" cy="6" r="1.5" /><circle cx="12" cy="17" r="2.5" /><path d="M7.7 8.2 10.8 15M15.7 7.2 13.2 14.9" /></>,
  guide: <path d="M12 6.5C10.3 5.2 8 4.8 5 5v12c3-.2 5.3.2 7 1.5 1.7-1.3 4-1.7 7-1.5V5c-3-.2-5.3.2-7 1.5zM12 6.5v12" />,
  actions: <><circle cx="12" cy="12" r="8" /><path d="m8.5 12.2 2.4 2.4 4.6-5" /></>,
  explore: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4.2-4.2M11 8.5v5M8.5 11h5" /></>,
  sync: <path d="M19 8a7.5 7.5 0 0 0-13-1.5M5 4v3.5h3.5M5 16a7.5 7.5 0 0 0 13 1.5M19 20v-3.5h-3.5" />,
};
export function Icon({ name }) {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

export function Segmented({ value, onChange, options, label }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button key={o} type="button" role="radio" aria-checked={value === o} className={value === o ? "on" : ""} onClick={() => onChange(o)}>
          {o}
        </button>
      ))}
    </div>
  );
}

export function Reading({ children }) {
  return (
    <div className="reading" role="status">
      <p>
        <span className="pulse" aria-hidden="true" />
        {children}
      </p>
      <span className="bar" style={{ width: "86%" }} />
      <span className="bar" style={{ width: "64%" }} />
      <span className="bar" style={{ width: "74%" }} />
    </div>
  );
}

export function Toasts({ items }) {
  return (
    <div className="toasts" role="status" aria-live="polite">
      {items.map((t) => (
        <div key={t.id} className={"toast " + (t.kind || "")}>{t.text}</div>
      ))}
    </div>
  );
}
