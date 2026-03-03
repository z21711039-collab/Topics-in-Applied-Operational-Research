# At this step, we assigns a *concrete room* to each (event, week) occurrence, given the fixed time template (day + start hour) from Step 1.
#  Hard constraints:
#  (H6) Room Assignment per Weekly Occurrence
#  (H7) Strict Room-Type Compatibility
#  (H8) Room–Time Conflicts

# Algorithm:
#   Greedy interval coloring per (room_type, week, day):
#   Convert each occurrence to an interval [start_slot, end_slot)
#   Sort by start_slot
#   Maintain a heap of busy rooms ordered by end_slot; release rooms when they finish
#   Assign a free room if any; otherwise mark as failed


from __future__ import annotations
import pandas as pd
from pathlib import Path
from typing import Dict, List, Set, Tuple

EVENTS_XLSX = r"d:\MSC\TOPICS\events.xlsx"
ROOMS_XLSX  = r"d:\MSC\TOPICS\room.xlsx"
STEP1_SOL   = r"d:\MSC\TOPICS\step1_solution.csv"

# Teaching days in our model: Monday-Friday
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY2IDX = {d:i for i,d in enumerate(DAYS)}

# Time slots for class scheduling every day are from 09:00 to 18:00
SLOT_START_HOURS = list(range(9, 18))   # 9..17
HOUR2SLOT = {h:i for i,h in enumerate(SLOT_START_HOURS)}
NUM_SLOTS = len(SLOT_START_HOURS)

# No-room flag
NO_ROOM_FLAG = "No room required"

# We treat "NHS Room" as "General Teaching"
ROOMTYPE_MAP = {
    "NHS Room": "General Teaching",
}

def norm_room_type(x) -> str:
    """
    Normalize room type:
        set empty/NaN/None as No room required
        set NHS Room as General Teaching
        set otherwise keep original string
    """
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s.lower() in ["nan", "none", "null", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)

# Output directory
OUTDIR = Path(__file__).resolve().parent

def parse_weeks(x) -> Set[int]:
    """
    Parse the 'weeks' string to a set of integers.
    """
    if pd.isna(x):
        return set()
    out: Set[int] = set()
    for tok in str(x).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out

def main():
    # load room table
    rm = pd.read_excel(ROOMS_XLSX).copy()
    rm = rm.rename(columns={
        "Id": "room_id",
        "Capacity": "cap",
        "Campus": "campus",
        "Specialist room type": "room_type",
    })
    rm["room_id"] = rm["room_id"].astype(str)
    rm["room_type"] = rm["room_type"].astype(str).str.strip()
    rm["room_type"] = rm["room_type"].apply(norm_room_type)   # NHS->General Teaching
    rm = rm[["room_id", "cap", "campus", "room_type"]].reset_index(drop=True)

    # Build mapping: room_type -> list of row indices in rm
    type_to_room_idx: Dict[str, List[int]] = {}
    for idx, row in rm.iterrows():
        type_to_room_idx.setdefault(row["room_type"], []).append(idx)

    # load step1 solution
    sol0 = pd.read_csv(STEP1_SOL).copy()
    sol0["weeks_set"] = sol0["weeks"].apply(parse_weeks)
    sol0["req_room_type"] = sol0["req_room_type"].apply(norm_room_type)  # NHS->General Teaching

    # Step1 must provide day/start
    if sol0["assigned_day"].isna().any() or sol0["assigned_start_hour"].isna().any():
        raise RuntimeError("Step1 solution has missing day/start_hour.")

    # Expand into (event, week) occurrences
    # No-room events "still happen" each week, so they must be expanded too (they just keep room_id empty).
    rows = []
    for _, r in sol0.iterrows():
        for wk in r["weeks_set"]:
            rr = r.to_dict()
            rr["week"] = int(wk)
            rows.append(rr)

    sol = pd.DataFrame(rows).copy()
    sol.drop(columns=["weeks_set"], inplace=True, errors="ignore")


    # normalize room_id fields to avoid fake 'nan'
    for col in ["room_id", "room_campus"]:
        if col in sol.columns:
            sol[col] = sol[col].fillna("").astype(str)
            sol.loc[sol[col].str.lower().isin(["nan", "none"]), col] = ""
    
    
    # output
    sol["room_id"] = ""
    sol["room_campus"] = ""

    # occupancy: (week, room_idx, day_idx, slot)
    occ: Set[Tuple[int,int,int,int]] = set()

    # heuristic: longer first within each type
    def difficulty_key(r):
        return (-int(r["L_slots"]), )

    sol_sorted = sol.sort_values(by=["req_room_type"], kind="stable").copy()

    # Greedy assignment for room-required occurrences
    import heapq

    assigned_count = 0
    failed: List[Tuple[str, int]] = []

    # Only handle the rows that require a room (no-room does not need to assign room_id).
    need = sol[sol["req_room_type"] != NO_ROOM_FLAG].copy()

    # Interval coloring per (room_type, week, day) ensures no overlaps in the same room
    for (room_type, wk, day), g in need.groupby(["req_room_type", "week", "assigned_day"], sort=False):
        room_type = str(room_type).strip()
        room_list = type_to_room_idx.get(room_type, [])

        if not room_list:
            # If no rooms of this type, all occurrences in this group will fail
            for _, rr in g.iterrows():
                failed.append((rr["event_id"], int(rr["week"])))
            continue

        # Build intervals [start, end) in slot index
        # Convert occurrences to slot intervals [start, end)
        intervals = []
        for idx, row in g.iterrows():
            start = HOUR2SLOT[int(row["assigned_start_hour"])]
            L = int(row["L_slots"])
            end = start + L
            intervals.append((start, end, idx))
            
        # Sort by start time
        intervals.sort(key=lambda x: (x[0], x[1]))


        free_rooms = list(room_list)  # list of available room indices
        busy = []  # heap of (end, room_idx)

        for start, end, idx in intervals:
            # list of available room indices
            while busy and busy[0][0] <= start:
                _, r_idx = heapq.heappop(busy)
                free_rooms.append(r_idx)

            if not free_rooms:
                # If no free room, we mark as failed
                failed.append((sol.at[idx, "event_id"], int(sol.at[idx, "week"])))
                continue

            r_idx = free_rooms.pop()
            sol.at[idx, "room_id"] = rm.at[r_idx, "room_id"]
            sol.at[idx, "room_campus"] = rm.at[r_idx, "campus"]
            heapq.heappush(busy, (end, r_idx))
            assigned_count += 1

    # Outputs
    out_path = OUTDIR / "step2_solution_with_rooms_by_week.csv"
    sol.to_csv(out_path, index=False)

    print("Assigned rooms for", assigned_count, "occurrences requiring rooms.")
    print("Failed assignments:", len(failed))
    if failed:
        fail_path = OUTDIR / "step2_failed_occurrences.csv"
        pd.DataFrame(failed, columns=["event_id","week"]).to_csv(fail_path, index=False)
        print("Wrote failed list to:", fail_path)
    print("Wrote final schedule to:", out_path)
    

if __name__ == "__main__":
    main()