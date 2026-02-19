"""
data_store.py — Shared in-memory data layer for SkyLark Drone Operations.

Holds three pandas DataFrames as module-level globals so all tool modules
share a single source of truth without circular imports.

Usage:
    from data_store import init_data, get_pilots_df, get_drones_df, get_missions_df

Call init_data() exactly once at application startup (in Chainlit's on_chat_start).
After that, all tool modules call the getter functions to access live data.
"""

import os
import logging

import pandas as pd

import sheets

logger = logging.getLogger(__name__)

# Absolute path to the data directory (sibling of this file)
_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Module-level DataFrame globals — mutated in place by tool write operations
_pilots_df: pd.DataFrame | None = None
_drones_df: pd.DataFrame | None = None
_missions_df: pd.DataFrame | None = None

_initialized: bool = False


def _normalize_multivalue(df: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """
    Normalize multi-value fields to use semicolons consistently.

    Some CSVs may have been edited with commas inside values (e.g., "Mapping, Survey").
    This replaces comma-separated values with semicolons and strips extra whitespace
    so all tools can rely on ';' as the sole delimiter.
    """
    for col in columns:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.strip()
                .str.replace(r"\s*,\s*", ";", regex=True)
                .str.replace(r"\s*;\s*", ";", regex=True)
            )
    return df


def init_data() -> bool:
    """
    Load all three DataFrames from Google Sheets (if available) or local CSVs.

    This function is idempotent — calling it multiple times re-loads the data,
    which is useful for refreshing state between sessions.

    Returns:
        True if at least the pilots DataFrame was loaded with data.
    """
    global _pilots_df, _drones_df, _missions_df, _initialized

    pilots_path = os.path.join(_DATA_DIR, "pilot_roster.csv")
    drones_path = os.path.join(_DATA_DIR, "drone_fleet.csv")
    missions_path = os.path.join(_DATA_DIR, "missions.csv")

    _pilots_df = sheets.load_tab("Pilots", pilots_path)
    _drones_df = sheets.load_tab("Drones", drones_path)
    _missions_df = sheets.load_tab("Missions", missions_path)

    # Normalize multi-value fields
    _pilots_df = _normalize_multivalue(_pilots_df, ["skills", "certifications"])
    _drones_df = _normalize_multivalue(_drones_df, ["capabilities"])
    _missions_df = _normalize_multivalue(
        _missions_df,
        ["required_skills", "required_certs", "required_capabilities"],
    )

    # Ensure string columns that may have NaN are filled with "-" for safe comparisons
    for col in ["current_assignment", "assigned_pilot_id", "assigned_drone_id"]:
        if col in _pilots_df.columns:
            _pilots_df[col] = _pilots_df[col].fillna("-").astype(str).str.strip()
        if col in _missions_df.columns:
            _missions_df[col] = _missions_df[col].fillna("-").astype(str).str.strip()
        if col in _drones_df.columns:
            _drones_df[col] = _drones_df[col].fillna("-").astype(str).str.strip()

    source = "Google Sheets" if sheets.is_available() else "local CSV"
    logger.info(
        "[DataStore] Initialized from %s: %d pilots, %d drones, %d missions.",
        source,
        len(_pilots_df),
        len(_drones_df),
        len(_missions_df),
    )

    _initialized = True
    return len(_pilots_df) > 0


# ─────────────────────────────────────────────
# Accessor functions (used by all tool modules)
# ─────────────────────────────────────────────

def get_pilots_df() -> pd.DataFrame:
    """Return the live pilots DataFrame. Raises RuntimeError if not initialized."""
    if _pilots_df is None:
        raise RuntimeError("DataStore not initialized. Call init_data() first.")
    return _pilots_df


def get_drones_df() -> pd.DataFrame:
    """Return the live drones DataFrame. Raises RuntimeError if not initialized."""
    if _drones_df is None:
        raise RuntimeError("DataStore not initialized. Call init_data() first.")
    return _drones_df


def get_missions_df() -> pd.DataFrame:
    """Return the live missions DataFrame. Raises RuntimeError if not initialized."""
    if _missions_df is None:
        raise RuntimeError("DataStore not initialized. Call init_data() first.")
    return _missions_df


def is_initialized() -> bool:
    """Return True if init_data() has been called at least once."""
    return _initialized


def get_data_source() -> str:
    """Return a human-readable description of the active data source."""
    if sheets.is_available():
        return "Google Sheets (live sync enabled)"
    return "local CSV files (offline mode)"
