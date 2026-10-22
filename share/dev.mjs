// Local stand-in for the share service and the viewer, to try sharing without deploying anything:
//   node share/dev.mjs                       (worker on :8787, viewer on :8788; data is kept in memory)
// then start Scrybinder with  SCRYBINDER_SHARE_API=http://127.0.0.1:8787  SCRYBINDER_SHARE_VIEWER=http://127.0.0.1:8788
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { handle } from "./worker/src/index.js";

const store = new Map();
const env = {
  VIEWER_ORIGIN: "http://127.0.0.1:8788",
  VIEWER_URL: "http://127.0.0.1:8788/",
  SHARES: {
    put: async (k, v) => store.set(k, v),
    get: async (k, t) => (store.has(k) ? (t === "json" ? JSON.parse(store.get(k)) : store.get(k)) : null),
    delete: async (k) => store.delete(k),
  },
};

createServer(async (req, res) => {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  const body = Buffer.concat(chunks);
  const r = await handle(new Request(`http://127.0.0.1:8787${req.url}`, { method: req.method, headers: req.headers, body: ["GET", "HEAD"].includes(req.method) ? undefined : body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(8787, "127.0.0.1");

const site = join(fileURLToPath(new URL(".", import.meta.url)), "site");
const types = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml" };
createServer(async (req, res) => {
  const path = new URL(req.url, "http://x").pathname;
  if (path === "/config.js") { res.writeHead(200, { "Content-Type": "text/javascript" }); return res.end('export const SHARE_API = "http://127.0.0.1:8787";'); }
  try {
    const file = join(site, normalize(path === "/" ? "/index.html" : path));
    if (!file.startsWith(site)) throw new Error("outside the site folder");
    const data = await readFile(file);
    res.writeHead(200, { "Content-Type": types[extname(file)] || "application/octet-stream" });
    res.end(data);
  } catch { res.writeHead(404); res.end("not found"); }
}).listen(8788, "127.0.0.1");
console.log("share worker http://127.0.0.1:8787, viewer http://127.0.0.1:8788");
