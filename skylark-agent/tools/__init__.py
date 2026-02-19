"""
tools/__init__.py — Tool registry for the SkyLark Drone Operations agent.

Maps every tool name to a (callable, FunctionDeclaration) tuple.
The agent/core.py module imports this registry to:
  1. Build the Gemini Tool object (all FunctionDeclarations)
  2. Dispatch incoming function calls to the correct Python function
"""

from tools.roster import (
    query_pilots, QUERY_PILOTS_DECL,
    get_pilot_details, GET_PILOT_DETAILS_DECL,
    update_pilot_status, UPDATE_PILOT_STATUS_DECL,
    calculate_pilot_cost, CALCULATE_PILOT_COST_DECL,
)
from tools.drones import (
    query_drones, QUERY_DRONES_DECL,
    get_drone_details, GET_DRONE_DETAILS_DECL,
    filter_drones_by_weather, FILTER_DRONES_BY_WEATHER_DECL,
    update_drone_status, UPDATE_DRONE_STATUS_DECL,
)
from tools.missions import (
    query_missions, QUERY_MISSIONS_DECL,
    get_mission_details, GET_MISSION_DETAILS_DECL,
    assign_pilot_to_mission, ASSIGN_PILOT_DECL,
    assign_drone_to_mission, ASSIGN_DRONE_DECL,
    get_active_assignments, GET_ACTIVE_ASSIGNMENTS_DECL,
)
from tools.conflicts import (
    check_pilot_conflicts, CHECK_PILOT_CONFLICTS_DECL,
    check_drone_conflicts, CHECK_DRONE_CONFLICTS_DECL,
    detect_all_conflicts, DETECT_ALL_CONFLICTS_DECL,
    suggest_reassignment, SUGGEST_REASSIGNMENT_DECL,
)

# Registry: tool_name -> (callable, FunctionDeclaration)
registry: dict = {
    # ── Roster ──────────────────────────────────────────────
    "query_pilots":         (query_pilots,         QUERY_PILOTS_DECL),
    "get_pilot_details":    (get_pilot_details,    GET_PILOT_DETAILS_DECL),
    "update_pilot_status":  (update_pilot_status,  UPDATE_PILOT_STATUS_DECL),
    "calculate_pilot_cost": (calculate_pilot_cost, CALCULATE_PILOT_COST_DECL),

    # ── Drones ──────────────────────────────────────────────
    "query_drones":             (query_drones,             QUERY_DRONES_DECL),
    "get_drone_details":        (get_drone_details,        GET_DRONE_DETAILS_DECL),
    "filter_drones_by_weather": (filter_drones_by_weather, FILTER_DRONES_BY_WEATHER_DECL),
    "update_drone_status":      (update_drone_status,      UPDATE_DRONE_STATUS_DECL),

    # ── Missions ────────────────────────────────────────────
    "query_missions":          (query_missions,          QUERY_MISSIONS_DECL),
    "get_mission_details":     (get_mission_details,     GET_MISSION_DETAILS_DECL),
    "assign_pilot_to_mission": (assign_pilot_to_mission, ASSIGN_PILOT_DECL),
    "assign_drone_to_mission": (assign_drone_to_mission, ASSIGN_DRONE_DECL),
    "get_active_assignments":  (get_active_assignments,  GET_ACTIVE_ASSIGNMENTS_DECL),

    # ── Conflict Detection ───────────────────────────────────
    "check_pilot_conflicts": (check_pilot_conflicts, CHECK_PILOT_CONFLICTS_DECL),
    "check_drone_conflicts": (check_drone_conflicts, CHECK_DRONE_CONFLICTS_DECL),
    "detect_all_conflicts":  (detect_all_conflicts,  DETECT_ALL_CONFLICTS_DECL),
    "suggest_reassignment":  (suggest_reassignment,  SUGGEST_REASSIGNMENT_DECL),
}

# Flat list of all FunctionDeclarations (used to build the Gemini Tool object)
all_declarations = [decl for _, decl in registry.values()]
