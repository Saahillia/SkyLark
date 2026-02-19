"""
agent/core.py — Gemini 2.0 Flash agentic loop for SkyLark Drone Operations.

Provides:
  run_agent_turn(history, user_message) -> tuple[str, list]

The agent loop:
  1. Appends the user message to history
  2. Calls Gemini with all 17 tools registered
  3. If Gemini returns tool calls → executes them, feeds results back, repeats
  4. If Gemini returns a text response → returns it along with updated history

Safety circuit breaker: max 10 tool-call rounds per turn to prevent infinite loops.
"""

import logging
import os

from google import genai
from google.genai import types

from agent.prompts import SYSTEM_PROMPT
from tools import registry, all_declarations

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Gemini client setup
# ─────────────────────────────────────────────

MODEL = "gemini-2.0-flash"
MAX_TOOL_ROUNDS = 10  # circuit breaker

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    """Lazy-initialize the Gemini client."""
    global _client
    if _client is None:
        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError(
                "GEMINI_API_KEY environment variable is not set. "
                "Get a free key at https://aistudio.google.com/app/apikey"
            )
        _client = genai.Client(api_key=api_key)
        logger.info("[Agent] Gemini client initialized with model '%s'.", MODEL)
    return _client


# Build the Gemini Tool object once at import time
_TOOLS = [types.Tool(function_declarations=all_declarations)]

_CONFIG = types.GenerateContentConfig(
    system_instruction=SYSTEM_PROMPT,
    tools=_TOOLS,
    temperature=0.2,        # Low temperature for deterministic operational decisions
    max_output_tokens=4096,
)


# ─────────────────────────────────────────────
# History helpers
# ─────────────────────────────────────────────

def new_history() -> list:
    """Return an empty conversation history."""
    return []


def _append_user_text(history: list, text: str) -> list:
    return history + [{"role": "user", "parts": [{"text": text}]}]


def _append_model_text(history: list, text: str) -> list:
    return history + [{"role": "model", "parts": [{"text": text}]}]


# ─────────────────────────────────────────────
# Tool dispatcher
# ─────────────────────────────────────────────

def _execute_tool(name: str, args: dict) -> dict:
    """
    Execute a registered tool by name with the given arguments.
    Returns the result dict. Never raises — wraps exceptions in an error dict.
    """
    if name not in registry:
        logger.warning("[Agent] Unknown tool called: '%s'", name)
        return {"error": f"Tool '{name}' is not registered."}

    fn, _ = registry[name]
    try:
        result = fn(**args)
        logger.debug("[Agent] Tool '%s' returned: %s", name, str(result)[:200])
        return result
    except TypeError as e:
        logger.warning("[Agent] Tool '%s' called with bad args %s: %s", name, args, e)
        return {"error": f"Invalid arguments for tool '{name}': {e}"}
    except Exception as e:
        logger.error("[Agent] Tool '%s' raised an unexpected error: %s", name, e)
        return {"error": f"Tool '{name}' encountered an error: {e}"}


# ─────────────────────────────────────────────
# Main agentic loop
# ─────────────────────────────────────────────

def run_agent_turn(history: list, user_message: str) -> tuple[str, list]:
    """
    Run one complete agentic turn (may involve multiple internal tool-call rounds).

    Args:
        history      : Conversation history as a list of role/parts dicts.
                       Pass new_history() for the first turn.
        user_message : The user's latest message string.

    Returns:
        (final_text, updated_history)
        final_text     : The agent's final text response to display to the user.
        updated_history: The full updated conversation history for the next turn.
    """
    client = _get_client()

    # Append the user's message
    history = _append_user_text(history, user_message)

    for round_num in range(MAX_TOOL_ROUNDS):
        logger.debug("[Agent] Turn round %d — calling Gemini.", round_num + 1)

        try:
            response = client.models.generate_content(
                model=MODEL,
                contents=history,
                config=_CONFIG,
            )
        except Exception as e:
            error_msg = (
                f"I encountered an error while contacting the AI model: {e}\n\n"
                "Please check that your GEMINI_API_KEY is valid and try again."
            )
            logger.error("[Agent] Gemini API error: %s", e)
            return error_msg, _append_model_text(history, error_msg)

        # Extract parts from the first candidate
        candidate = response.candidates[0]
        parts = candidate.content.parts if candidate.content else []

        # Separate function calls from text parts
        function_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call]
        text_parts = [p for p in parts if hasattr(p, "text") and p.text]

        if not function_calls:
            # Terminal response — extract and return the text
            final_text = "\n".join(p.text for p in text_parts if p.text).strip()
            if not final_text:
                final_text = "I've completed the requested operations. Is there anything else you need?"
            history = _append_model_text(history, final_text)
            logger.debug("[Agent] Final response after %d round(s).", round_num + 1)
            return final_text, history

        # Append the model's tool-call turn to history
        # We convert parts to dicts for serialization
        model_parts_dicts = []
        for p in parts:
            if hasattr(p, "function_call") and p.function_call:
                model_parts_dicts.append({
                    "function_call": {
                        "name": p.function_call.name,
                        "args": dict(p.function_call.args),
                    }
                })
            elif hasattr(p, "text") and p.text:
                model_parts_dicts.append({"text": p.text})

        history = history + [{"role": "model", "parts": model_parts_dicts}]

        # Execute all function calls in this round
        tool_result_parts = []
        for fc_part in function_calls:
            fc = fc_part.function_call
            tool_name = fc.name
            tool_args = dict(fc.args) if fc.args else {}

            logger.info("[Agent] Executing tool: %s(%s)", tool_name, tool_args)
            result = _execute_tool(tool_name, tool_args)

            tool_result_parts.append({
                "function_response": {
                    "name": tool_name,
                    "response": result,
                }
            })

        # Feed tool results back as a "user" turn (Gemini API requirement)
        history = history + [{"role": "user", "parts": tool_result_parts}]

    # Circuit breaker triggered
    fallback = (
        "I've reached the maximum number of tool calls for this request. "
        "Please try a more specific question or break it into smaller steps."
    )
    logger.warning("[Agent] Circuit breaker triggered after %d rounds.", MAX_TOOL_ROUNDS)
    return fallback, _append_model_text(history, fallback)
