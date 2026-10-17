import { useEffect, useState } from "react";
import { Select } from "./select";
import { IconPhoto, IconPhotoFilled } from "@tabler/icons-react";

/** Card size (px): by default it grows with the screen (1080p ≈ 240, 1440p ≈ 320); the user can adjust it. */
export const autoSize = () => Math.min(360, Math.max(170, Math.round(window.innerWidth / 8 / 10) * 10));
const SIZE_KEY = "scrybinder.cardsize";
const COLS_KEY = "scrybinder.cols";
const COL_OPTIONS = [3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16];
const GAP = 16;  // gap-4
/** Image source closest to the real size in pixels (size × density): shrinking too much makes card text jagged. */
export const sourceFor = (tilePx: number) => (tilePx * (window.devicePixelRatio || 1) > 420 ? "large" : "normal");

const read = (k: string, d: number) => { try { return Number(localStorage.getItem(k)) || d; } catch { return d; } };
const write = (k: string, n: number) => { try { localStorage.setItem(k, String(n)); } catch { /* no storage */ } };

/** Responsive card grid (size/columns are saved and shared between pages: Collection, Add). */
export function useCardGrid() {
  const [tile, setTile] = useState<number>(() => read(SIZE_KEY, autoSize()));
  const [cols, setCols] = useState<number>(() => read(COLS_KEY, 0));  // 0 = automatic
  const [el, setGridEl] = useState<HTMLDivElement | null>(null);
  const [w, setW] = useState(0);
  useEffect(() => {
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(e.contentRect.width));
    ro.observe(el);
    return () => ro.disconnect();
  }, [el]);
  // real width of each card: in "auto" the cards stretch to fill the row, so count the columns that fit
  const nCols = cols || Math.max(1, Math.floor((w + GAP) / (tile + GAP)));
  return {
    tile, cols, setGridEl,
    setTileSize: (n: number) => { setTile(n); write(SIZE_KEY, n); },
    setColumns: (n: number) => { setCols(n); write(COLS_KEY, n); },
    tilePx: w ? (w - GAP * (nCols - 1)) / nCols : tile,
    style: { gridTemplateColumns: cols ? `repeat(${cols}, minmax(0, 1fr))` : `repeat(auto-fill, minmax(${tile}px, 1fr))` },
  };
}

export function GridControls({ g }: { g: ReturnType<typeof useCardGrid> }) {
  return (
    <>
      <Select className="field w-auto" value={g.cols} aria-label="Columns" title="Number of columns" onChange={(e) => g.setColumns(+e.target.value)}>
        <option value={0}>Columns: auto</option>
        {COL_OPTIONS.map((n) => <option key={n} value={n}>{n} columns</option>)}
      </Select>
      {!g.cols && (
        <label className="flex items-center gap-2 text-xs text-mute" title="Card size (double-click to reset)">
          <IconPhoto className="size-3.5" aria-hidden />
          <input type="range" min={130} max={380} step={10} value={g.tile} aria-label="Card size" className="w-28 accent-[var(--color-accent)]"
            onChange={(e) => g.setTileSize(+e.target.value)} onDoubleClick={() => g.setTileSize(autoSize())} />
          <IconPhotoFilled className="size-5" aria-hidden />
        </label>
      )}
    </>
  );
}
