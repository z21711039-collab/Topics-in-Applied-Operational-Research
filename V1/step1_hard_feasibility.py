#  Step 1: Hard-constraint feasibility scheduling (At this step, we only generate time templates and do not make specific room allocations)
#  Hard constraints:
#  (H1) Exactly One Start Time per Event
#  (H2) Duration and Consecutiveness
#  (H3) Fixed Weeks
#  (H4) Room-Type Capacity (room-required events only)
#  (H5) Pattern Constraint: Same Time Template Across Weeks


from __future__ import annotations

import pandas as pd
from typing import Dict, List, Set, Tuple
from pathlib import Path
from ortools.sat.python import cp_model

# Import the cleaned data
EVENTS_XLSX = r"d:\MSC\TOPICS\events.xlsx"
ROOMS_XLSX  = r"d:\MSC\TOPICS\room.xlsx"

# Teaching days in our model: Monday-Friday
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

# Time slots for class scheduling every day are from 09:00 to 18:00
SLOT_START_HOURS = list(range(9, 18))  # 9..17
NUM_SLOTS = len(SLOT_START_HOURS)      # 9

NO_ROOM_FLAG = "No room required"


# We treat NHS Room as General Teaching
ROOMTYPE_MAP = {
    "NHS Room": "General Teaching",
}

def norm_room_type(x) -> str:
    """
    [EN] Normalize room type:
       map empty/NaN/None/null to NO_ROOM_FLAG
       otherwise, we map via ROOMTYPE_MAP
    """
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s.lower() in ["nan", "none", "null", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)

# Output directory
OUTDIR = Path(__file__).resolve().parent

# [H3] Fixed Weeks
def parse_weeks(x) -> Set[int]:
    """
    Parse input Weeks into recurrence set W_e 
    """
    if pd.isna(x):
        return set()
    out: Set[int] = set()
    for tok in str(x).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out

# (H2) Duration and Consecutiveness
def dur_to_slots(minutes: int) -> int:
    """
    Convert minutes to L_e (number of consecutive 1-hour slots), via ceil(minutes/60).
    """
    return int((int(minutes) + 59) // 60)


def main(time_limit_sec: int = 900, N_EVENTS: int | None = 2000, stop_after_first_solution: bool = True):
    ev = pd.read_excel(EVENTS_XLSX).copy()
    rm = pd.read_excel(ROOMS_XLSX).copy()

    # Clean rooms
    rm = rm.rename(columns={
        "Id": "room_id",
        "Capacity": "cap",
        "Campus": "campus",
        "Specialist room type": "room_type",
    })
    rm["room_id"] = rm["room_id"].astype(str)
    rm["room_type"] = rm["room_type"].astype(str).str.strip()
    rm["room_type"] = rm["room_type"].apply(norm_room_type)   # We treat NHS rooms as General Teaching rooms
    rm = rm[["room_id", "cap", "campus", "room_type"]].reset_index(drop=True)

# (H4) Room-Type Capacity
# type_capacity = number of rooms of that type
    type_to_rooms = rm.groupby("room_type").indices #First, group the room_type into a "list of row indices for each type,
    type_capacity = {t: len(idx_list) for t, idx_list in type_to_rooms.items()} # then calculate the length of each group to get the room count.

# Clean events
    ev = ev.rename(columns={
        "Event ID": "event_id",
        "Duration (minutes)": "dur_min",
        "Event Size": "size",
        "Room type 2": "req_room_type",
        "Weeks": "weeks_raw",
    })
    ev["weeks_set"] = ev["weeks_raw"].apply(parse_weeks)

    if N_EVENTS is not None:
        ev = ev.head(int(N_EVENTS)).copy()

    ev["event_id"] = ev["event_id"].astype(str)
    
    # treat empty req_room_type as NO_ROOM_FLAG
    ev["req_room_type"] = ev["req_room_type"].astype(str).str.strip()
    ev.loc[ev["req_room_type"].isin(["nan", "NaN", "None", ""]), "req_room_type"] = NO_ROOM_FLAG
    ev["req_room_type"] = ev["req_room_type"].apply(norm_room_type)  # NHS->General Teaching

    ev["size"] = ev["size"].fillna(0).astype(int)
    
    # Compute L_e in slots
    ev["L"] = ev["dur_min"].astype(int).apply(dur_to_slots)

    all_weeks: List[int] = sorted({k for s in ev["weeks_set"] for k in s})

    # Split events: room-required / no-room
    E_room = ev.index[ev["req_room_type"] != NO_ROOM_FLAG].tolist()
    E_noroom = ev.index[ev["req_room_type"] == NO_ROOM_FLAG].tolist()

    print(f"Events total: {len(ev)} | need room: {len(E_room)} | no room: {len(E_noroom)}")

    # Stage A (CP-SAT): schedule only room-required events

    print("Stage A: schedule only room-required events")

    modelA = cp_model.CpModel()

    startA = {}
    possible_starts = {}

    # (H1) + (H2)
    # For each room-required event: We only allow feasible starts (t+L<=NUM_SLOTS) and enforce exactly-one
    for i in E_room:
        L = int(ev.at[i, "L"])
        opts = []
        for d in range(len(DAYS)):
            for t in range(NUM_SLOTS):
                # (H2) feasibility of start time for duration L
                if t + L <= NUM_SLOTS:
                    startA[(i,d,t)] = modelA.NewBoolVar(f"sA_e{i}_d{d}_t{t}")
                    opts.append((d,t))
        possible_starts[i] = opts
        if not opts:
            raise RuntimeError(f"[StageA] event_id={ev.at[i,'event_id']} L={L} > NUM_SLOTS={NUM_SLOTS} Or no available starting point")
        modelA.Add(sum(startA[(i,d,t)] for (d,t) in opts) == 1)

    # (H4) Room-Type Capacity (room-required events only) 
    type_to_events = {}
    for i in E_room:
        type_to_events.setdefault(ev.at[i, "req_room_type"], []).append(i)

    for wk in all_weeks:
        for d in range(len(DAYS)):
            for s in range(NUM_SLOTS):
                for room_type_i, ev_list in type_to_events.items():
                    cap = type_capacity.get(room_type_i, 0)
                    if cap <= 0:
                        continue

                    terms = []
                    for i in ev_list:
                        # (H3) only enforce in weeks where event occurs
                        if wk not in ev.at[i, "weeks_set"]:
                            continue
                        L = int(ev.at[i, "L"])
                        # event covers slot s iff start t in [s-L+1, s]
                        t_lo = max(0, s - L + 1)
                        t_hi = min(s + 1, NUM_SLOTS - L + 1)
                        for t in range(t_lo, t_hi):
                            terms.append(startA[(i,d,t)])
                    if terms:
                        modelA.Add(sum(terms) <= cap)
                        
    # Solve Stage A
    solverA = cp_model.CpSolver()
    solverA.parameters.max_time_in_seconds = float(time_limit_sec)
    solverA.parameters.stop_after_first_solution = True
    solverA.parameters.num_search_workers = 1
    solverA.parameters.log_search_progress = False
    solverA.parameters.cp_model_probing_level = 0
    solverA.parameters.symmetry_level = 0
    
    
    statusA = solverA.Solve(modelA)
    print("Stage A status =", solverA.StatusName(statusA))

    if statusA not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        raise RuntimeError("A feasible time plan cannot be found in Stage A")

    # Save the solution
    fixed_dt = {}
    for i in E_room:
        for (d,t) in possible_starts[i]:
            if solverA.Value(startA[(i,d,t)]) == 1:
                fixed_dt[i] = (d,t)
                break

    # Stage B: Concrete room assignment by week

    print("Stage B: Concrete room assignment by week")

    modelB = cp_model.CpModel()
    startB = {}

    # (H2) feasible starts only
    for i in ev.index:
        L = int(ev.at[i, "L"])
        opts = []
        for d in range(len(DAYS)):
            for t in range(NUM_SLOTS):
                if t + L <= NUM_SLOTS:
                    startB[(i,d,t)] = modelB.NewBoolVar(f"sB_e{i}_d{d}_t{t}")
                    opts.append((d,t))
                    
        if not opts:
            raise RuntimeError(f"[StageB] event_id={ev.at[i,'event_id']} L={L} > NUM_SLOTS={NUM_SLOTS} 或无可用起始点")

        # (H1) exactly one template
        modelB.Add(sum(startB[(i,d,t)] for (d,t) in opts) == 1)

        # (H5) Pattern Constraint: Same Time Template Across Weeks
        # Fix the template for room-required events to Stage A result
        if i in fixed_dt:
            d_star, t_star = fixed_dt[i]
            for (d,t) in opts:
                if (d,t) == (d_star,t_star):
                    modelB.Add(startB[(i,d,t)] == 1)
                else:
                    modelB.Add(startB[(i,d,t)] == 0)

    # Solve stage B
    solverB = cp_model.CpSolver()
    solverB.parameters.max_time_in_seconds = float(time_limit_sec)
    solverB.parameters.stop_after_first_solution = True
    solverB.parameters.num_search_workers = 1
    solverB.parameters.log_search_progress = False
    solverB.parameters.cp_model_probing_level = 0
    solverB.parameters.symmetry_level = 0

    statusB = solverB.Solve(modelB)
    print("Stage B status =", solverB.StatusName(statusB))

    if statusB not in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        raise RuntimeError("Stage B cannot schedule time for the no-room")

    # Output complete timetable (including no-room)
    out = []
    for i in ev.index:
        chosen_day = None
        chosen_hour = None
        for d in range(len(DAYS)):
            for t in range(NUM_SLOTS):
                if (i,d,t) in startB and solverB.Value(startB[(i,d,t)]) == 1:
                    chosen_day = DAYS[d]
                    chosen_hour = SLOT_START_HOURS[t]
                    break

        out.append({
            "event_id": ev.at[i,"event_id"],
            "weeks": ev.at[i,"weeks_raw"], # original weeks string
            "req_room_type": ev.at[i,"req_room_type"],
            "size": int(ev.at[i,"size"]),
            "L_slots": int(ev.at[i,"L"]), # duration in slots
            "assigned_day": chosen_day,
            "assigned_start_hour": chosen_hour,
            "room_id": "", # Step 1: empty
            "room_campus": "", # Step 1: empty
        })

    sol = pd.DataFrame(out)
    sol_path = OUTDIR / "step1_solution.csv"
    sol.to_csv(sol_path, index=False)
    print("Complete timetable:", sol_path)


if __name__ == "__main__":
    # We first tried 2,000 of them and then all of them. This line of code is reserved for our subsequent use. You can generously ignore it.
    main(time_limit_sec=1800, N_EVENTS=None, stop_after_first_solution=True)