# @sahaj/web

Mobile-first PWA for Sahaj: React 19, Vite, TypeScript, Tailwind v4, shadcn/ui, Motion, Zustand, TanStack Query.

The UI implements the Claude Design file (v2, Paytm-inspired palette, direction 1a "chat timeline"). The export
lives in `docs/design/<export>/` and is git-ignored; open its `Sahaj Design v2.dc.html` over HTTP to view it.

| Path | What it is |
|---|---|
| `src/index.css` | Design tokens (light + dark), type, radii, motion. Re-skin by changing `--brand-*` |
| `src/lib/i18n.ts` | Interface text in English and Hindi (menu → App language). Conversation text is never translated |
| `src/components/conversation/` | Timeline, bubbles (fallback, clarify, text-only), dock with every voice state |
| `src/components/cards/` | EMI, prepayment, comparison (table/list), profile summary, recommendation, needs consent, handoff |
| `src/components/sheets/` | Consent, citations, mic explainer/blocked, menu + withdraw, install, about |
| `src/lib/session.ts` | Controller: socket events → store, push-to-talk, consent, handoff, playback |
| `src/store/session.ts`, `src/store/ui.ts` | Zustand: conversation state; UI preferences (persisted) and open sheets |
| `src/lib/socket.ts` | `/ws/voice` client: same origin, `wss://` on https, reconnect with backoff |
| `src/lib/audio/` | Recorder (WebM or iPhone MP4, level meter, 30 s limit) and iPhone-safe playback |
| `mock/server.mjs` | Mock backend speaking the real protocol, scripted through every design state |
| `scripts/icons.sh` | Rebuilds the self-hosted Material Symbols subset when you use a new icon |
| `src/components/brand/logo.tsx`, `public/` | Logo ("voice bars", docs/design/logo-1c): exact design geometry, colours mapped to `--brand-*` tokens. Icons and `favicon.svg` are rendered from it |

Types come from `@sahaj/contracts`. The live conversation goes through the socket and the Zustand store;
TanStack Query is only for REST calls. Below 1024 px the layout is the phone design; from 1024 px cards open in a
"Latest card" side panel and the dock floats (hold Space to talk).

## Run

```bash
pnpm dev:mock        # mock backend + Vite: no Sarvam / Postgres / model needed. Each recording
                     # advances a scripted demo: EMI, citations, comparison, prepayment, clarify,
                     # fallback, text-only (Urdu), needs analysis → recommendation
pnpm dev:web         # Vite only; proxies /ws, /stt and /health to the real API on :8000 (pnpm dev:api)
pnpm --filter @sahaj/web build && pnpm --filter @sahaj/web preview   # production build with service worker, :4173
```

## Demo on an iPhone

The microphone only works on **HTTPS** (or localhost), so a phone on `http://192.168.x.x:5173` cannot record. Use a tunnel:

```bash
pnpm dev:mock            # or: pnpm dev:api + pnpm dev:web
pnpm demo:tunnel         # ngrok http 5173 → open the https://….ngrok-free.app URL on the iPhone
```

Before the demo:
- **Use the deployed URL if you can** (see `docs/deployment.md`). It's the most reliable option and the PWA installs cleanly.
- **Install it:** Safari → Share → *Add to Home Screen*, then open it from the icon (full screen, no browser bar).
- **Allow the mic once.** iOS may ask again on each cold launch of a home-screen app. That's an iOS behaviour, not a bug.
- **Turn the volume up.** Replies play through the speaker even when the silent switch is on.
- **Use one tunnel URL for the whole demo.** Changing the URL means installing again.

How the iPhone problems are handled:
- **Recording format.** Safari records MP4/AAC. The backend detects the container from the bytes (`apps/api/services/audio.py`).
- **Autoplay.** The reply arrives after the finger lifts, and iOS blocks audio that isn't started by a gesture. `player.unlock()` runs during the press and unlocks one reusable `<audio>` element.
- **Quiet earpiece.** While the mic is open, iOS plays sound through the earpiece. The mic is released after every recording, so replies use the loudspeaker.
- **Long-press.** The long-press callout and text selection are disabled on the talk button. A pointer capture keeps the press alive if the finger drifts.
- **Backgrounding.** iOS closes sockets when the app goes to the background. The app reconnects when it becomes visible again and notes that the conversation was reset.
- **Layout.** The layout follows the safe areas (notch, home indicator) and uses `100dvh`.

## PWA

`vite-plugin-pwa` generates the manifest, the service worker and the icons. Icons come from `public/icon.svg`, a
placeholder until the logo arrives. The service worker caches the app shell and fonts, and never caches `/ws`,
`/stt`, `/health`, `/audit` or `/docs`.
