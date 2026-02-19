"""
tools/conflicts.py — Conflict detection and urgent reassignment tools.

Tools:
  1. check_pilot_conflicts   — All conflict types for a pilot-mission pairing
  2. check_drone_conflicts   — All conflict types for a drone-mission pairing
  3. detect_all_conflicts    — Full audit across all active assignments
  4. suggest_reassignment    — Ranked alternative pilot/drone candidates for a mission
"""

import logging
from datetime import date

from google.genai import types

from data_store import get_pilots_df, get_drones_df, get_missions_df

logger = logging.getLogger(__name__)

_RAINY_KEYWORD = "IP43"


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _parse_list(value: str) -> list[str]:
    """Split a semicolon-separated string into a stripped, non-empty list."""
    return [item.strip() for item in str(value).split(";") if item.strip()]


def _dates_overlap(start1: date, end1: date, start2: date, end2: date) -> bool:
    """Return True if two date ranges overlap (inclusive on both ends)."""
    return start1 <= end2 and end1 >= start2


def _parse_date(value: str) -> date | None:
    """Parse an ISO date string; return None on failure."""
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        return None


# ═══════════════════════════════════════════════════════════════
# TOOL 1: check_pilot_conflicts
# ═══════════════════════════════════════════════════════════════

def check_pilot_conflicts(pilot_id: str, project_id: str) -> dict:
    """
    Check all conflict types for assigning a pilot to a mission.

    Conflict types detected:
      DOUBLE_BOOKING   — pilot already assigned to an overlapping mission
      PILOT_ON_LEAVE   — pilot's status is On Leave
      PILOT_UNAVAILABLE— pilot's status is Unavailable
      SKILL_MISMATCH   — pilot lacks required skills
      CERT_MISMATCH    — pilot lacks required certifications  (HIGH)
      BUDGET_OVERRUN   — pilot cost > mission budget          (MEDIUM)
      LOCATION_MISMATCH— pilot city ≠ mission city           (LOW)
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
    conflicts = []

    m_start = _parse_date(mission["start_date"])
    m_end = _parse_date(mission["end_date"])

    # 1. STATUS CHECKS
    pilot_status = str(pilot["status"]).strip()
    if pilot_status == "On Leave":
        conflicts.append({
            "type": "PILOT_ON_LEAVE",
            "severity": "HIGH",
            "detail": (
                f"Pilot {pilot['name']} is On Leave"
                + (f" until {pilot['available_from']}." if pilot.get("available_from") else ".")
            ),
            "resolution": "Choose an available pilot or wait for their return date.",
        })
    elif pilot_status == "Unavailable":
        conflicts.append({
            "type": "PILOT_UNAVAILABLE",
            "severity": "HIGH",
            "detail": f"Pilot {pilot['name']} is marked Unavailable.",
            "resolution": "Update pilot status to Available when ready.",
        })

    # 2. DOUBLE-BOOKING
    if m_start and m_end:
        other_missions = missions_df[
            (missions_df["assigned_pilot_id"] == pilot_id)
            & (missions_df["project_id"] != project_id)
            & (missions_df["status"].isin(["Assigned", "In Progress"]))
        ]
        for _, other in other_missions.iterrows():
            o_start = _parse_date(other["start_date"])
            o_end = _parse_date(other["end_date"])
            if o_start and o_end and _dates_overlap(m_start, m_end, o_start, o_end):
                conflicts.append({
                    "type": "DOUBLE_BOOKING",
                    "severity": "HIGH",
                    "detail": (
                        f"Pilot is already assigned to {other['project_id']} "
                        f"({other['client']}) from {o_start} to {o_end}."
                    ),
                    "resolution": f"Reassign {other['project_id']} or adjust the mission dates.",
                })

    # 3. SKILL MISMATCH
    required_skills = _parse_list(mission.get("required_skills", ""))
    pilot_skills = _parse_list(pilot.get("skills", ""))
    missing_skills = [s for s in required_skills if s not in pilot_skills]
    if missing_skills:
        conflicts.append({
            "type": "SKILL_MISMATCH",
            "severity": "MEDIUM",
            "detail": f"Mission requires skills {required_skills}; pilot has {pilot_skills}. Missing: {missing_skills}.",
            "resolution": "Find a pilot with the missing skills.",
        })

    # 4. CERTIFICATION MISMATCH
    required_certs = _parse_list(mission.get("required_certs", ""))
    pilot_certs = _parse_list(pilot.get("certifications", ""))
    missing_certs = [c for c in required_certs if c not in pilot_certs]
    if missing_certs:
        conflicts.append({
            "type": "CERT_MISMATCH",
            "severity": "HIGH",
            "detail": f"Mission requires certs {required_certs}; pilot holds {pilot_certs}. Missing: {missing_certs}.",
            "resolution": "Find a pilot with the required certifications.",
        })

    # 5. BUDGET OVERRUN
    if m_start and m_end:
        duration_days = (m_end - m_start).days + 1
        daily_rate = float(pilot.get("daily_rate_inr", 0))
        total_cost = daily_rate * duration_days
        budget = float(mission.get("mission_budget_inr", 0))
        if budget > 0 and total_cost > budget:
            conflicts.append({
                "type": "BUDGET_OVERRUN",
                "severity": "MEDIUM",
                "detail": (
                    f"Pilot cost ₹{total_cost:,.0f} ({duration_days}d × ₹{daily_rate:,.0f}/day) "
                    f"exceeds mission budget ₹{budget:,.0f} by ₹{total_cost - budget:,.0f}."
                ),
                "resolution": "Choose a lower-rate pilot or increase the mission budget.",
            })

    # 6. LOCATION MISMATCH
    if str(pilot["location"]).strip().lower() != str(mission["location"]).strip().lower():
        conflicts.append({
            "type": "LOCATION_MISMATCH",
            "severity": "LOW",
            "detail": (
                f"Pilot is in {pilot['location']}; mission is in {mission['location']}."
            ),
            "resolution": "Arrange travel or find a pilot already in the mission city.",
        })

    severities = [c["severity"] for c in conflicts]
    overall = (
        "HIGH" if "HIGH" in severities else
        "MEDIUM" if "MEDIUM" in severities else
        "LOW" if "LOW" in severities else
        "NONE"
    )

    return {
        "pilot_id": pilot_id,
        "pilot_name": pilot["name"],
        "project_id": project_id,
        "mission_client": mission["client"],
        "conflict_count": len(conflicts),
        "has_conflicts": len(conflicts) > 0,
        "overall_severity": overall,
        "conflicts": conflicts,
    }


CHECK_PILOT_CONFLICTS_DECL = types.FunctionDeclaration(
    name="check_pilot_conflicts",
    description=(
        "Check all conflict types for assigning a specific pilot to a specific mission. "
        "Detects: double-booking, pilot on leave/unavailable, skill mismatch, "
        "certification mismatch, budget overrun, and location mismatch. "
        "Returns a structured report with severity levels (HIGH/MEDIUM/LOW) and resolution hints."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "pilot_id": types.Schema(
                type=types.Type.STRING,
                description="Pilot ID to check, e.g. 'P001'.",
            ),
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID to check against, e.g. 'PRJ001'.",
            ),
        },
        required=["pilot_id", "project_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 2: check_drone_conflicts
# ═══════════════════════════════════════════════════════════════

def check_drone_conflicts(drone_id: str, project_id: str) -> dict:
    """
    Check all conflict types for assigning a drone to a mission.

    Conflict types detected:
      DRONE_IN_MAINTENANCE  — drone status is Maintenance     (HIGH)
      DOUBLE_BOOKING        — drone already assigned to overlapping mission (HIGH)
      WEATHER_RISK          — non-IP43 drone on Rainy mission (HIGH)
      CAPABILITY_MISMATCH   — drone lacks required capabilities (MEDIUM)
      LOCATION_MISMATCH     — drone city ≠ mission city       (LOW)
    """
    drone_id = drone_id.strip().upper()
    project_id = project_id.strip().upper()

    drones_df = get_drones_df()
    missions_df = get_missions_df()

    drone_row = drones_df[drones_df["drone_id"] == drone_id]
    mission_row = missions_df[missions_df["project_id"] == project_id]

    if drone_row.empty:
        return {"error": f"Drone '{drone_id}' not found."}
    if mission_row.empty:
        return {"error": f"Mission '{project_id}' not found."}

    drone = drone_row.iloc[0]
    mission = mission_row.iloc[0]
    conflicts = []

    m_start = _parse_date(mission["start_date"])
    m_end = _parse_date(mission["end_date"])

    # 1. MAINTENANCE CHECK
    if str(drone["status"]).strip().lower() == "maintenance":
        maint_due = drone.get("maintenance_due", "unknown")
        conflicts.append({
            "type": "DRONE_IN_MAINTENANCE",
            "severity": "HIGH",
            "detail": f"Drone {drone['model']} ({drone_id}) is currently in Maintenance (due: {maint_due}).",
            "resolution": "Wait until maintenance is complete or choose a different drone.",
        })

    # 2. DOUBLE-BOOKING
    if m_start and m_end:
        other_missions = missions_df[
            (missions_df["assigned_drone_id"] == drone_id)
            & (missions_df["project_id"] != project_id)
            & (missions_df["status"].isin(["Assigned", "In Progress"]))
        ]
        for _, other in other_missions.iterrows():
            o_start = _parse_date(other["start_date"])
            o_end = _parse_date(other["end_date"])
            if o_start and o_end and _dates_overlap(m_start, m_end, o_start, o_end):
                conflicts.append({
                    "type": "DOUBLE_BOOKING",
                    "severity": "HIGH",
                    "detail": (
                        f"Drone is already assigned to {other['project_id']} "
                        f"({other['client']}) from {o_start} to {o_end}."
                    ),
                    "resolution": f"Reassign {other['project_id']} or adjust the mission dates.",
                })

    # 3. WEATHER RISK
    weather_forecast = str(mission.get("weather_forecast", "")).strip().capitalize()
    is_ip43 = _RAINY_KEYWORD in str(drone.get("weather_resistance", ""))
    if weather_forecast == "Rainy" and not is_ip43:
        conflicts.append({
            "type": "WEATHER_RISK",
            "severity": "HIGH",
            "detail": (
                f"Mission weather forecast is Rainy but drone {drone['model']} ({drone_id}) "
                f"is not IP43-rated (weather resistance: {drone.get('weather_resistance', 'None')})."
            ),
            "resolution": "Assign an IP43-rated drone (D001 DJI M300 or D003 DJI Mavic 3T).",
        })

    # 4. CAPABILITY MISMATCH
    required_caps = _parse_list(mission.get("required_capabilities", ""))
    drone_caps = _parse_list(drone.get("capabilities", ""))
    missing_caps = [c for c in required_caps if c not in drone_caps]
    if missing_caps:
        conflicts.append({
            "type": "CAPABILITY_MISMATCH",
            "severity": "MEDIUM",
            "detail": (
                f"Mission requires capabilities {required_caps}; "
                f"drone has {drone_caps}. Missing: {missing_caps}."
            ),
            "resolution": "Find a drone with the required capabilities.",
        })

    # 5. LOCATION MISMATCH
    if str(drone["location"]).strip().lower() != str(mission["location"]).strip().lower():
        conflicts.append({
            "type": "LOCATION_MISMATCH",
            "severity": "LOW",
            "detail": f"Drone is in {drone['location']}; mission is in {mission['location']}.",
            "resolution": "Transport the drone to the mission location or use a local drone.",
        })

    severities = [c["severity"] for c in conflicts]
    overall = (
        "HIGH" if "HIGH" in severities else
        "MEDIUM" if "MEDIUM" in severities else
        "LOW" if "LOW" in severities else
        "NONE"
    )

    return {
        "drone_id": drone_id,
        "drone_model": drone["model"],
        "project_id": project_id,
        "mission_client": mission["client"],
        "conflict_count": len(conflicts),
        "has_conflicts": len(conflicts) > 0,
        "overall_severity": overall,
        "conflicts": conflicts,
    }


CHECK_DRONE_CONFLICTS_DECL = types.FunctionDeclaration(
    name="check_drone_conflicts",
    description=(
        "Check all conflict types for assigning a specific drone to a specific mission. "
        "Detects: drone in maintenance, double-booking, weather risk (non-IP43 on Rainy mission), "
        "capability mismatch, and location mismatch. "
        "Returns a structured report with severity levels (HIGH/MEDIUM/LOW) and resolution hints."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "drone_id": types.Schema(
                type=types.Type.STRING,
                description="Drone ID to check, e.g. 'D001'.",
            ),
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID to check against, e.g. 'PRJ001'.",
            ),
        },
        required=["drone_id", "project_id"],
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 3: detect_all_conflicts
# ═══════════════════════════════════════════════════════════════

def detect_all_conflicts() -> dict:
    """
    Run a full conflict audit across all active (Assigned/In Progress) missions.
    Returns a consolidated report grouped by mission.
    """
    missions_df = get_missions_df()
    active = missions_df[missions_df["status"].isin(["Assigned", "In Progress"])]

    if active.empty:
        return {
            "total_conflicts": 0,
            "missions_with_conflicts": 0,
            "report": [],
            "message": "No active assignments to audit.",
        }

    report = []
    total_conflicts = 0

    for _, mission in active.iterrows():
        project_id = mission["project_id"]
        mission_report = {
            "project_id": project_id,
            "client": mission["client"],
            "priority": mission["priority"],
            "status": mission["status"],
            "pilot_conflicts": None,
            "drone_conflicts": None,
            "total_conflicts_for_mission": 0,
            "overall_severity": "NONE",
        }

        pilot_id = str(mission.get("assigned_pilot_id", "-")).strip()
        drone_id = str(mission.get("assigned_drone_id", "-")).strip()

        all_severities = []

        if pilot_id and pilot_id != "-":
            pc = check_pilot_conflicts(pilot_id, project_id)
            if "error" not in pc:
                mission_report["pilot_conflicts"] = pc
                total_conflicts += pc["conflict_count"]
                mission_report["total_conflicts_for_mission"] += pc["conflict_count"]
                if pc["has_conflicts"]:
                    all_severities.append(pc["overall_severity"])

        if drone_id and drone_id != "-":
            dc = check_drone_conflicts(drone_id, project_id)
            if "error" not in dc:
                mission_report["drone_conflicts"] = dc
                total_conflicts += dc["conflict_count"]
                mission_report["total_conflicts_for_mission"] += dc["conflict_count"]
                if dc["has_conflicts"]:
                    all_severities.append(dc["overall_severity"])

        # Compute mission-level severity
        mission_report["overall_severity"] = (
            "HIGH" if "HIGH" in all_severities else
            "MEDIUM" if "MEDIUM" in all_severities else
            "LOW" if "LOW" in all_severities else
            "NONE"
        )

        report.append(mission_report)

    missions_with_conflicts = sum(
        1 for r in report if r["total_conflicts_for_mission"] > 0
    )

    # Sort by severity: HIGH first, then MEDIUM, LOW, NONE
    severity_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "NONE": 3}
    report.sort(key=lambda r: severity_order.get(r["overall_severity"], 4))

    return {
        "total_conflicts": total_conflicts,
        "missions_audited": len(report),
        "missions_with_conflicts": missions_with_conflicts,
        "report": report,
        "summary": (
            f"Audited {len(report)} active mission(s). "
            f"Found {total_conflicts} conflict(s) across {missions_with_conflicts} mission(s)."
        ),
    }


DETECT_ALL_CONFLICTS_DECL = types.FunctionDeclaration(
    name="detect_all_conflicts",
    description=(
        "Run a full conflict audit across ALL currently active missions (Assigned or In Progress). "
        "Checks every assigned pilot and drone for all conflict types. "
        "Returns a report sorted by severity (HIGH conflicts first). "
        "Use this for a full operational health check."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={},
    ),
)


# ═══════════════════════════════════════════════════════════════
# TOOL 4: suggest_reassignment
# ═══════════════════════════════════════════════════════════════

def suggest_reassignment(project_id: str) -> dict:
    """
    For a mission with conflicts, identify root causes and return ranked
    alternative pilot and drone candidates.

    Scoring:
      +2 points — candidate in same city as mission (location match)
      +1 point  — pilot cost within budget / drone is IP43-rated
      0 points  — no bonus
    Top 3 candidates are returned for each category.
    """
    project_id = project_id.strip().upper()

    missions_df = get_missions_df()
    pilots_df = get_pilots_df()
    drones_df = get_drones_df()

    mission_row = missions_df[missions_df["project_id"] == project_id]
    if mission_row.empty:
        return {"error": f"Mission '{project_id}' not found."}

    mission = mission_row.iloc[0]

    # ── Step 1: Detect root causes ────────────────────────────
    root_causes = []
    current_pilot_id = str(mission.get("assigned_pilot_id", "-")).strip()
    current_drone_id = str(mission.get("assigned_drone_id", "-")).strip()

    if current_pilot_id and current_pilot_id != "-":
        pc = check_pilot_conflicts(current_pilot_id, project_id)
        if "error" not in pc and pc["has_conflicts"]:
            root_causes.extend(pc["conflicts"])

    if current_drone_id and current_drone_id != "-":
        dc = check_drone_conflicts(current_drone_id, project_id)
        if "error" not in dc and dc["has_conflicts"]:
            root_causes.extend(dc["conflicts"])

    # ── Step 2: Find eligible pilots ──────────────────────────
    m_start = _parse_date(mission["start_date"])
    m_end = _parse_date(mission["end_date"])
    duration_days = (m_end - m_start).days + 1 if (m_start and m_end) else 1
    budget = float(mission.get("mission_budget_inr", 0))

    candidate_pilots = []
    for _, pilot in pilots_df.iterrows():
        p_id = pilot["pilot_id"]
        # Skip the currently assigned pilot
        if p_id == current_pilot_id:
            continue

        conflicts = check_pilot_conflicts(p_id, project_id)
        if "error" in conflicts:
            continue

        high_conflicts = [c for c in conflicts.get("conflicts", []) if c["severity"] == "HIGH"]
        if high_conflicts:
            continue  # Ineligible

        score = 0
        cost = float(pilot.get("daily_rate_inr", 0)) * duration_days
        if str(pilot["location"]).strip().lower() == str(mission["location"]).strip().lower():
            score += 2
        if budget > 0 and cost <= budget:
            score += 1

        candidate_pilots.append({
            "pilot_id": p_id,
            "name": pilot["name"],
            "location": pilot["location"],
            "status": pilot["status"],
            "skills": pilot["skills"],
            "certifications": pilot["certifications"],
            "daily_rate_inr": pilot["daily_rate_inr"],
            "estimated_total_cost_inr": cost,
            "within_budget": budget == 0 or cost <= budget,
            "warnings": [c for c in conflicts.get("conflicts", []) if c["severity"] != "HIGH"],
            "match_score": score,
        })

    candidate_pilots.sort(key=lambda x: -x["match_score"])

    # ── Step 3: Find eligible drones ──────────────────────────
    candidate_drones = []
    for _, drone in drones_df.iterrows():
        d_id = drone["drone_id"]
        if d_id == current_drone_id:
            continue

        conflicts = check_drone_conflicts(d_id, project_id)
        if "error" in conflicts:
            continue

        high_conflicts = [c for c in conflicts.get("conflicts", []) if c["severity"] == "HIGH"]
        if high_conflicts:
            continue  # Ineligible

        score = 0
        is_ip43 = _RAINY_KEYWORD in str(drone.get("weather_resistance", ""))
        if str(drone["location"]).strip().lower() == str(mission["location"]).strip().lower():
            score += 2
        if is_ip43:
            score += 1

        candidate_drones.append({
            "drone_id": d_id,
            "model": drone["model"],
            "location": drone["location"],
            "status": drone["status"],
            "capabilities": drone["capabilities"],
            "weather_resistance": drone["weather_resistance"],
            "is_ip43_rated": is_ip43,
            "warnings": [c for c in conflicts.get("conflicts", []) if c["severity"] != "HIGH"],
            "match_score": score,
        })

    candidate_drones.sort(key=lambda x: -x["match_score"])

    return {
        "project_id": project_id,
        "client": mission["client"],
        "priority": mission["priority"],
        "current_pilot_id": current_pilot_id,
        "current_drone_id": current_drone_id,
        "root_causes": root_causes,
        "root_cause_count": len(root_causes),
        "recommended_pilots": candidate_pilots[:3],
        "recommended_drones": candidate_drones[:3],
        "eligible_pilot_count": len(candidate_pilots),
        "eligible_drone_count": len(candidate_drones),
        "next_step": (
            "Review the recommended candidates above. "
            "To execute a reassignment, call assign_pilot_to_mission and/or assign_drone_to_mission "
            "with the chosen IDs."
        ),
    }


SUGGEST_REASSIGNMENT_DECL = types.FunctionDeclaration(
    name="suggest_reassignment",
    description=(
        "For a mission with conflicts, detect the root cause(s) and return ranked "
        "alternative pilot and drone candidates that have no HIGH severity conflicts. "
        "Candidates are scored by location match (+2) and budget fit/IP43 rating (+1). "
        "Use this for urgent reassignments. "
        "After user confirms, call assign_pilot_to_mission and/or assign_drone_to_mission."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "project_id": types.Schema(
                type=types.Type.STRING,
                description="Mission project ID that needs reassignment, e.g. 'PRJ002'.",
            ),
        },
        required=["project_id"],
    ),
)
