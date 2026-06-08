import type { ReactNode } from "react";

export function TabsShell({ children }: { children: ReactNode }) {
  return <div className="tabs">{children}</div>;
}

export function TabButton({
  id,
  panelId,
  active,
  onClick,
  children,
}: {
  id: string;
  panelId: string;
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      role="tab"
      id={id}
      className={`tab-btn ${active ? "active" : ""}`}
      aria-selected={active}
      aria-controls={panelId}
      tabIndex={active ? 0 : -1}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function TabPanel({
  id,
  labelledBy,
  active,
  children,
}: {
  id: string;
  labelledBy: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <div id={id} role="tabpanel" aria-labelledby={labelledBy} hidden={!active} className="tab-panel">
      {children}
    </div>
  );
}
