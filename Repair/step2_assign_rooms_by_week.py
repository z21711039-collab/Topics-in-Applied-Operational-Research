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
from typing import Dict, List, Optional, Set, Tuple

EVENTS_XLSX = "events.xlsx"
ROOMS_XLSX  = "room.xlsx"
STEP1_SOL   = "step1_solution_firefight.csv"

# Teaching days in our model: Monday-Friday
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY2IDX = {d:i for i,d in enumerate(DAYS)}

# Time slots for class scheduling every day are from 09:00 to 18:00
SLOT_START_HOURS = list(range(9, 18))   # 9..17
HOUR2SLOT = {h:i for i,h in enumerate(SLOT_START_HOURS)}
NUM_SLOTS = len(SLOT_START_HOURS)

# No-room flag
NO_ROOM_FLAG = "No room required"
REPAIR_EXTRA_CANDIDATES = 5
W_CAPACITY = 30
W_CAMPUS = 10
W_SAME_ROOM = 20


ROOMTYPE_MAP = {}

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


def can_use_room(
    occ: Set[Tuple[int, str, str, int]],
    wk: int,
    day: str,
    start: int,
    end: int,
    room_id: str,
) -> bool:
    for s in range(start, end):
        if (int(wk), room_id, str(day), s) in occ:
            return False
    return True


def occupy_room(
    occ: Set[Tuple[int, str, str, int]],
    wk: int,
    day: str,
    start: int,
    end: int,
    room_id: str,
) -> None:
    for s in range(start, end):
        occ.add((int(wk), room_id, str(day), s))


def release_room(
    occ: Set[Tuple[int, str, str, int]],
    wk: int,
    day: str,
    start: int,
    end: int,
    room_id: str,
) -> None:
    for s in range(start, end):
        occ.discard((int(wk), room_id, str(day), s))


def room_penalties(room_row: pd.Series, size: int, expected_campus: str) -> Tuple[int, int]:
    overflow = max(size - int(room_row["cap"]), 0)
    campus_bad = 0 if (not expected_campus) or str(room_row["campus"]).strip() == expected_campus else 1
    return overflow, campus_bad


def event_local_score(
    assignments: List[Tuple[int, str]],
    room_id_to_idx: Dict[str, int],
    rm: pd.DataFrame,
    size: int,
    expected_campus: str,
) -> int:
    used_rooms = {rid for _, rid in assignments if rid}
    same_room_penalty = max(len(used_rooms) - 1, 0)
    capacity_penalty = 0
    campus_penalty = 0

    for _, rid in assignments:
        r_idx = room_id_to_idx.get(str(rid))
        if r_idx is None:
            continue
        overflow, campus_bad = room_penalties(rm.loc[r_idx], size, expected_campus)
        capacity_penalty += overflow
        campus_penalty += campus_bad

    return (
        W_SAME_ROOM * same_room_penalty
        + W_CAPACITY * capacity_penalty
        + W_CAMPUS * campus_penalty
    )


def main(step1_sol="step1_solution_baseline.csv",
         out_csv="step2_solution_with_rooms_by_week_baseline.csv",
         fail_csv="step2_failed_occurrences_baseline.csv",
         events_xlsx=EVENTS_XLSX):
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
    rm["cap"] = pd.to_numeric(rm["cap"], errors="coerce").fillna(0).astype(int)
    rm = rm[["room_id", "cap", "campus", "room_type"]].reset_index(drop=True)
    # Build mapping: room_type -> list of row indices in rm
    type_to_room_idx: Dict[str, List[int]] = {}
    room_id_to_idx: Dict[str, int] = {}
    for idx, row in rm.iterrows():
        type_to_room_idx.setdefault(row["room_type"], []).append(idx)
        room_id_to_idx[str(row["room_id"])] = idx

    # load step1 solution
    sol0 = pd.read_csv(step1_sol).copy()
    sol0["weeks_set"] = sol0["weeks"].apply(parse_weeks)
    sol0["req_room_type"] = sol0["req_room_type"].apply(norm_room_type)  # NHS->General Teaching

    ev = pd.read_excel(events_xlsx).copy()
    ev.columns = ev.columns.str.strip()
    ev = ev.rename(columns={
        "Event ID": "event_id",
        "Expected Campus": "event_campus",
    })
    ev["event_id"] = ev["event_id"].astype(str)
    ev["event_campus"] = ev["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()
    event_to_campus = ev.set_index("event_id")["event_campus"].to_dict()

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
    sol["event_campus"] = sol["event_id"].astype(str).map(event_to_campus).fillna(NO_ROOM_FLAG)


    assigned_count = 0
    failed: List[Tuple[str, int]] = []

    # Only handle rows that require a room
    need = sol[sol["req_room_type"] != NO_ROOM_FLAG].copy()

    # 全局 occupancy：按最终 room_id 检查，避免任何重复占用
    occ: Set[Tuple[int, str, str, int]] = set()

    event_week_count = need.groupby("event_id")["week"].nunique().to_dict()

    # Phase 1: greedy initial assignment
    for (room_type, wk, day), g in need.groupby(["req_room_type", "week", "assigned_day"], sort=False):
        room_type = str(room_type).strip()
        room_list = type_to_room_idx.get(room_type, [])

        if not room_list:
            for idx, rr in g.iterrows():
                failed.append((rr["event_id"], int(rr["week"])))
            continue

        intervals = []
        for idx, row in g.iterrows():
            start = HOUR2SLOT[int(row["assigned_start_hour"])]
            L = int(row["L_slots"])
            end = start + L
            size = int(row["size"])
            intervals.append((start, end, -L, -size, idx, size))

        intervals.sort()

        for start, end, _, _, idx, size in intervals:
            expected_campus = str(sol.at[idx, "event_campus"]).strip()
            if expected_campus == NO_ROOM_FLAG:
                expected_campus = ""

            feasible_rooms = []
            for r_idx in room_list:
                rid = str(rm.at[r_idx, "room_id"])
                if can_use_room(occ, int(wk), str(day), start, end, rid):
                    feasible_rooms.append(r_idx)

            if not feasible_rooms:
                failed.append((sol.at[idx, "event_id"], int(sol.at[idx, "week"])))
                continue

            eligible_rooms = [r_idx for r_idx in feasible_rooms if int(rm.at[r_idx, "cap"]) >= size]
            chosen_r_idx: Optional[int] = None

            if eligible_rooms:
                min_cap = min(int(rm.at[r_idx, "cap"]) for r_idx in eligible_rooms)
                tight_rooms = [r_idx for r_idx in eligible_rooms if int(rm.at[r_idx, "cap"]) == min_cap]
                campus_tight_rooms = [
                    r_idx for r_idx in tight_rooms
                    if (not expected_campus) or str(rm.at[r_idx, "campus"]).strip() == expected_campus
                ]
                target_rooms = campus_tight_rooms if campus_tight_rooms else tight_rooms
                chosen_r_idx = min(target_rooms, key=lambda r: str(rm.at[r, "room_id"]))
            else:
                max_cap = max(int(rm.at[r_idx, "cap"]) for r_idx in feasible_rooms)
                max_cap_rooms = [r_idx for r_idx in feasible_rooms if int(rm.at[r_idx, "cap"]) == max_cap]
                campus_max_rooms = [
                    r_idx for r_idx in max_cap_rooms
                    if (not expected_campus) or str(rm.at[r_idx, "campus"]).strip() == expected_campus
                ]
                target_rooms = campus_max_rooms if campus_max_rooms else max_cap_rooms
                chosen_r_idx = min(target_rooms, key=lambda r: str(rm.at[r, "room_id"]))

            rid = str(rm.at[chosen_r_idx, "room_id"])
            sol.at[idx, "room_id"] = rid
            sol.at[idx, "room_campus"] = rm.at[chosen_r_idx, "campus"]
            occupy_room(occ, int(wk), str(day), start, end, rid)
            assigned_count += 1

    # Phase 2: deterministic same-room repair across weeks
    repair_events = (
        sol[
            (sol["req_room_type"] != NO_ROOM_FLAG)
            & sol["room_id"].astype(str).str.strip().ne("")
        ]
        .groupby("event_id", sort=False)
    )
    repaired_events = 0

    for event_id, g in sorted(
        repair_events,
        key=lambda item: (
            -int(event_week_count.get(str(item[0]), 1)),
            -int(item[1]["size"].iloc[0]),
            str(item[0]),
        ),
    ):
        g = g.copy()
        used_rooms = g["room_id"].fillna("").astype(str).str.strip()
        distinct_rooms = [rid for rid in used_rooms.unique().tolist() if rid]
        if len(distinct_rooms) <= 1:
            continue

        sample = g.iloc[0]
        room_type = str(sample["req_room_type"]).strip()
        room_list = type_to_room_idx.get(room_type, [])
        if not room_list:
            continue

        day = str(sample["assigned_day"])
        start = HOUR2SLOT[int(sample["assigned_start_hour"])]
        end = start + int(sample["L_slots"])
        size = int(sample["size"])
        expected_campus = str(sample.get("event_campus", NO_ROOM_FLAG)).strip()
        if expected_campus == NO_ROOM_FLAG:
            expected_campus = ""

        current_assignments = []
        for idx, row in g.iterrows():
            rid = str(row["room_id"]).strip()
            current_assignments.append((idx, int(row["week"]), rid, str(row["room_campus"])))
            release_room(occ, int(row["week"]), day, start, end, rid)
        current_score = event_local_score(
            [(wk, rid) for _, wk, rid, _ in current_assignments],
            room_id_to_idx,
            rm,
            size,
            expected_campus,
        )

        room_usage = g["room_id"].value_counts()
        candidate_room_ids: List[str] = []
        for rid in room_usage.index.tolist():
            rid = str(rid).strip()
            if rid and rid not in candidate_room_ids:
                candidate_room_ids.append(rid)

        extra_candidates = sorted(
            room_list,
            key=lambda r_idx: (
                abs(int(rm.at[r_idx, "cap"]) - size),
                0 if (not expected_campus) or str(rm.at[r_idx, "campus"]).strip() == expected_campus else 1,
                str(rm.at[r_idx, "room_id"]),
            ),
        )
        for r_idx in extra_candidates:
            rid = str(rm.at[r_idx, "room_id"]).strip()
            if rid not in candidate_room_ids:
                candidate_room_ids.append(rid)
            if len(candidate_room_ids) >= len(distinct_rooms) + REPAIR_EXTRA_CANDIDATES:
                break

        chosen_room_id = ""
        chosen_room_campus = ""
        chosen_score = current_score
        for rid in candidate_room_ids:
            if all(can_use_room(occ, wk, day, start, end, rid) for _, wk, _, _ in current_assignments):
                cand_score = event_local_score(
                    [(wk, rid) for _, wk, _, _ in current_assignments],
                    room_id_to_idx,
                    rm,
                    size,
                    expected_campus,
                )
                if cand_score < chosen_score:
                    chosen_room_id = rid
                    match = rm.loc[room_id_to_idx[rid]]
                    chosen_room_campus = str(match["campus"])
                    chosen_score = cand_score

        if chosen_room_id and chosen_score < current_score:
            for idx, wk, _, _ in current_assignments:
                sol.at[idx, "room_id"] = chosen_room_id
                sol.at[idx, "room_campus"] = chosen_room_campus
                occupy_room(occ, wk, day, start, end, chosen_room_id)
            repaired_events += 1
        else:
            for idx, wk, rid, _ in current_assignments:
                occupy_room(occ, wk, day, start, end, rid)

    # Phase 3: capacity-focused upgrade without breaking across-week consistency
    capacity_repaired_events = 0
    repair_groups = (
        sol[
            (sol["req_room_type"] != NO_ROOM_FLAG)
            & sol["room_id"].astype(str).str.strip().ne("")
        ]
        .groupby("event_id", sort=False)
    )

    for event_id, g in sorted(
        repair_groups,
        key=lambda item: (
            -int(item[1]["size"].iloc[0]),
            -int(event_week_count.get(str(item[0]), 1)),
            str(item[0]),
        ),
    ):
        g = g.copy()
        sample = g.iloc[0]
        room_type = str(sample["req_room_type"]).strip()
        room_list = type_to_room_idx.get(room_type, [])
        if not room_list:
            continue

        day = str(sample["assigned_day"])
        start = HOUR2SLOT[int(sample["assigned_start_hour"])]
        end = start + int(sample["L_slots"])
        size = int(sample["size"])
        expected_campus = str(sample.get("event_campus", NO_ROOM_FLAG)).strip()
        if expected_campus == NO_ROOM_FLAG:
            expected_campus = ""

        current_assignments = []
        for idx, row in g.iterrows():
            rid = str(row["room_id"]).strip()
            if not rid:
                current_assignments = []
                break
            current_assignments.append((idx, int(row["week"]), rid, str(row["room_campus"])))
        current_score = event_local_score(
            [(wk, rid) for _, wk, rid, _ in current_assignments],
            room_id_to_idx,
            rm,
            size,
            expected_campus,
        )

        if not current_assignments:
            continue

        for _, wk, rid, _ in current_assignments:
            release_room(occ, wk, day, start, end, rid)

        candidate_rooms = sorted(
            room_list,
            key=lambda r_idx: (
                max(size - int(rm.at[r_idx, "cap"]), 0),
                0 if (not expected_campus) or str(rm.at[r_idx, "campus"]).strip() == expected_campus else 1,
                abs(int(rm.at[r_idx, "cap"]) - size),
                str(rm.at[r_idx, "room_id"]),
            ),
        )

        chosen_room_id = ""
        chosen_room_campus = ""
        chosen_score = current_score
        for r_idx in candidate_rooms:
            rid = str(rm.at[r_idx, "room_id"]).strip()
            if all(can_use_room(occ, wk, day, start, end, rid) for _, wk, _, _ in current_assignments):
                cand_score = event_local_score(
                    [(wk, rid) for _, wk, _, _ in current_assignments],
                    room_id_to_idx,
                    rm,
                    size,
                    expected_campus,
                )
                if cand_score < chosen_score:
                    chosen_room_id = rid
                    chosen_room_campus = str(rm.at[r_idx, "campus"])
                    chosen_score = cand_score

        if chosen_room_id and chosen_score < current_score:
            for idx, wk, _, _ in current_assignments:
                sol.at[idx, "room_id"] = chosen_room_id
                sol.at[idx, "room_campus"] = chosen_room_campus
                occupy_room(occ, wk, day, start, end, chosen_room_id)
            capacity_repaired_events += 1
        else:
            for idx, wk, rid, _ in current_assignments:
                occupy_room(occ, wk, day, start, end, rid)

    assigned_event_rooms = (
        sol[sol["room_id"].astype(str).str.strip() != ""]
        .groupby("event_id")["room_id"]
        .agg(lambda s: sorted(set(s.astype(str).str.strip())))
    )
    fixed_room_events = int((assigned_event_rooms.apply(len) == 1).sum())
    partial_reuse_events = int((assigned_event_rooms.apply(len) > 1).sum())

    # Outputs
    sol.drop(columns=["event_campus"], inplace=True, errors="ignore")
    out_path = OUTDIR / out_csv
    sol.to_csv(out_path, index=False)

    print("Assigned rooms for", assigned_count, "occurrences requiring rooms.")
    print("Failed assignments:", len(failed))
    print("Events repaired to one room across weeks:", repaired_events)
    print("Events upgraded for lower capacity overflow:", capacity_repaired_events)
    print("Events kept in one room across all scheduled weeks:", fixed_room_events)
    print("Events with repeated room reuse despite partial splits:", partial_reuse_events)
    if failed:
        fail_path = OUTDIR / fail_csv
        pd.DataFrame(failed, columns=["event_id","week"]).to_csv(fail_path, index=False)
        print("Wrote failed list to:", fail_path)
    print("Wrote final schedule to:", out_path)
    

if __name__ == "__main__":
    main()
