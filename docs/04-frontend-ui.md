# Frontend / UI Requirements

See [[00-overview]] for the open question on the alert/warning palette — this doc proposes a resolution, flagged for confirmation.

## 1. Design system

- **Framework**: React, Material Design components via **MUI (Material UI)**.
- **Themes**: both a dark theme and a light theme, user-toggleable, following MUI's theming system (`createTheme` + `CssBaseline`), persisted per-user (e.g. stored on the user profile or in local storage keyed by user).
- **Tone**: elegant, professional — this is an org-wide internal tool used by every engineer, not a marketing surface. Favor whitespace, restrained motion, and clear information hierarchy over decoration.

## 2. Color system

Given by the user: primary palette is **white**, **`#1474d4`** (blue), **`#06b6ed`** (cyan), plus soft semantic colors for alerts/warnings "like `#78b75e`."

Proposed token set (flagged in [[00-overview]] §6 for confirmation — `#78b75e` is a green and reads as "success," not "warning," so a full soft semantic set is proposed here in the same visual language):

| Token | Light theme | Dark theme | Usage |
|---|---|---|---|
| `primary` | `#1474d4` | `#4a9ce8` (lightened for dark-mode contrast) | Primary actions, links, active nav |
| `secondary` / `accent` | `#06b6ed` | `#06b6ed` | Secondary actions, highlights, charts |
| `background.default` | `#f7f9fc` (subtle cool-gray, not pure white) | `#0f1720` (near-black, not pure black) | Page background |
| `background.paper` | `#ffffff` | `#182430` | Cards, dialogs — stays pure white/near-black so it's visibly distinct from the page behind it, same relationship as dark mode |
| `success` (soft) | `#78b75e` | `#8fcf77` | Healthy status, resolved alerts |
| `warning` (soft) | `#e8b04b` | `#f0c268` | Degraded status, needs attention |
| `error` / `critical` (soft) | `#e07a6b` | `#eb9385` | Critical alerts, failures |
| `info` | `#06b6ed` | `#06b6ed` | Informational banners |

All semantic colors are intentionally **soft/muted**, not saturated alarm-red, matching the "soft colors" instruction — critical states should still read as unmistakably urgent via icon/label/position, not just raw color saturation (also an accessibility win).

## 3. Key screens

1. **Login** — username + password only (see [[05-auth-and-users]]), no "forgot password" flow needed for v1 (plaintext, admin resets manually).
2. **Chat** — the core SRE Agent interface. Streaming responses, tool-call transparency (shows which docs were retrieved / which live queries were run, collapsible), conversation history sidebar. Session titles start as "New Chat" and are auto-renamed to the matched document's title once the Orchestrator pins the session (see [[08-chat-sessions-and-orchestration]]); a pinned session shows a small badge/chip naming its document. When the assistant detects topic drift, it renders a redirect message (not an answer) with a one-click **"Start new session"** button pre-filled with the drifted message, per [[08-chat-sessions-and-orchestration]] §6.
3. **Dashboards** — embedded/summarized views for:
   - Grafana panels relevant to the user's groups.
   - EKS cluster overview (pods by status, recent events, deployments) per cluster in scope.
   - CloudWatch/Prometheus key metrics summary.
   This is a summarized "at a glance" surface, not a full Grafana re-implementation — deep-dive links out to the real Grafana/CloudWatch console.
4. **Knowledge Base management** — per-user view of: their personal documents (upload/delete), and documents in each group they belong to (upload if permitted, browse/search always). Upload flow lets the user pick target scope (personal vs. a specific group they belong to), add free-form tags, and choose the chunking strategy for that document — "whole document" or "best effort" with a small/medium/large qualitative size, defaulting to the system-wide setting (see [[02-access-control-and-rag]] §3).
5. **Admin** (superusers only) — manage groups (create/rename/delete), manage user-to-group membership, grant/revoke superuser flag, manage `integration_scope` mappings (which cluster/account/dashboard belongs to which group), browse/re-tag/delete any document, and set the system-wide default chunking strategy (ingestion settings).
6. **Settings** — theme toggle (dark/light), profile (change own password — still plaintext compare in v1, but let the UI support changing it).

## 4. Non-goals for v1 UI

- No mobile-native app — responsive web is sufficient.
- No real-time collaborative chat (multiple users in one thread) — chats are per-user.
- No custom dashboard builder — dashboards are backend-configured per group, not drag-and-drop editable by end users in v1.
