"""
tools/roster.py — Pilot roster management tools for SkyLark Drone Operations.

Tools:
  1. query_pilots          — Filter pilots by skill, certification, location, status
  2. get_pilot_details     — Full details for a specific pilot
  3. update_pilot_status   — Update pilot status with Google Sheets sync
  4. calculate_pilot_cost  — Calculate total pilot cost for a mission with budget check
"""

import logging
from datetime import date

from google.genai import types

import sheets
from data_store import get_pilots_df, get_missions_df

logger = logging.getLogger(__name__)

VALID_STATUSES = {"Available", "Assigned", "On Leave", "Unavailable"}


# ═══════════════════════════════════════════════════════════════
# TOOL 1: query_pilots
# ═══════════════════════════════════════════════════════════════

def query_pilots(
    skill: str = None,
    certification: str = None,
    location: str = None,
    status: str = None,
) -> dict:
    """
    Search and filter pilots. All parameters are optional — omit any to skip that filter.
    """
    df = get_pilots_df().copy()

    if skill:
        df = df[df["skills"].str.contains(skill.strip(), case=False, na=False)]
    if certification:
        df = df[df["certifications"].str.contains(certification.strip(), case=False, na=False)]
    if location:
        df = df[df["location"].str.lower() == location.strip().lower()]
    if status:
        df = df[df["status"].str.lower() == status.strip().lower()]

    if df.empty:
        return {
            "pilots": [],
            "count": 0,
            "message": "No pilots match the given criteria.",
        }

    return {
        "pilots": df.to_dict(orient="records"),
        "count": len(df),
        "filters_applied": {
            k: v for k, v in {
                "skill": skill, "certification": certification,
                "location": location, "status": status,
            }.items() if v is not None
        },
    }


QUERY_PILOTS_DECL = types.FunctionDeclaration(
    name="query_pilots",
    description=(
        "Search and filter pilots by skill, certification, location, or availability status. "
        "All parameters are optional — omit any to return all pilots. "
        "Use this to find pilots suitable for a mission before assigning."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "skill": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Skill to filter by. Valid values: Mapping, Survey, Inspection, Thermal. "
                    "Case-insensitive substring match."
                ),
            ),
            "certification": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Certification to filter by. Valid values: DGCA, Night Ops. "
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
                    "Status to filter by. Valid values: Available, Assigned, On Leave, Unavailable."
                ),
            ),
        },
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 2: get_pilot_details
# ═══════════════════════════════════════════════════════════════

def get_pilot_details(pilot_id: str) -> dict:
    """Return full details for a specific pilot by ID."""
    df = get_pilots_df()
    row = df[df["pilot_id"] == pilot_id.strip().upper()]

    if row.empty:
        return {
            "error": f"Pilot '{pilot_id}' not found. Valid IDs: "
                     + ", ".join(df["pilot_id"].tolist())
        }

    pilot = row.iloc[0].to_dict()

    # Enrich with parsed skill/cert lists for readability
    pilot["skills_list"] = [s.strip() for s in str(pilot.get("skills", "")).split(";") if s.strip()]
    pilot["certifications_list"] = [c.strip() for c in str(pilot.get("certifications", "")).split(";") if c.strip()]

    return {"pilot": pilot}


GET_PILOT_DETAILS_DECL = types.FunctionDeclaration(
    name="get_pilot_details",
    description=(
        "Retrieve full details for a specific pilot including skills, certifications, "
        "location, status, current assignment, and daily rate."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pilot_id": types.Schema(
                type=types.Type.STRING,
                description="Pilot ID, e.g. 'P001', 'P002', 'P003', 'P004'.",
            ),
        },
        required=["pilot_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 3: update_pilot_status
# ═══════════════════════════════════════════════════════════════

def update_pilot_status(pilot_id: str, new_status: str) -> dict:
    """
    Update a pilot's status in the in-memory DataFrame and sync to Google Sheets.
    Valid statuses: Available, Assigned, On Leave, Unavailable.
    """
    pilot_id = pilot_id.strip().upper()
    new_status = new_status.strip()

    if new_status not in VALID_STATUSES:
        return {
            "error": f"Invalid status '{new_status}'. "
                     f"Valid values: {', '.join(sorted(VALID_STATUSES))}."
        }

    df = get_pilots_df()
    if pilot_id not in df["pilot_id"].values:
        return {
            "error": f"Pilot '{pilot_id}' not found. Valid IDs: "
                     + ", ".join(df["pilot_id"].tolist())
        }

    old_status = df.loc[df["pilot_id"] == pilot_id, "status"].iloc[0]

    synced = sheets.write_cell(
        tab_name="Pilots",
        row_id=pilot_id,
        id_col="pilot_id",
        col_name="status",
        value=new_status,
        df=df,
    )

    return {
        "success": True,
        "pilot_id": pilot_id,
        "pilot_name": df.loc[df["pilot_id"] == pilot_id, "name"].iloc[0],
        "old_status": old_status,
        "new_status": new_status,
        "synced_to_sheets": synced,
        "message": (
            f"Status updated: {old_status} → {new_status}. "
            + ("Synced to Google Sheets." if synced else "Saved locally (Sheets sync unavailable).")
        ),
    }


UPDATE_PILOT_STATUS_DECL = types.FunctionDeclaration(
    name="update_pilot_status",
    description=(
        "Update a pilot's availability status. "
        "Immediately syncs the change back to the Google Sheets pilot roster. "
        "Valid statuses: Available, Assigned, On Leave, Unavailable."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pilot_id": types.Schema(
                type=types.Type.STRING,
                description="Pilot ID to update, e.g. 'P001'.",
            ),
            "new_status": types.Schema(
                type=types.Type.STRING,
                description=(
                    "New status value. Must be one of: Available, Assigned, On Leave, Unavailable."
                ),
            ),
        },
        required=["pilot_id", "new_status"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: calculate_pilot_cost
# ═══════════════════════════════════════════════════════════════

def calculate_pilot_cost(pilot_id: str, project_id: str) -> dict:
    """
    Calculate the total cost of assigning a pilot to a mission.

    Cost = daily_rate_inr × number_of_calendar_days
    Duration = (end_date - start_date).days + 1  (inclusive of both endpoints)
    """
    pilot_id = pilot_id.strip().upper()
    project_id = project_id.strip().upper()

    pilots_df = get_pilots_df()
    missions_df = get_missions_df()

    pilot_row = pilots_df[pilots_df["pilot_id"] == pilot_id]
    mission_row = missions_df[missions_df["project_id"] == project_id]

    if pilot_row.empty:
        return {"error": f"Pilot '{pilot_id}' not found."}
    if mission_row.empty:
        return {"error": f"Mission '{project_id}' not found."}

    pilot = pilot_row.iloc[0]
    mission = mission_row.iloc[0]

    try:
        start = date.fromisoformat(str(mission["start_date"]))
        end = date.fromisoformat(str(mission["end_date"]))
    except ValueError as e:
        return {"error": f"Invalid mission dates: {e}"}

    duration_days = (end - start).days + 1
    daily_rate = float(pilot["daily_rate_inr"])
    total_cost = daily_rate * duration_days
    budget = float(mission["mission_budget_inr"])
    budget_remaining = budget - total_cost
    within_budget = total_cost <= budget

    return {
        "pilot_id": pilot_id,
        "pilot_name": pilot["name"],
        "project_id": project_id,
        "client": mission["client"],
        "start_date": str(start),
        "end_date": str(end),
        "duration_days": duration_days,
        "daily_rate_inr": daily_rate,
        "total_pilot_cost_inr": total_cost,
        "mission_budget_inr": budget,
        "budget_remaining_inr": budget_remaining,
        "within_budget": within_budget,
        "budget_utilization_pct": round((total_cost / budget) * 100, 1) if budget > 0 else None,
        "warning": None if within_budget else (
            f"BUDGET OVERRUN: Pilot cost ₹{total_cost:,.0f} exceeds mission budget ₹{budget:,.0f} "
            f"by ₹{abs(budget_remaining):,.0f}."
        ),
    }


CALCULATE_PILOT_COST_DECL = types.FunctionDeclaration(
    name="calculate_pilot_cost",
    description=(
        "Calculate the total cost of assigning a pilot to a specific mission. "
        "Returns daily rate, mission duration in days, total pilot cost, mission budget, "
        "budget remaining, and a budget overrun warning if applicable."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pilot_id": types.Schema(
                type=types.Type.STRING,
                description="Pilot ID, e.g. 'P001'.",
            ),
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID, e.g. 'PRJ001'.",
            ),
        },
        required=["pilot_id", "project_id"],
    ),
)
