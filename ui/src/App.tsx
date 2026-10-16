import { useEffect, useState } from "react";
import { IconAlertTriangle, IconCards, IconPlus, IconScan, IconSettings, IconStack2, IconSwitchVertical } from "@tabler/icons-react";
import { api, Status } from "./api";
import { Sidebar, SidebarFooter, SidebarGroup, SidebarHeader, SidebarItem, SidebarSection } from "./components/sidebar";
import Collection from "./pages/Collection";
import Decks from "./pages/Decks";
import Sets from "./pages/Sets";
import Scan from "./pages/Scan";
import Add from "./pages/Add";
import ImportExport from "./pages/ImportExport";
import Settings from "./pages/Settings";

const PAGES = { collection: "Cards", sets: "Sets", decks: "Decks", scan: "Scan", add: "Add", io: "Import / Export", settings: "Settings" } as const;
type Page = keyof typeof PAGES;
const ICON = { decks: IconStack2, scan: IconScan, add: IconPlus, io: IconSwitchVertical, settings: IconSettings };

export default function App() {
  const [page, setPage] = useState<Page>("collection");
  const [open, setOpen] = useState(true);
  const [filter, setFilter] = useState<{ set?: string; location?: string }>({});
  const [deckTarget, setDeckTarget] = useState<{ deckId: number; oracleId?: string; n: number } | undefined>();  // `n` makes a repeat of the same target reopen it
  const [status, setStatus] = useState<Status | null>(null);
  const refresh = () => api<Status>("/status").then(setStatus).catch(() => {});
  useEffect(() => { refresh(); }, [page]);

  const needBulk = status && status.cards_in_db === 0;
  return (
    <div className="flex h-full">
      <Sidebar>
        <SidebarHeader>
          <img src="/favicon.svg" alt="" className="size-7 shrink-0" />
          <span className="text-[15px] font-semibold tracking-tight">Scrybinder</span>
        </SidebarHeader>
        <SidebarSection>
          <SidebarGroup icon={<IconCards className="size-[18px]" stroke={1.75} />} label="Collection" active={page === "collection" || page === "sets"}
            open={open} onToggle={() => {
              if (page === "collection" || page === "sets") setOpen(!open);
              else { setFilter({}); setPage("collection"); setOpen(true); }
            }}>
            <SidebarItem active={page === "collection"} onClick={() => { setFilter({}); setPage("collection"); }}>Cards</SidebarItem>
            <SidebarItem active={page === "sets"} onClick={() => setPage("sets")}>Sets</SidebarItem>
          </SidebarGroup>
          {(["decks", "scan", "add", "io", "settings"] as const).map((p) => {
            const I = ICON[p];
            return <SidebarItem key={p} icon={<I className="size-[18px]" stroke={1.75} />} active={page === p} badge={p === "settings" && status?.update_available ? <span className="size-2 rounded-full bg-accent" title={`Scrybinder ${status.update_available} is available`} /> : undefined}
              onClick={() => { if (p === "decks") setDeckTarget(undefined); setPage(p); }}>{PAGES[p]}</SidebarItem>;
          })}
        </SidebarSection>
        <SidebarFooter>Card data and images © Scryfall<br />Scrybinder is not affiliated with Wizards of the Coast.</SidebarFooter>
      </Sidebar>
      <div className="relative flex min-w-0 flex-1 flex-col">
      <main className="min-h-0 flex-1 overflow-y-auto">
        {status && (needBulk || status.bulk_stale) && page !== "settings" && (
          <button onClick={() => setPage("settings")}
            className="flex w-full cursor-pointer items-center gap-2 border-b border-gold/30 bg-gold/10 px-6 py-2.5 text-left text-sm text-gold">
            <IconAlertTriangle className="size-4 shrink-0" />
            {needBulk ? "The card database is empty. Download the Scryfall bulk data in Settings to get started."
              : `The card database is ${Math.floor(status.bulk_age_days ?? 0)} days old. Update it in Settings.`}
          </button>
        )}
        <div className="mx-auto max-w-[2600px] p-6 min-[1800px]:px-10">
          {page === "collection" && <Collection key={`${filter.set}|${filter.location}`} initialSet={filter.set} initialLocation={filter.location}
            onOpenDeck={(deckId, oracleId) => { setDeckTarget({ deckId, oracleId, n: Date.now() }); setPage("decks"); }} />}
          {page === "sets" && <Sets onOpen={(set, location) => { setFilter({ set, location }); setPage("collection"); }} />}
          {page === "decks" && <Decks key={deckTarget?.n} target={deckTarget} />}
          {page === "scan" && <Scan />}
          {page === "add" && <Add />}
          {page === "io" && <ImportExport />}
          {page === "settings" && <Settings status={status} refresh={refresh} />}
        </div>
      </main>
      <div id="status-root" />  {/* a page can pin a bar here, under the scrolling area */}
      <div id="drawer-root" className="pointer-events-none absolute inset-0 z-40" />
      </div>
    </div>
  );
}
