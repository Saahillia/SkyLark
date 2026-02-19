# SkyLark — Decision Log

A running record of architectural decisions, trade-offs, and issues encountered during development and deployment.

---

## Architecture Decisions

### 1. LLM Selection: Gemini 2.0 Flash

| Option | Reason not chosen |
|---|---|
| GPT-4o | Paid tier required for reliable function calling volume |
| Claude | Paid tier, no significant advantage for this use case |
| **Gemini 2.0 Flash** | **Free tier (1,500 req/day), 1M token context, native function calling** |

### 2. UI Framework: Chainlit

| Option | Reason not chosen |
|---|---|
| Streamlit | No native WebSocket support; poor fit for streaming agents |
| Gradio | Limited conversational UI primitives |
| **Chainlit** | **Purpose-built for conversational AI, WebSocket-native, supports history** |

### 3. Deployment: Render

| Option | Reason not chosen |
|---|---|
| Vercel | Serverless — terminates long-running processes; incompatible with Chainlit WebSockets |
| Railway | Similar pricing to Render with less free tier availability |
| **Render** | **Persistent processes, free tier, WebSocket support, render.yaml IaC** |

### 4. Data Layer: In-Memory pandas DataFrames

| Option | Reason not chosen |
|---|---|
| SQLite | Adds file I/O complexity; overkill for < 100 rows |
| PostgreSQL | Requires provisioning, credentials, migrations |
| **pandas DataFrames** | **Zero setup, sufficient for demo scale, easy CSV round-trip** |

### 5. Agent Loop: Non-Streaming Synchronous

| Option | Reason not chosen |
|---|---|
| Streaming | Multi-round tool calls cannot stream cleanly mid-execution |
| **Synchronous with asyncio.to_thread** | **Reliable, predictable; Gemini SDK has mature sync support** |

---

## Data Design Decisions

### 6. Semicolons as Multi-Value Separator

CSV's native comma separator conflicts with multi-value fields like skills ("Mapping, Survey"). Semicolons (`Mapping;Survey`) avoid ambiguity without requiring quoted fields.

### 7. `required_capabilities` Field Added to missions.csv

The spec required drone-to-mission matching but only listed skill fields. Without `required_capabilities`, drones would be matched on pilot skills rather than their own capability specs. Added this field to enable proper drone filtering.

### 8. "Assigned" Status Added to Pilots

The spec listed `Available / On Leave / Unavailable` as valid pilot statuses. A fourth status, `Assigned`, is necessary to track pilots actively on a mission without marking them unavailable for future planning.

### 9. Calendar Days for Cost Calculation

Pilot cost = `daily_rate_inr × (end_date − start_date + 1)`. Calendar days is the most standard interpretation for field operations billing and avoids ambiguity around "working days."

---

## Google Sheets Integration Decisions

### 10. Support for Both Single Sheet and Separate Sheets

Initially designed for one spreadsheet with 3 tabs (Pilots / Drones / Missions). Extended to support 3 separate spreadsheets (`PILOTS_SPREADSHEET_ID`, `DRONES_SPREADSHEET_ID`, `MISSIONS_SPREADSHEET_ID`) when deployment required separate sheets per data type.

**Resolution order in `sheets.py`:**
1. If separate IDs are set → each tab reads from its own spreadsheet
2. If only `SPREADSHEET_ID` is set → all tabs read from the same spreadsheet
3. Named worksheet first, then first worksheet (handles both named and unnamed tabs)

### 11. Graceful CSV Fallback

Google Sheets connection is optional. If credentials or IDs are missing, the app loads from local `data/` CSVs silently. This allows offline development without any Sheets setup.

### 12. Write-Back Scope

Only pilot status and drone status write back to Sheets (via `update_pilot_status` and `update_drone_status` tools). Mission assignment fields (`assigned_pilot_id`, `assigned_drone_id`, `status`) are updated in-memory only. Full Sheets write-back for missions is a known gap.

---

## Deployment Issues & Fixes

### 13. render.yaml Location (Critical)

**Problem:** `render.yaml` was placed inside `skylark-agent/`. Render only reads `render.yaml` from the **repository root**. Because Render couldn't find it, it auto-detected the project as Node.js (due to Chainlit's presence) and ran `yarn` instead of `pip install`. Result: `chainlit: command not found` on start.

**Fix:** Moved `render.yaml` to the repo root and added `rootDir: skylark-agent` to tell Render where the Python app lives.

### 14. Python Version Compatibility

**Problem:** Local development used Python 3.14 (system default). The `anyio` package has a conflict between the pip-installed and system versions on Python 3.14, causing Chainlit's web server to serve HTTP 500 errors on every request — resulting in a completely blank browser page.

**Fix:** Created a Python 3.11 virtual environment (`.venv`) inside `skylark-agent/`. Python 3.11 is the version the requirements were written for and has no anyio conflicts.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
chainlit run app.py
```

### 15. Spreadsheet ID Assignment (Corrected)

**Problem:** The 3 Google Sheets were originally assigned in the wrong order — Pilots ID pointed to the "Drones.csv" sheet, etc.

**Fix:** Corrected by reading the actual spreadsheet titles from the Sheets API connection log and reassigning:
- `PILOTS_SPREADSHEET_ID` → spreadsheet titled "Pilots"
- `DRONES_SPREADSHEET_ID` → spreadsheet titled "Drones.csv"
- `MISSIONS_SPREADSHEET_ID` → spreadsheet titled "Missions"

---

## Security Decisions

### 16. Secrets Management

All secrets are stored in `.env` (gitignored). The following patterns are excluded by `.gitignore`:
- `.env`, `.env.*`, `*.env`
- `key.json`, `*credentials*.json`, `*service_account*.json`
- `*.pem`, `*.key`, SSH key files
- `.claude/` (Claude Code local settings)

`.env.example` is committed as a template with placeholder values only.

### 17. Credentials Stored as Environment Variables (Not Files)

The Google service account JSON is minified to a single line and stored as the `GOOGLE_CREDENTIALS_JSON` environment variable. This avoids committing a credentials file and works cleanly with Render's environment variable system.

### 18. No Hardcoded Credentials

All API keys and credentials are loaded via `os.environ.get()` with empty-string defaults. Missing credentials result in graceful degradation (CSV fallback) rather than crashes, except for `GEMINI_API_KEY` which raises a clear `RuntimeError`.

---

## Known Gaps (Future Work)

| Gap | Impact | Suggested Fix |
|---|---|---|
| Mission assignments don't write back to Sheets | Assignments are session-only | Add `write_cell` calls in `assign_pilot_to_mission` and `assign_drone_to_mission` |
| No persistent storage | Data resets on every Chainlit session start | Replace DataFrames with SQLite or Supabase |
| No user authentication | All users share the same operational view | Add Chainlit OAuth (Google login) |
| Python 3.14 incompatibility locally | Blank page if venv not activated | Pin anyio version or wait for chainlit/anyio 3.14 support |
| Async Gemini calls | Synchronous calls block the thread pool | Use `generate_content_async` from the google-genai SDK |
