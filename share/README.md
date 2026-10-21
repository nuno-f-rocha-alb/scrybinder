# Share links

Scrybinder can turn a deck, a trade, a list or part of the collection into a link. Two small pieces make that work; both are optional and nothing is sent until you press **Create link**.

- `worker/`: a Cloudflare Worker that keeps one share document (a small JSON file: cards, quantities, finishes, optionally prices) for 30 days under a random 12-character id. No accounts, no cookies, no logs of what is sent. `POST /api/share` stores it, `GET /api/share/:id` returns it (CORS only for the viewer), `DELETE /api/share/:id` removes it (needs the secret token the app keeps).
- `site/`: the viewer, a static page (no build, no scripts from other sites) published to GitHub Pages. It fetches the document by id and shows the cards with images from Scryfall, with **Copy as text** and **Download JSON** (the app imports that file). It can also open a share file dropped on the page.

What is never sent: notes, purchase prices, a trade's other person and cash, and locations (unless you tick the box).

## Try it without deploying anything

```bash
node share/dev.mjs
```

Starts a local worker (`:8787`, in memory) and the viewer (`:8788`). Then run Scrybinder with `SCRYBINDER_SHARE_API=http://127.0.0.1:8787` and `SCRYBINDER_SHARE_VIEWER=http://127.0.0.1:8788`.

## Deploy (once)

1. Worker (needs a free Cloudflare account):
   ```bash
   cd share/worker
   npx wrangler login
   npx wrangler kv namespace create SHARES     # paste the id it prints into wrangler.toml
   npx wrangler deploy                          # prints https://scrybinder-share.<account>.workers.dev
   ```
   `VIEWER_ORIGIN` in `wrangler.toml` must be the origin of the Pages site (for example `https://<user>.github.io`).
2. Viewer: put the Worker address in `site/config.js`, then in the repository settings set Pages > Source to **GitHub Actions**; `.github/workflows/pages.yml` publishes `share/site` on every change.
   The viewer's Content-Security-Policy (`site/index.html`) allows connections to `https://*.workers.dev`; if you use a custom domain for the Worker, add it to `connect-src`.
3. App: set `SHARE_API` (the Worker address) and `SHARE_VIEWER` (`https://<user>.github.io/<repo>`) in `scrybinder/share.py`. Until then the Share button explains that sharing is not set up.

## Tests

```bash
cd share/worker && node --test     # the Worker
cd share/test && node --test       # the viewer's helpers
```
