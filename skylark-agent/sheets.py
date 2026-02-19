"""
sheets.py — Google Sheets 2-way sync for SkyLark Drone Operations.

Provides:
  - load_tab(tab_name, csv_path)  → pd.DataFrame  (read from Sheets, fallback to CSV)
  - write_cell(...)               → bool           (write single cell back to Sheets)

Supports either:
  - A single spreadsheet with 3 tabs (SPREADSHEET_ID)
  - Three separate spreadsheets (PILOTS_SPREADSHEET_ID, DRONES_SPREADSHEET_ID, MISSIONS_SPREADSHEET_ID)

All functions catch exceptions gracefully and never crash the application.
If Sheets is unavailable, the app continues using local CSV data.
"""

import os
import json
import logging

import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# Maps tab name → env var name for separate-spreadsheet mode
_TAB_ENV_MAP = {
    "Pilots":   "PILOTS_SPREADSHEET_ID",
    "Drones":   "DRONES_SPREADSHEET_ID",
    "Missions": "MISSIONS_SPREADSHEET_ID",
}

# Module-level singletons
_gc: gspread.Client | None = None
_sheets: dict[str, gspread.Spreadsheet] = {}   # tab_name → Spreadsheet
_sheets_available: bool = False


def _connect() -> bool:
    """
    Attempt to connect to Google Sheets using the service account credentials
    stored in the GOOGLE_CREDENTIALS_JSON environment variable.

    Supports two modes:
      1. Single spreadsheet: SPREADSHEET_ID (all 3 tabs in one sheet)
      2. Separate spreadsheets: PILOTS_SPREADSHEET_ID, DRONES_SPREADSHEET_ID,
                                MISSIONS_SPREADSHEET_ID

    Returns True if at least one connection succeeded, False otherwise.
    """
    global _gc, _sheets, _sheets_available

    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_json:
        logger.info(
            "[Sheets] GOOGLE_CREDENTIALS_JSON not set. Running in CSV-only mode."
        )
        return False

    # Resolve spreadsheet IDs — separate IDs take priority over single ID
    single_id = os.environ.get("SPREADSHEET_ID", "").strip()
    tab_ids: dict[str, str] = {}

    for tab, env_var in _TAB_ENV_MAP.items():
        sid = os.environ.get(env_var, "").strip()
        if sid:
            tab_ids[tab] = sid
        elif single_id:
            tab_ids[tab] = single_id   # all tabs share the same spreadsheet

    if not tab_ids:
        logger.info(
            "[Sheets] No spreadsheet ID env vars set. Running in CSV-only mode."
        )
        return False

    try:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        _gc = gspread.authorize(creds)
    except json.JSONDecodeError as e:
        logger.warning("[Sheets] Invalid JSON in GOOGLE_CREDENTIALS_JSON: %s", e)
        return False
    except Exception as e:
        logger.warning("[Sheets] Failed to build credentials: %s", e)
        return False

    # Open each spreadsheet (de-duplicated so shared IDs only open once)
    opened: dict[str, gspread.Spreadsheet] = {}
    for tab, sheet_id in tab_ids.items():
        if sheet_id in opened:
            _sheets[tab] = opened[sheet_id]
            continue
        try:
            sh = _gc.open_by_key(sheet_id)
            _sheets[tab] = sh
            opened[sheet_id] = sh
            logger.info(
                "[Sheets] Connected '%s' → spreadsheet '%s' (%s).",
                tab, sh.title, sheet_id[:12] + "...",
            )
        except gspread.exceptions.APIError as e:
            logger.warning(
                "[Sheets] API error opening spreadsheet for '%s' (%s): %s",
                tab, sheet_id[:12] + "...", e,
            )
        except Exception as e:
            logger.warning(
                "[Sheets] Failed to open spreadsheet for '%s': %s", tab, e
            )

    _sheets_available = bool(_sheets)
    return _sheets_available


def is_available() -> bool:
    """Return True if at least one Sheets connection is active."""
    return _sheets_available


def load_tab(tab_name: str, csv_path: str) -> pd.DataFrame:
    """
    Load a worksheet from Google Sheets for the given tab_name.

    Resolution order within the spreadsheet:
      1. A worksheet named exactly tab_name (e.g. "Pilots")
      2. The first worksheet in the spreadsheet (fallback for single-tab sheets)

    Falls back to reading csv_path if Sheets is unavailable.

    Args:
        tab_name: Logical tab name — "Pilots", "Drones", or "Missions".
        csv_path: Absolute path to the local CSV fallback file.

    Returns:
        A pandas DataFrame with the tab's data.
    """
    if _sheets_available and tab_name in _sheets:
        sh = _sheets[tab_name]
        try:
            # Try the named worksheet first
            try:
                ws = sh.worksheet(tab_name)
            except gspread.exceptions.WorksheetNotFound:
                # Fall back to first worksheet (for single-tab sheets)
                ws = sh.get_worksheet(0)
                logger.info(
                    "[Sheets] Tab '%s' not found by name in '%s'; using first worksheet.",
                    tab_name, sh.title,
                )

            records = ws.get_all_records()
            if records:
                df = pd.DataFrame(records)
                logger.info(
                    "[Sheets] Loaded %d rows from '%s' (sheet: %s).",
                    len(df), tab_name, sh.title,
                )
                return df
            else:
                logger.warning(
                    "[Sheets] Worksheet for '%s' is empty. Falling back to CSV.",
                    tab_name,
                )
        except gspread.exceptions.APIError as e:
            logger.warning(
                "[Sheets] API error reading '%s': %s. Falling back to CSV.",
                tab_name, e,
            )
        except Exception as e:
            logger.warning(
                "[Sheets] Error reading '%s': %s. Falling back to CSV.", tab_name, e
            )

    # CSV fallback
    try:
        df = pd.read_csv(csv_path)
        logger.info("[CSV] Loaded %d rows from '%s'.", len(df), csv_path)
        return df
    except FileNotFoundError:
        logger.error("[CSV] File not found: %s", csv_path)
        return pd.DataFrame()
    except Exception as e:
        logger.error("[CSV] Error reading '%s': %s", csv_path, e)
        return pd.DataFrame()


def write_cell(
    tab_name: str,
    row_id: str,
    id_col: str,
    col_name: str,
    value: str,
    df: pd.DataFrame,
) -> bool:
    """
    Write a single cell value back to Google Sheets and update the in-memory DataFrame.

    The in-memory DataFrame is ALWAYS updated regardless of whether Sheets sync succeeds.
    This ensures the agent remains consistent within a session even if Sheets is down.

    Args:
        tab_name : Logical tab name (e.g., "Pilots").
        row_id   : The identifier value in id_col that locates the row (e.g., "P001").
        id_col   : Column name used as the row identifier (e.g., "pilot_id").
        col_name : Column to update (e.g., "status").
        value    : New value to write (e.g., "Available").
        df       : The in-memory DataFrame to update in place.

    Returns:
        True if Sheets was updated successfully, False if the update was local-only.
    """
    # Always update in-memory DataFrame first
    mask = df[id_col] == row_id
    if not mask.any():
        logger.warning(
            "[Sheets] write_cell: row '%s' not found in column '%s'.", row_id, id_col
        )
        return False

    df.loc[mask, col_name] = value

    if not _sheets_available or tab_name not in _sheets:
        logger.info(
            "[Sheets] write_cell: Sheets unavailable for '%s'. In-memory update only "
            "(%s=%s).",
            tab_name, col_name, value,
        )
        return False

    sh = _sheets[tab_name]
    try:
        # Use named worksheet if it exists, else first worksheet
        try:
            ws = sh.worksheet(tab_name)
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.get_worksheet(0)

        headers = ws.row_values(1)

        if col_name not in headers:
            logger.warning(
                "[Sheets] Column '%s' not found in '%s' headers.", col_name, tab_name
            )
            return False
        if id_col not in headers:
            logger.warning(
                "[Sheets] ID column '%s' not found in '%s' headers.", id_col, tab_name
            )
            return False

        col_idx = headers.index(col_name) + 1       # 1-based
        id_col_idx = headers.index(id_col) + 1      # 1-based

        id_values = ws.col_values(id_col_idx)
        if row_id not in id_values:
            logger.warning(
                "[Sheets] Row ID '%s' not found in Sheets column '%s'.", row_id, id_col
            )
            return False

        row_idx = id_values.index(row_id) + 1       # 1-based
        ws.update_cell(row_idx, col_idx, value)

        logger.info(
            "[Sheets] Updated %s[%s].%s = '%s' (row %d, col %d).",
            tab_name, row_id, col_name, value, row_idx, col_idx,
        )
        return True

    except gspread.exceptions.APIError as e:
        logger.warning("[Sheets] API error during write_cell: %s", e)
    except Exception as e:
        logger.warning("[Sheets] Unexpected error during write_cell: %s", e)

    return False


# Attempt connection when this module is first imported.
_connect()
