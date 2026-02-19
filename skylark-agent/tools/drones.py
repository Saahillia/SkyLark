"""
tools/drones.py — Drone fleet management tools for SkyLark Drone Operations.

Tools:
  1. query_drones              — Filter drones by capability, location, status, weather resistance
  2. get_drone_details         — Full details for a specific drone
  3. filter_drones_by_weather  — Return drones safe to fly under a given weather condition
  4. update_drone_status       — Update drone status with Google Sheets sync
"""

import logging

from google.genai import types

import sheets
from data_store import get_drones_df

logger = logging.getLogger(__name__)

VALID_STATUSES = {"Available", "Maintenance", "Deployed", "Unavailable"}

# Drones with weather_resistance containing "IP43" can fly in Rainy conditions.
# All drones can fly in Sunny or Cloudy conditions.
_RAINY_KEYWORD = "IP43"


# ═══════════════════════════════════════════════════════════════
# TOOL 1: query_drones
# ═══════════════════════════════════════════════════════════════

def query_drones(
    capability: str = None,
    location: str = None,
    status: str = None,
    weather_resistant: bool = None,
) -> dict:
    """
    Search and filter drones. All parameters are optional.

    weather_resistant=True  → only IP43-rated drones (can fly in Rainy conditions)
    weather_resistant=False → only non-IP43 drones
    weather_resistant=None  → no weather filter applied
    """
    df = get_drones_df().copy()

    if capability:
        df = df[df["capabilities"].str.contains(capability.strip(), case=False, na=False)]
    if location:
        df = df[df["location"].str.lower() == location.strip().lower()]
    if status:
        df = df[df["status"].str.lower() == status.strip().lower()]
    if weather_resistant is True:
        df = df[df["weather_resistance"].str.contains(_RAINY_KEYWORD, case=False, na=False)]
    elif weather_resistant is False:
        df = df[~df["weather_resistance"].str.contains(_RAINY_KEYWORD, case=False, na=False)]

    if df.empty:
        return {
            "drones": [],
            "count": 0,
            "message": "No drones match the given criteria.",
        }

    return {
        "drones": df.to_dict(orient="records"),
        "count": len(df),
        "filters_applied": {
            k: v for k, v in {
                "capability": capability,
                "location": location,
                "status": status,
                "weather_resistant": weather_resistant,
            }.items() if v is not None
        },
    }


QUERY_DRONES_DECL = types.FunctionDeclaration(
    name="query_drones",
    description=(
        "Search and filter the drone fleet by capability, location, status, or weather resistance. "
        "All parameters are optional. "
        "Use this to find suitable drones for a mission before assigning."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "capability": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Drone capability to filter by. Valid values: LiDAR, RGB, Thermal. "
                    "Case-insensitive substring match."
                ),
            ),
            "location": types.Schema(
                type=types.Type.STRING,
                description="City to filter by, e.g. 'Bangalore' or 'Mumbai'.",
            ),
            "status": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Status to filter by. Valid values: Available, Maintenance, Deployed, Unavailable."
                ),
            ),
            "weather_resistant": types.Schema(
                type=types.Type.BOOLEAN,
                description=(
                    "If true, return only IP43-rated drones (safe for Rainy conditions). "
                    "If false, return only non-IP43 drones. Omit to return all."
                ),
            ),
        },
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 2: get_drone_details
# ═══════════════════════════════════════════════════════════════

def get_drone_details(drone_id: str) -> dict:
    """Return full details for a specific drone by ID."""
    df = get_drones_df()
    row = df[df["drone_id"] == drone_id.strip().upper()]

    if row.empty:
        return {
            "error": f"Drone '{drone_id}' not found. Valid IDs: "
                     + ", ".join(df["drone_id"].tolist())
        }

    drone = row.iloc[0].to_dict()

    # Enrich with parsed capability list
    drone["capabilities_list"] = [
        c.strip() for c in str(drone.get("capabilities", "")).split(";") if c.strip()
    ]
    drone["is_ip43_rated"] = _RAINY_KEYWORD in str(drone.get("weather_resistance", ""))
    drone["can_fly_rainy"] = drone["is_ip43_rated"]

    return {"drone": drone}


GET_DRONE_DETAILS_DECL = types.FunctionDeclaration(
    name="get_drone_details",
    description=(
        "Retrieve full details for a specific drone including model, capabilities, "
        "status, location, current assignment, maintenance due date, and weather resistance."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "drone_id": types.Schema(
                type=types.Type.STRING,
                description="Drone ID, e.g. 'D001', 'D002', 'D003', 'D004'.",
            ),
        },
        required=["drone_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 3: filter_drones_by_weather
# ═══════════════════════════════════════════════════════════════

def filter_drones_by_weather(weather_condition: str) -> dict:
    """
    Return drones that are safe to fly under the given weather condition.

    Rainy   → only IP43-rated drones
    Sunny   → all available drones (no rain restriction)
    Cloudy  → all available drones (no rain restriction)
    """
    condition = weather_condition.strip().capitalize()
    df = get_drones_df().copy()

    # Only return drones that are not in maintenance
    available_df = df[df["status"].str.lower() != "maintenance"].copy()

    if condition == "Rainy":
        eligible = available_df[
            available_df["weather_resistance"].str.contains(_RAINY_KEYWORD, case=False, na=False)
        ]
        ineligible = available_df[
            ~available_df["weather_resistance"].str.contains(_RAINY_KEYWORD, case=False, na=False)
        ]
        return {
            "weather_condition": condition,
            "eligible_drones": eligible.to_dict(orient="records"),
            "eligible_count": len(eligible),
            "ineligible_drones": ineligible.to_dict(orient="records"),
            "ineligible_count": len(ineligible),
            "rule": "Only IP43-rated drones may fly in Rainy conditions.",
            "warning": (
                f"{len(ineligible)} drone(s) are NOT rated for Rainy conditions and cannot be assigned."
                if len(ineligible) > 0 else None
            ),
        }
    else:
        # Sunny or Cloudy — all non-maintenance drones are eligible
        return {
            "weather_condition": condition,
            "eligible_drones": available_df.to_dict(orient="records"),
            "eligible_count": len(available_df),
            "ineligible_drones": [],
            "ineligible_count": 0,
            "rule": f"All available drones may fly in {condition} conditions.",
        }


FILTER_DRONES_BY_WEATHER_DECL = types.FunctionDeclaration(
    name="filter_drones_by_weather",
    description=(
        "Return drones eligible to fly under a given weather condition. "
        "In Rainy conditions, only IP43-rated drones are eligible. "
        "In Sunny or Cloudy conditions, all available drones are eligible. "
        "Also returns ineligible drones with a warning."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "weather_condition": types.Schema(
                type=types.Type.STRING,
                description="Weather condition to check. Valid values: Rainy, Sunny, Cloudy.",
            ),
        },
        required=["weather_condition"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: update_drone_status
# ═══════════════════════════════════════════════════════════════

def update_drone_status(drone_id: str, new_status: str) -> dict:
    """
    Update a drone's status in the in-memory DataFrame and sync to Google Sheets.
    Valid statuses: Available, Maintenance, Deployed, Unavailable.
    """
    drone_id = drone_id.strip().upper()
    new_status = new_status.strip()

    if new_status not in VALID_STATUSES:
        return {
            "error": f"Invalid status '{new_status}'. "
                     f"Valid values: {', '.join(sorted(VALID_STATUSES))}."
        }

    df = get_drones_df()
    if drone_id not in df["drone_id"].values:
        return {
            "error": f"Drone '{drone_id}' not found. Valid IDs: "
                     + ", ".join(df["drone_id"].tolist())
        }

    old_status = df.loc[df["drone_id"] == drone_id, "status"].iloc[0]

    synced = sheets.write_cell(
        tab_name="Drones",
        row_id=drone_id,
        id_col="drone_id",
        col_name="status",
        value=new_status,
        df=df,
    )

    return {
        "success": True,
        "drone_id": drone_id,
        "model": df.loc[df["drone_id"] == drone_id, "model"].iloc[0],
        "old_status": old_status,
        "new_status": new_status,
        "synced_to_sheets": synced,
        "message": (
            f"Status updated: {old_status} → {new_status}. "
            + ("Synced to Google Sheets." if synced else "Saved locally (Sheets sync unavailable).")
        ),
    }


UPDATE_DRONE_STATUS_DECL = types.FunctionDeclaration(
    name="update_drone_status",
    description=(
        "Update a drone's operational status. "
        "Immediately syncs the change back to the Google Sheets drone fleet sheet. "
        "Valid statuses: Available, Maintenance, Deployed, Unavailable."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "drone_id": types.Schema(
                type=types.Type.STRING,
                description="Drone ID to update, e.g. 'D001'.",
            ),
            "new_status": types.Schema(
                type=types.Type.STRING,
                description=(
                    "New status value. Must be one of: Available, Maintenance, Deployed, Unavailable."
                ),
            ),
        },
        required=["drone_id", "new_status"],
    ),
)
