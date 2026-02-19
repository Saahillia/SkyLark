"""
tools/missions.py — Mission and assignment management tools for SkyLark Drone Operations.

Tools:
  1. query_missions           — Filter missions by status, priority, or location
  2. get_mission_details      — Full details for a specific mission
  3. assign_pilot_to_mission  — Assign a pilot (with conflict pre-check)
  4. assign_drone_to_mission  — Assign a drone (with conflict pre-check)
  5. get_active_assignments   — List all currently assigned/in-progress missions
"""

import logging

from google.genai import types

import sheets
from data_store import get_missions_df, get_pilots_df, get_drones_df

logger = logging.getLogger(__name__)

VALID_MISSION_STATUSES = {"Unassigned", "Assigned", "In Progress", "Completed", "Cancelled"}


# ═══════════════════════════════════════════════════════════════
# TOOL 1: query_missions
# ═══════════════════════════════════════════════════════════════

def query_missions(
    status: str = None,
    priority: str = None,
    location: str = None,
) -> dict:
    """Filter missions by status, priority, or location. All params optional."""
    df = get_missions_df().copy()

    if status:
        df = df[df["status"].str.lower() == status.strip().lower()]
    if priority:
        df = df[df["priority"].str.lower() == priority.strip().lower()]
    if location:
        df = df[df["location"].str.lower() == location.strip().lower()]

    if df.empty:
        return {
            "missions": [],
            "count": 0,
            "message": "No missions match the given criteria.",
        }

    return {
        "missions": df.to_dict(orient="records"),
        "count": len(df),
        "filters_applied": {
            k: v for k, v in {
                "status": status, "priority": priority, "location": location,
            }.items() if v is not None
        },
    }


QUERY_MISSIONS_DECL = types.FunctionDeclaration(
    name="query_missions",
    description=(
        "Search and filter missions by status, priority, or location. "
        "All parameters are optional — omit any to return all missions."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "status": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Mission status to filter by. "
                    "Valid values: Unassigned, Assigned, In Progress, Completed, Cancelled."
                ),
            ),
            "priority": types.Schema(
                type=types.Type.STRING,
                description="Priority to filter by. Valid values: High, Urgent, Standard.",
            ),
            "location": types.Schema(
                type=types.Type.STRING,
                description="City to filter by, e.g. 'Bangalore' or 'Mumbai'.",
            ),
        },
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 2: get_mission_details
# ═══════════════════════════════════════════════════════════════

def get_mission_details(project_id: str) -> dict:
    """Return full details for a specific mission by project ID."""
    df = get_missions_df()
    row = df[df["project_id"] == project_id.strip().upper()]

    if row.empty:
        return {
            "error": f"Mission '{project_id}' not found. Valid IDs: "
                     + ", ".join(df["project_id"].tolist())
        }

    mission = row.iloc[0].to_dict()

    # Enrich with parsed lists
    mission["required_skills_list"] = [
        s.strip() for s in str(mission.get("required_skills", "")).split(";") if s.strip()
    ]
    mission["required_certs_list"] = [
        c.strip() for c in str(mission.get("required_certs", "")).split(";") if c.strip()
    ]
    mission["required_capabilities_list"] = [
        c.strip() for c in str(mission.get("required_capabilities", "")).split(";") if c.strip()
    ]

    # Attach assigned pilot and drone details if present
    pilot_id = str(mission.get("assigned_pilot_id", "-")).strip()
    drone_id = str(mission.get("assigned_drone_id", "-")).strip()

    if pilot_id and pilot_id != "-":
        pilots_df = get_pilots_df()
        pilot_row = pilots_df[pilots_df["pilot_id"] == pilot_id]
        if not pilot_row.empty:
            p = pilot_row.iloc[0]
            mission["assigned_pilot_name"] = p["name"]
            mission["assigned_pilot_status"] = p["status"]

    if drone_id and drone_id != "-":
        drones_df = get_drones_df()
        drone_row = drones_df[drones_df["drone_id"] == drone_id]
        if not drone_row.empty:
            d = drone_row.iloc[0]
            mission["assigned_drone_model"] = d["model"]
            mission["assigned_drone_status"] = d["status"]

    return {"mission": mission}


GET_MISSION_DETAILS_DECL = types.FunctionDeclaration(
    name="get_mission_details",
    description=(
        "Retrieve full details for a specific mission including client, location, "
        "required skills and certifications, dates, budget, weather forecast, "
        "and current pilot/drone assignments."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Project ID, e.g. 'PRJ001', 'PRJ002', 'PRJ003'.",
            ),
        },
        required=["project_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 3: assign_pilot_to_mission
# ═══════════════════════════════════════════════════════════════

def assign_pilot_to_mission(project_id: str, pilot_id: str) -> dict:
    """
    Assign a pilot to a mission after running a conflict pre-check.

    HIGH severity conflicts block the assignment.
    MEDIUM/LOW severity conflicts are reported as warnings but do not block.
    """
    # Import here to avoid circular dependency (conflicts imports missions)
    from tools.conflicts import check_pilot_conflicts

    project_id = project_id.strip().upper()
    pilot_id = pilot_id.strip().upper()

    missions_df = get_missions_df()
    pilots_df = get_pilots_df()

    if missions_df[missions_df["project_id"] == project_id].empty:
        return {"error": f"Mission '{project_id}' not found."}
    if pilots_df[pilots_df["pilot_id"] == pilot_id].empty:
        return {"error": f"Pilot '{pilot_id}' not found."}

    # Pre-check conflicts
    conflict_report = check_pilot_conflicts(pilot_id, project_id)
    high_conflicts = [c for c in conflict_report.get("conflicts", []) if c["severity"] == "HIGH"]

    if high_conflicts:
        return {
            "success": False,
            "blocked": True,
            "reason": "Assignment blocked due to HIGH severity conflicts.",
            "project_id": project_id,
            "pilot_id": pilot_id,
            "conflicts": conflict_report["conflicts"],
            "resolution": "Resolve the HIGH conflicts first or use suggest_reassignment to find alternatives.",
        }

    # Proceed with assignment
    missions_df.loc[missions_df["project_id"] == project_id, "assigned_pilot_id"] = pilot_id
    missions_df.loc[missions_df["project_id"] == project_id, "status"] = "Assigned"

    # Update pilot current_assignment
    pilots_df.loc[pilots_df["pilot_id"] == pilot_id, "current_assignment"] = project_id
    pilots_df.loc[pilots_df["pilot_id"] == pilot_id, "status"] = "Assigned"

    # Sync pilot status to Sheets
    sheets.write_cell("Pilots", pilot_id, "pilot_id", "status", "Assigned", pilots_df)
    sheets.write_cell("Pilots", pilot_id, "pilot_id", "current_assignment", project_id, pilots_df)

    pilot_name = pilots_df.loc[pilots_df["pilot_id"] == pilot_id, "name"].iloc[0]
    warnings = [c for c in conflict_report.get("conflicts", []) if c["severity"] != "HIGH"]

    return {
        "success": True,
        "project_id": project_id,
        "pilot_id": pilot_id,
        "pilot_name": pilot_name,
        "message": f"Pilot {pilot_name} ({pilot_id}) assigned to {project_id}.",
        "warnings": warnings,
        "synced_to_sheets": True,
    }


ASSIGN_PILOT_DECL = types.FunctionDeclaration(
    name="assign_pilot_to_mission",
    description=(
        "Assign a pilot to a mission. "
        "Automatically runs a conflict pre-check (double-booking, skill/cert mismatch, "
        "budget overrun, location mismatch). "
        "HIGH severity conflicts block the assignment. "
        "MEDIUM/LOW conflicts are reported as warnings."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID, e.g. 'PRJ001'.",
            ),
            "pilot_id": types.Schema(
                type=types.Type.STRING,
                description="Pilot ID to assign, e.g. 'P001'.",
            ),
        },
        required=["project_id", "pilot_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: assign_drone_to_mission
# ═══════════════════════════════════════════════════════════════

def assign_drone_to_mission(project_id: str, drone_id: str) -> dict:
    """
    Assign a drone to a mission after running a conflict pre-check.

    HIGH severity conflicts block the assignment.
    MEDIUM/LOW severity conflicts are reported as warnings but do not block.
    """
    from tools.conflicts import check_drone_conflicts

    project_id = project_id.strip().upper()
    drone_id = drone_id.strip().upper()

    missions_df = get_missions_df()
    drones_df = get_drones_df()

    if missions_df[missions_df["project_id"] == project_id].empty:
        return {"error": f"Mission '{project_id}' not found."}
    if drones_df[drones_df["drone_id"] == drone_id].empty:
        return {"error": f"Drone '{drone_id}' not found."}

    # Pre-check conflicts
    conflict_report = check_drone_conflicts(drone_id, project_id)
    high_conflicts = [c for c in conflict_report.get("conflicts", []) if c["severity"] == "HIGH"]

    if high_conflicts:
        return {
            "success": False,
            "blocked": True,
            "reason": "Assignment blocked due to HIGH severity conflicts.",
            "project_id": project_id,
            "drone_id": drone_id,
            "conflicts": conflict_report["conflicts"],
            "resolution": "Resolve the HIGH conflicts first or use suggest_reassignment to find alternatives.",
        }

    # Proceed with assignment
    missions_df.loc[missions_df["project_id"] == project_id, "assigned_drone_id"] = drone_id
    missions_df.loc[missions_df["project_id"] == project_id, "status"] = "Assigned"

    # Update drone current_assignment
    drones_df.loc[drones_df["drone_id"] == drone_id, "current_assignment"] = project_id
    drones_df.loc[drones_df["drone_id"] == drone_id, "status"] = "Deployed"

    # Sync drone status to Sheets
    sheets.write_cell("Drones", drone_id, "drone_id", "status", "Deployed", drones_df)
    sheets.write_cell("Drones", drone_id, "drone_id", "current_assignment", project_id, drones_df)

    drone_model = drones_df.loc[drones_df["drone_id"] == drone_id, "model"].iloc[0]
    warnings = [c for c in conflict_report.get("conflicts", []) if c["severity"] != "HIGH"]

    return {
        "success": True,
        "project_id": project_id,
        "drone_id": drone_id,
        "drone_model": drone_model,
        "message": f"Drone {drone_model} ({drone_id}) assigned to {project_id}.",
        "warnings": warnings,
        "synced_to_sheets": True,
    }


ASSIGN_DRONE_DECL = types.FunctionDeclaration(
    name="assign_drone_to_mission",
    description=(
        "Assign a drone to a mission. "
        "Automatically runs a conflict pre-check (maintenance status, double-booking, "
        "weather risk, capability mismatch, location mismatch). "
        "HIGH severity conflicts block the assignment. "
        "MEDIUM/LOW conflicts are reported as warnings."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID, e.g. 'PRJ001'.",
            ),
            "drone_id": types.Schema(
                type=types.Type.STRING,
                description="Drone ID to assign, e.g. 'D001'.",
            ),
        },
        required=["project_id", "drone_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 5: get_active_assignments
# ═══════════════════════════════════════════════════════════════

def get_active_assignments() -> dict:
    """
    Return all missions with status Assigned or In Progress,
    along with their assigned pilot and drone details.
    """
    missions_df = get_missions_df()
    pilots_df = get_pilots_df()
    drones_df = get_drones_df()

    active = missions_df[
        missions_df["status"].isin(["Assigned", "In Progress"])
    ].copy()

    if active.empty:
        return {
            "active_assignments": [],
            "count": 0,
            "message": "No active assignments currently.",
        }

    assignments = []
    for _, row in active.iterrows():
        entry = row.to_dict()

        # Enrich with pilot info
        pilot_id = str(entry.get("assigned_pilot_id", "-")).strip()
        if pilot_id and pilot_id != "-":
            p_row = pilots_df[pilots_df["pilot_id"] == pilot_id]
            if not p_row.empty:
                entry["pilot_name"] = p_row.iloc[0]["name"]
                entry["pilot_status"] = p_row.iloc[0]["status"]
                entry["pilot_location"] = p_row.iloc[0]["location"]

        # Enrich with drone info
        drone_id = str(entry.get("assigned_drone_id", "-")).strip()
        if drone_id and drone_id != "-":
            d_row = drones_df[drones_df["drone_id"] == drone_id]
            if not d_row.empty:
                entry["drone_model"] = d_row.iloc[0]["model"]
                entry["drone_status"] = d_row.iloc[0]["status"]
                entry["drone_location"] = d_row.iloc[0]["location"]

        assignments.append(entry)

    return {
        "active_assignments": assignments,
        "count": len(assignments),
    }


GET_ACTIVE_ASSIGNMENTS_DECL = types.FunctionDeclaration(
    name="get_active_assignments",
    description=(
        "List all currently active missions (status: Assigned or In Progress) "
        "with their assigned pilot and drone details including names, locations, and statuses."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)
