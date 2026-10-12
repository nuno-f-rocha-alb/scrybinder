/* Collapsible navigation sidebar (original implementation, CSS transitions only).
   Collapsing keeps the icons; labels fade out. Groups hold sub-items and fold away when the bar is collapsed. */
import * as React from "react";
import { IconChevronRight, IconLayoutSidebarLeftCollapse, IconLayoutSidebarLeftExpand } from "@tabler/icons-react";

const cx = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(" ");
const Ctx = React.createContext({ collapsed: false, toggle: () => {} });
export const useSidebar = () => React.useContext(Ctx);

const ROW = "group relative flex w-full cursor-pointer items-center gap-2.5 rounded-[10px] px-3 py-[9px] text-[13.5px] font-medium leading-none outline-none select-none whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:ring-accent";
const ICON_BTN = "flex items-center justify-center rounded-lg text-mute hover:bg-raised hover:text-ink cursor-pointer";

export function Sidebar({ width = 232, collapsedWidth = 64, children }: { width?: number; collapsedWidth?: number; children: React.ReactNode }) {
  const [collapsed, setCollapsed] = React.useState(() => {
    try { return localStorage.getItem("scrybinder.sidebar") === "1"; } catch { return false; }
  });
  const toggle = () => setCollapsed((c) => {
    try { localStorage.setItem("scrybinder.sidebar", c ? "0" : "1"); } catch { /* no storage: ignore */ }
    return !c;
  });
  return (
    <Ctx.Provider value={{ collapsed, toggle }}>
      <nav aria-label="Main navigation" style={{ width: collapsed ? collapsedWidth : width }}
        className="relative flex h-full shrink-0 flex-col overflow-hidden border-r border-line bg-bg transition-[width] duration-200 ease-out motion-reduce:transition-none">
        {children}
      </nav>
    </Ctx.Provider>
  );
}

/** Text that fades out (and stops taking space) when the sidebar is collapsed. */
function Label({ className, children }: { className?: string; children: React.ReactNode }) {
  const { collapsed } = useSidebar();
  return <span aria-hidden={collapsed} className={cx("min-w-0 truncate transition-opacity duration-150", collapsed ? "pointer-events-none w-0 opacity-0" : "opacity-100", className)}>{children}</span>;
}

export function SidebarHeader({ children }: { children: React.ReactNode }) {
  const { collapsed, toggle } = useSidebar();
  return (
    <div className={cx("flex h-14 shrink-0 items-center", collapsed ? "justify-center" : "gap-2.5 px-[18px]")}>
      {collapsed ? (
        <button onClick={toggle} aria-label="Expand sidebar" className={cx(ICON_BTN, "size-8")}>
          <IconLayoutSidebarLeftExpand className="size-[18px]" stroke={1.75} />
        </button>
      ) : (
        <>
          {children}
          <button onClick={toggle} aria-label="Collapse sidebar" className={cx(ICON_BTN, "ml-auto size-7")}>
            <IconLayoutSidebarLeftCollapse className="size-[17px]" stroke={1.75} />
          </button>
        </>
      )}
    </div>
  );
}

export function SidebarSection({ label, children }: { label?: string; children: React.ReactNode }) {
  const { collapsed } = useSidebar();
  return (
    <div role="group" aria-label={label} className="py-1">
      {label && !collapsed && <div className="flex h-[26px] items-end px-[18px] pb-1.5 text-[10.5px] font-medium uppercase leading-none tracking-[0.08em] text-mute">{label}</div>}
      <div className="flex flex-col gap-px px-2">{children}</div>
    </div>
  );
}

export function SidebarItem({ icon, active, badge, onClick, children }: {
  icon?: React.ReactNode; active?: boolean; badge?: React.ReactNode; onClick?: () => void; children: string;
}) {
  const { collapsed } = useSidebar();
  return (
    <button type="button" onClick={onClick} title={collapsed ? children : undefined} aria-current={active ? "page" : undefined}
      className={cx(ROW, active ? "bg-accent-soft text-ink" : "text-mute hover:bg-raised/60 hover:text-ink")}>
      {icon && <span className={cx("flex size-5 shrink-0 items-center justify-center", active && "text-accent")}>{icon}</span>}
      <Label className="flex-1 text-left">{children}</Label>
      {badge && !collapsed ? <span className="flex shrink-0">{badge}</span> : null}
    </button>
  );
}

/** A parent row with sub-items. With the bar collapsed only the parent icon is shown. */
export function SidebarGroup({ icon, label, active, open, onToggle, children }: {
  icon: React.ReactNode; label: string; active?: boolean; open: boolean; onToggle: () => void; children: React.ReactNode;
}) {
  const { collapsed } = useSidebar();
  const expanded = open && !collapsed;
  return (
    <div className="flex flex-col">
      <button type="button" onClick={onToggle} aria-expanded={open} title={collapsed ? label : undefined}
        className={cx(ROW, active ? "text-ink" : "text-mute hover:bg-raised/60 hover:text-ink")}>
        <span className={cx("flex size-5 shrink-0 items-center justify-center", active && "text-accent")}>{icon}</span>
        <Label className="flex-1 text-left">{label}</Label>
        {!collapsed && <IconChevronRight aria-hidden className={cx("size-3.5 shrink-0 text-mute transition-transform duration-200", open && "rotate-90")} stroke={2} />}
      </button>
      <div className={cx("grid transition-[grid-template-rows,opacity] duration-200 ease-out motion-reduce:transition-none", expanded ? "grid-rows-[1fr] opacity-100" : "grid-rows-[0fr] opacity-0")}>
        <div className="overflow-hidden">
          <div className="relative ml-[21px] flex flex-col gap-px py-0.5 pl-2.5 before:absolute before:inset-y-1 before:left-0 before:w-px before:bg-line">{children}</div>
        </div>
      </div>
    </div>
  );
}

export function SidebarFooter({ children }: { children: React.ReactNode }) {
  const { collapsed } = useSidebar();
  return <div className={cx("mt-auto shrink-0 border-t border-line py-3 text-[11px] leading-snug text-mute", collapsed ? "hidden" : "px-[18px]")}>{children}</div>;
}
