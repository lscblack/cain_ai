# KAI Mobile (Flutter) — design

Date: 2026-10-12 · Owner: lscblack · Status: building (milestones)

## Goal
A professional "hacker-theme" Flutter app giving a single operator KAI's intelligence
tools on their phone, talking to the existing FastAPI backend over a configurable
base URL (Cloudflare tunnel for remote, or LAN). Mirrors the web feature set:
face search (upload image/video + live camera), the report-card dossier format,
and the other search tools (phone/email/username/universal search, investigations).
Voice command ("Jarvis") drives search hands-free.

## Non-negotiables (inherit KAI guardrails)
Public sources + authorized use only. Matches are **potential leads, hedged**, never
confirmed identity. Secrets (JWT) stay in secure on-device storage; never logged.
Live camera frames ephemeral. SSRF/engine behaviour stays server-side (unchanged).

## Backend access (sub-project B)
- Backend keeps binding 127.0.0.1:8001. `cloudflared` runs on the host and
  connects to it; the tunnel gives an HTTPS URL. (Named tunnel + Cloudflare
  Access = the "+ auth" gate — needs the user's CF account; until then KAI's own
  JWT login is the gate, plus a quick tunnel for testing.)
- App base URL is user-configurable + persisted (Settings). Native HTTP → no CORS.

## Architecture
- `mobile/` Flutter project, org `net.nexventures`, package `kai_mobile`, Android first.
- State: lightweight (provider/ChangeNotifier or setState); no heavy framework.
- Packages: http, shared_preferences (base URL), flutter_secure_storage (token),
  image_picker (photo/video), google_fonts (mono), camera (live), speech_to_text (voice).
- Layers: `services/` (ApiClient, Auth), `theme/` (hacker theme tokens + scanline),
  `models/`, `widgets/` (ReportCard, ScanningStrip, BoxOverlay), `screens/`.

## Theme
Dark, near-black panels, monospace, green (#36d399)/amber(#ffb020)/red(#f87272)
accents, subtle scanline + glow; animated scanning strip of indexed-face crops
during a search (matches the web motif). Confidence bands colour-coded.

## Milestones
- **C1 (first testable APK):** theme, Settings(base URL), login(JWT)→secure store,
  Home, Face search (pick/capture image → POST /intelligence/face/search → scanning
  animation → report cards). Build + install on device.
- **C2:** Live camera detect (camera plugin → POST /frame throttled → boxes + report
  cards + capture) and image multi-face (/detect).
- **C3:** Video upload search (sub-project D backend first, then mobile).
- **C4:** Other search tools (universal /search, phone, email, username, investigations).
- **C5:** Voice command ("Jarvis") — speech_to_text → intent → run the matching search.

Each milestone: build, verify APK compiles, merge to main, note what was tested.
```
