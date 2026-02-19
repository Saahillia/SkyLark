"""
app.py — SkyLark Drone Operations Coordinator
Chainlit entry point.

Environment variables required:
  GEMINI_API_KEY          — Gemini 2.0 Flash API key (required)
  GOOGLE_CREDENTIALS_JSON — Service account JSON for Sheets sync (optional)
  SPREADSHEET_ID          — Google Sheets ID (optional, required if using Sheets)
  CHAINLIT_AUTH_SECRET    — Chainlit session secret (required in production)

Run locally:
  chainlit run app.py
"""

import asyncio
import logging
import os

import chainlit as cl
from dotenv import load_dotenv

# Load .env file for local development (no-op in production)
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# Import agent after env vars are loaded
from agent.core import run_agent_turn, new_history
from data_store import init_data, get_data_source


# ─────────────────────────────────────────────────────────────
# Welcome message shown at the start of every session
# ─────────────────────────────────────────────────────────────

WELCOME_MESSAGE = """Welcome to **SkyLark Drone Operations Coordinator**.

I manage your pilot roster, drone fleet, mission assignments, and conflict detection — all in one place.

**What I can do:**

**Roster Management**
- Find pilots by skill, certification, or location
- Check pilot availability and current assignments
- Calculate mission costs per pilot
- Update pilot status (syncs to Google Sheets)

**Drone Inventory**
- Query the fleet by capability, location, or status
- Filter drones by weather resistance (IP43 for Rainy missions)
- Update drone status (syncs to Google Sheets)
- Flag maintenance issues

**Assignment Tracking**
- Assign pilots and drones to missions (with automatic conflict checks)
- View all active assignments
- Handle urgent reassignments with ranked alternatives

**Conflict Detection**
- Full operational audit across all active missions
- Double-booking, skill/cert mismatches, budget overruns
- Weather risk alerts and location mismatch warnings

---
**Try asking:**
- *"Show me all active assignments"*
- *"Find available pilots in Bangalore with Mapping skills"*
- *"Check conflicts for PRJ002"*
- *"Suggest a reassignment for PRJ002"*
- *"Which drones can fly in Rainy weather?"*
- *"How much will Arjun cost for PRJ001?"*
"""


# ─────────────────────────────────────────────────────────────
# Chainlit lifecycle hooks
# ─────────────────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    """
    Initialize a new chat session.
    - Load data from Google Sheets (or CSV fallback)
    - Set empty conversation history
    - Send welcome message
    """
    logger.info("[App] New chat session started.")

    # Initialize DataFrames (blocking I/O — run in thread to avoid blocking event loop)
    try:
        await asyncio.to_thread(init_data)
        source = get_data_source()
        logger.info("[App] Data initialized from: %s", source)
    except Exception as e:
        logger.error("[App] Data initialization error: %s", e)
        await cl.Message(
            content=(
                "**Warning:** Failed to load operational data. "
                f"Error: {e}\n\n"
                "Please check your environment variables and try refreshing."
            )
        ).send()
        return

    # Initialize empty conversation history for this session
    cl.user_session.set("history", new_history())

    # Append data source info to welcome message
    data_note = f"\n\n*Data source: {get_data_source()}*"
    await cl.Message(content=WELCOME_MESSAGE + data_note).send()


@cl.on_message
async def on_message(message: cl.Message):
    """
    Handle an incoming user message.
    - Run the Gemini agentic loop (may call multiple tools internally)
    - Update conversation history
    - Display the response
    """
    history = cl.user_session.get("history", new_history())

    # Send an empty message immediately to show activity
    response_msg = cl.Message(content="")
    await response_msg.send()

    try:
        # Run agent in a thread (synchronous Gemini API calls)
        response_text, updated_history = await asyncio.to_thread(
            run_agent_turn, history, message.content
        )
        cl.user_session.set("history", updated_history)
        response_msg.content = response_text
        await response_msg.update()

    except RuntimeError as e:
        # Configuration errors (e.g., missing GEMINI_API_KEY)
        error_text = (
            f"**Configuration Error:** {e}\n\n"
            "Please set your `GEMINI_API_KEY` environment variable and restart."
        )
        logger.error("[App] RuntimeError in on_message: %s", e)
        response_msg.content = error_text
        await response_msg.update()

    except Exception as e:
        error_text = (
            f"**Unexpected Error:** {e}\n\n"
            "Please try again. If the issue persists, rephrase your request."
        )
        logger.error("[App] Unexpected error in on_message: %s", e, exc_info=True)
        response_msg.content = error_text
        await response_msg.update()
