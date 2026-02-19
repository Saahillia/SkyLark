# SkyLark Drone Operations Coordinator

An AI agent that handles the core responsibilities of a drone operations coordinator — pilot roster management, drone fleet inventory, mission assignment tracking, and conflict detection — through a conversational chat interface.

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Chainlit UI (Browser)                 │
│              Conversational chat interface               │
└───────────────────────┬─────────────────────────────────┘
                        │  HTTP / WebSocket
┌───────────────────────▼─────────────────────────────────┐
│                     app.py                               │
│          on_chat_start  │  on_message                    │
└───────────────────────┬─────────────────────────────────┘
                        │
┌───────────────────────▼─────────────────────────────────┐
│               agent/core.py                              │
│   Gemini 2.0 Flash  ←→  Tool execution loop             │
│   (up to 10 rounds per turn, circuit breaker)            │
└──────┬──────────────────────────────────────────────────┘
       │  calls 17 tools
┌──────▼──────────────────────────────────────────────────┐
│                  tools/                                  │
│  roster.py   drones.py   missions.py   conflicts.py      │
│  (4 tools)   (4 tools)   (5 tools)     (4 tools)         │
└──────┬──────────────────────────────────────────────────┘
       │  reads/writes
┌──────▼──────────────────────────────────────────────────┐
│              data_store.py                               │
│        In-memory pandas DataFrames                       │
│   _pilots_df   _drones_df   _missions_df                 │
└──────┬──────────────────────────────────────────────────┘
       │  load (read)          │  write_cell (write)
┌──────▼──────┐       ┌────────▼────────────────────────┐
│  sheets.py  │       │       sheets.py                  │
│  CSV files  │       │  Google Sheets (2-way sync)      │
│  (fallback) │       │  Pilots / Drones / Missions tabs │
└─────────────┘       └─────────────────────────────────┘
```

### Key Components

| File | Purpose |
|------|---------|
| `app.py` | Chainlit entry point — session init, message routing |
| `agent/core.py` | Gemini 2.0 Flash client, agentic tool-call loop |
| `agent/prompts.py` | System prompt defining the coordinator persona and rules |
| `tools/roster.py` | 4 pilot tools: query, details, update status, calculate cost |
| `tools/drones.py` | 4 drone tools: query, details, weather filter, update status |
| `tools/missions.py` | 5 mission tools: query, details, assign pilot, assign drone, active list |
| `tools/conflicts.py` | 4 conflict tools: pilot check, drone check, full audit, suggest reassignment |
| `tools/__init__.py` | Tool registry mapping names → (callable, FunctionDeclaration) |
| `sheets.py` | Google Sheets 2-way sync with graceful CSV fallback |
| `data_store.py` | Shared in-memory DataFrames + init_data() |
| `data/` | Enhanced CSV files (local fallback / source data) |

---

## Setup

### Prerequisites
- Python 3.11+
- A free Gemini API key from [Google AI Studio](https://aistudio.google.com/app/apikey)
- (Optional) A Google Cloud service account for Sheets sync

### Local Setup

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd skylark-agent

# 2. Create a Python 3.11 virtual environment (required — avoids package conflicts)
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY (and optionally the Sheets IDs)

# 5. Run the agent
chainlit run app.py
# Opens at http://localhost:8000
```

### Google Sheets Setup (Optional but Required for Write-Back Demo)

1. Create a new Google Sheet with **3 tabs** named exactly:
   - `Pilots`
   - `Drones`
   - `Missions`

2. Copy the header + data rows from the corresponding CSV files in `data/` into each tab.

3. Create a Google Cloud service account:
   - Go to [Google Cloud Console](https://console.cloud.google.com) → IAM & Admin → Service Accounts
   - Create a new service account (no roles needed)
   - Keys tab → Add Key → Create new key → JSON → Download

4. Share your Google Sheet with the service account's email address (Editor role).

5. Minify the JSON key for use as an environment variable:
   ```bash
   python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))" key.json
   ```

6. Set environment variables:
   ```bash
   GOOGLE_CREDENTIALS_JSON=<paste minified JSON here>
   SPREADSHEET_ID=<the ID from your sheet URL>
   ```

### Deploy to Render

1. Push this repository to GitHub.
2. Create a new [Render](https://render.com) Web Service connected to your repo.
3. Render will auto-detect `render.yaml` and configure the service.
4. Set environment variables in the Render dashboard:
   - `GEMINI_API_KEY`
   - `GOOGLE_CREDENTIALS_JSON`
   - `SPREADSHEET_ID`
5. Deploy. The app will be live at your Render URL.

---

## Usage Guide

### Roster Management

| What you want | What to say |
|---------------|-------------|
| Find available pilots | *"Show me all available pilots"* |
| Find pilots by skill | *"Find pilots with Thermal skills in Bangalore"* |
| Find pilots with a certification | *"Which pilots have Night Ops certification?"* |
| View a pilot's details | *"Show me details for Arjun"* or *"Get details for P001"* |
| Calculate mission cost | *"How much will Arjun cost for PRJ001?"* |
| Update pilot status | *"Set Neha to On Leave"* or *"Mark P002 as Available"* |
| View all assignments | *"Show me all current assignments"* |

### Drone Inventory

| What you want | What to say |
|---------------|-------------|
| Query the fleet | *"Show me all available drones"* |
| Filter by capability | *"Which drones have Thermal capability?"* |
| Filter by weather | *"Which drones can fly in Rainy conditions?"* |
| Filter by location | *"Show drones in Mumbai"* |
| View drone details | *"Get details for D001"* |
| Update drone status | *"Mark D002 as Available"* |
| Check maintenance | *"Are any drones in maintenance?"* |

### Assignment Tracking

| What you want | What to say |
|---------------|-------------|
| View active missions | *"Show me all active assignments"* |
| Get mission details | *"Tell me about PRJ002"* |
| Find a pilot for a mission | *"Find a suitable pilot for PRJ003"* |
| Assign a pilot | *"Assign Arjun to PRJ003"* or *"Assign P001 to PRJ003"* |
| Assign a drone | *"Assign D001 to PRJ003"* |
| Find weather-safe drones | *"Which drones can handle PRJ001's weather?"* |

### Conflict Detection

| What you want | What to say |
|---------------|-------------|
| Full audit | *"Run a full conflict check"* or *"Show all conflicts"* |
| Check a specific assignment | *"Check conflicts for PRJ002"* |
| Check pilot eligibility | *"Can Neha be assigned to PRJ002?"* |
| Check drone eligibility | *"Is D002 suitable for PRJ001?"* |
| Urgent reassignment | *"PRJ002 has conflicts — suggest a reassignment"* |
| Fix a specific conflict | *"Fix the issue with PRJ002"* |

### Urgent Reassignment Flow

When a mission has conflicts, the agent will:
1. Detect and explain the root cause(s)
2. Present ranked alternative pilot and drone candidates (scored by location + cost/IP43)
3. Wait for your confirmation
4. Execute the reassignment and sync changes to Google Sheets

Example conversation:
```
You: PRJ002 has issues. Sort it out urgently.
Agent: [Runs conflict detection → finds CERT_MISMATCH and CAPABILITY_MISMATCH]
       [Shows top 3 pilot candidates and top 3 drone candidates]
       Recommend assigning Rohit (P003) + D001. Confirm?
You: Yes, go ahead.
Agent: [Assigns P003 to PRJ002, assigns D001 to PRJ002, syncs to Sheets]
       Done. Rohit (P003) and DJI M300 (D001) assigned to PRJ002. Synced to Google Sheets.
```

---

## Data Schema

### pilot_roster.csv
| Column | Type | Description |
|--------|------|-------------|
| pilot_id | String | Unique ID (P001–P004) |
| name | String | Full name |
| skills | String | Semicolon-separated skills |
| certifications | String | Semicolon-separated certs |
| location | String | Current city |
| status | Enum | Available / Assigned / On Leave / Unavailable |
| current_assignment | String | Project ID or "-" |
| available_from | Date | ISO date (YYYY-MM-DD) |
| daily_rate_inr | Number | Daily rate in ₹ |
| hourly_rate_inr | Number | Hourly rate (daily/8) |

### drone_fleet.csv
| Column | Type | Description |
|--------|------|-------------|
| drone_id | String | Unique ID (D001–D004) |
| model | String | Drone model name |
| capabilities | String | Semicolon-separated capabilities |
| status | Enum | Available / Maintenance / Deployed / Unavailable |
| location | String | Current city |
| current_assignment | String | Project ID or "-" |
| maintenance_due | Date | Next maintenance date |
| weather_resistance | String | "IP43 (Rain)" or "None (Clear Sky Only)" |

### missions.csv
| Column | Type | Description |
|--------|------|-------------|
| project_id | String | Unique ID (PRJ001–PRJ003) |
| client | String | Client name |
| location | String | Mission city |
| required_skills | String | Semicolon-separated skills |
| required_certs | String | Semicolon-separated certifications |
| start_date | Date | ISO date |
| end_date | Date | ISO date |
| priority | Enum | High / Urgent / Standard |
| mission_budget_inr | Number | Total budget in ₹ |
| weather_forecast | Enum | Rainy / Sunny / Cloudy |
| estimated_duration_hours | Number | Total mission hours |
| assigned_pilot_id | String | Assigned pilot ID or "-" |
| assigned_drone_id | String | Assigned drone ID or "-" |
| status | Enum | Unassigned / Assigned / In Progress / Completed / Cancelled |
| required_capabilities | String | Semicolon-separated drone capabilities needed |

---

## Decision Log

### Key Assumptions

1. **Daily rate × calendar days = pilot cost.** The spec says "total cost based on mission duration" without specifying hours vs days. Calendar days is the simplest and most standard interpretation for field operations.

2. **"Unavailable" and "Assigned" are both valid pilot statuses.** The spec lists "Available / On Leave / Unavailable" but the data naturally needs "Assigned" for pilots actively on a mission. Both are supported.

3. **Missions.csv is included in Sheets sync (read).** The spec only requires Pilot Roster and Drone Fleet for read. However, mission data is equally critical for conflict detection and assignment. We read all three tabs. Write-back is implemented for pilots and drones.

4. **Semicolons as multi-value separator.** The original CSVs used commas inside quoted fields which causes CSV parsing ambiguity. Semicolons avoid this entirely.

5. **Required capabilities in missions.** The spec doesn't explicitly list this field, but without it, drone-to-mission matching would be skill-based only and miss the drone capability dimension. Added `required_capabilities` to missions.csv.

### Trade-offs

| Decision | Alternative | Why We Chose This |
|----------|-------------|-------------------|
| Gemini 2.0 Flash | GPT-4o | Free tier (1500 req/day), native function calling, 1M context |
| Chainlit | Streamlit, Gradio | Purpose-built for conversational AI agents, WebSocket support |
| Render | Vercel | Vercel is serverless — incompatible with Chainlit WebSockets |
| In-memory DataFrames | SQLite, PostgreSQL | Zero setup, sufficient for this data size (< 100 rows), no persistence needed |
| Non-streaming agent loop | Streaming | Multi-round tool calls can't stream cleanly; simpler and more reliable |
| pandas for CSV parsing | csv module, polars | Familiar, widely used, handles type inference well |

### What I'd Do Differently With More Time

1. **Persistent storage** — Replace in-memory DataFrames with SQLite or Supabase so writes survive restarts and multiple Render instances don't diverge.

2. **Full Sheets write-back for missions** — Currently only pilot and drone status syncs back. Mission assignments (assigned_pilot_id, assigned_drone_id, status) should also write back to keep Sheets fully in sync.

3. **User authentication** — Chainlit supports OAuth. With more time, I'd add Google OAuth so each ops manager sees their own session history.

4. **Async Gemini calls** — The current loop uses synchronous `generate_content` wrapped in `asyncio.to_thread`. The `google-genai` SDK has async methods (`generate_content_async`) that would be cleaner.

5. **More sample data** — 4 pilots and 4 drones creates limited conflict scenarios. A larger dataset would better demonstrate edge cases.

6. **Streaming final responses** — Add streaming for the final text-only turn to improve perceived responsiveness on slow connections.

### Urgent Reassignment Interpretation

> "The agent should help coordinate urgent reassignments"

**Interpretation:** An urgent reassignment is triggered when an active mission has one or more HIGH severity conflicts that prevent it from proceeding as planned. The agent's role is to:

1. **Diagnose** — automatically detect what conflicts exist and why they block the mission (not just list errors, but explain the root cause in plain language).

2. **Source alternatives** — search the full pilot and drone roster for candidates that pass all HIGH-severity conflict checks for the affected mission.

3. **Rank** — score candidates by operational fit: location match (highest priority, avoids travel delays) and budget efficiency / weather capability.

4. **Present options** — show the top 3 pilot candidates and top 3 drone candidates with a confidence score, so the ops manager can make an informed decision quickly.

5. **Execute on confirmation** — only after the manager confirms, the agent calls `assign_pilot_to_mission` and `assign_drone_to_mission`, which include their own conflict pre-checks as a safety net, and immediately sync the new assignments to Google Sheets.

This design keeps the human in the loop for the final decision (appropriate for regulated drone operations) while eliminating the manual searching that makes reassignment slow.

---

## Tech Stack Summary

| Layer | Technology | Justification |
|-------|------------|---------------|
| Language | Python 3.11 | Best ecosystem for AI/data work |
| LLM | Gemini 2.0 Flash | Free, 1M context, native function calling |
| Agent SDK | `google-genai` 1.5.0 | Official Google SDK, supports tool use |
| UI | Chainlit 2.0 | Purpose-built for conversational agents |
| Google Sheets | `gspread` 6.1 + `google-auth` | Standard Python Sheets integration |
| Data layer | pandas 2.2 | Simple, no DB setup needed |
| Hosting | Render (free tier) | Supports persistent processes + WebSockets |
