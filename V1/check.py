# check.py
# Verify Step1/Step2 output satisfies ALL hard requirements:
# - Week is valid integer for room-required rows
# - No-room events have NO room assigned
# - Room-required events DO have a valid room_id, and room_type matches
# - Day/start_hour/L_slots valid; long events do not overflow the day
# - Pattern: same (day,start_hour) across weeks for each event_id
# - Hard conflicts: no (week, room_id, day, slot) overlap

from __future__ import annotations

import pandas as pd
from pathlib import Path
from typing import Set, Tuple, Dict, List

# ====== FILE PATHS (edit if needed) ======
ROOMS_XLSX = r"d:\MSC\TOPICS\room.xlsx"
SOLUTION_CSV = r"d:\MSC\TOPICS\step2_solution_with_rooms_by_week.csv"  # <- your step2 by-week output
# If your file name is different, just change SOLUTION_CSV
# ========================================

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY2IDX = {d: i for i, d in enumerate(DAYS)}

SLOT_START_HOURS = list(range(9, 18))  # 9..17
HOUR2SLOT = {h: i for i, h in enumerate(SLOT_START_HOURS)}
NUM_SLOTS = len(SLOT_START_HOURS)  # 9

NO_ROOM_FLAG = "No room required"

ROOMTYPE_MAP = {
    "NHS Room": "General Teaching",
}

def is_empty_room(x) -> bool:
    """Treat '', NaN, 'nan', 'none' as empty."""
    if pd.isna(x):
        return True
    s = str(x).strip().lower()
    return (s == "") or (s == "nan") or (s == "none") or (s == "null")

def norm_room_type(x) -> str:
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s in ["nan", "NaN", "None", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)

def main():
    sol_path = Path(SOLUTION_CSV)
    if not sol_path.exists():
        raise FileNotFoundError(f"Cannot find SOLUTION_CSV: {sol_path}")

    # ---- load solution ----
    sol = pd.read_csv(sol_path).copy()

    # required columns (minimum)
    required_cols = ["event_id", "req_room_type", "assigned_day", "assigned_start_hour", "L_slots"]
    for c in required_cols:
        if c not in sol.columns:
            raise RuntimeError(f"Solution CSV missing required column: {c}")

    # step2 by-week output MUST have week column for conflict checks
    if "week" not in sol.columns:
        raise RuntimeError("Solution CSV missing 'week' column. Step2 by-week output should have integer week.")

    # normalize req_room_type
    sol["req_room_type_norm"] = sol["req_room_type"].apply(norm_room_type)

    # ensure room_id column exists (even if blank)
    if "room_id" not in sol.columns:
        sol["room_id"] = ""
    if "room_campus" not in sol.columns:
        sol["room_campus"] = ""

    # ---- load rooms ----
    rm = pd.read_excel(ROOMS_XLSX).copy()
    rm = rm.rename(columns={
        "Id": "room_id",
        "Capacity": "cap",
        "Campus": "campus",
        "Specialist room type": "room_type",
    })
    rm["room_id"] = rm["room_id"].astype(str)
    rm["room_type"] = rm["room_type"].astype(str).str.strip()
    rm["room_type_norm"] = rm["room_type"].apply(norm_room_type)

    roomid_to_type: Dict[str, str] = dict(zip(rm["room_id"], rm["room_type_norm"]))
    roomid_set: Set[str] = set(rm["room_id"].tolist())

    # ------------------------------------------------------------------
    # CHECKS
    # ------------------------------------------------------------------
    # Sanity(week): room-required rows must have valid integer week
    need_room_mask = (sol["req_room_type_norm"] != NO_ROOM_FLAG)
    # week should be int-like
    week_bad = sol[need_room_mask & (~pd.to_numeric(sol["week"], errors="coerce").notna())]
    print(f"Sanity(week): room-required rows with invalid week = {len(week_bad)}")
    if len(week_bad):
        print(week_bad[["event_id", "week", "req_room_type", "room_id"]].head(20).to_string(index=False))

    # convert week to int where possible
    sol["week_num"] = pd.to_numeric(sol["week"], errors="coerce")
    # keep week_num as Int64 (nullable)
    sol["week_num"] = sol["week_num"].astype("Int64")

    # Sanity(1): room_id empty but req_room_type != No room required
    s1_bad = sol[
        (sol["req_room_type_norm"] != NO_ROOM_FLAG) &
        (sol["room_id"].apply(is_empty_room))
    ]
    print(f"Sanity(1): room_id empty but req_room_type != {NO_ROOM_FLAG}: {len(s1_bad)}")
    if len(s1_bad):
        print(s1_bad[["event_id", "week", "req_room_type", "room_id"]].head(20).to_string(index=False))

    # Sanity(1b): room_id filled but req_room_type == No room required
    s1b_bad = sol[
        (sol["req_room_type_norm"] == NO_ROOM_FLAG) &
        (~sol["room_id"].apply(is_empty_room))
    ]
    print(f"Sanity(1b): room_id filled but req_room_type == {NO_ROOM_FLAG}: {len(s1b_bad)}")
    if len(s1b_bad):
        print(s1b_bad[["event_id", "week", "req_room_type", "room_id"]].head(20).to_string(index=False))

    # Sanity(2a): room_id not found in room.xlsx (only for room-required rows)
    s2a_bad = sol[
        (sol["req_room_type_norm"] != NO_ROOM_FLAG) &
        (~sol["room_id"].apply(is_empty_room)) &
        (~sol["room_id"].astype(str).isin(roomid_set))
    ]
    print(f"Sanity(2a): room_id not found in room.xlsx: {len(s2a_bad)}")
    if len(s2a_bad):
        print(s2a_bad[["event_id", "week", "req_room_type", "room_id"]].head(20).to_string(index=False))

    # Sanity(2b): assigned room_type != req_room_type (only for room-required rows with valid room_id)
    def assigned_type(room_id):
        rid = str(room_id)
        return roomid_to_type.get(rid, None)

    s2b_bad_rows = []
    for _, row in sol[sol["req_room_type_norm"] != NO_ROOM_FLAG].iterrows():
        if is_empty_room(row["room_id"]):
            continue
        rid = str(row["room_id"])
        at = roomid_to_type.get(rid, None)
        if at is None:
            continue
        if at != row["req_room_type_norm"]:
            s2b_bad_rows.append((row["event_id"], row["week"], row["req_room_type_norm"], rid, at))

    print(f"Sanity(2b): assigned room_type != req_room_type: {len(s2b_bad_rows)}")
    if s2b_bad_rows:
        df = pd.DataFrame(s2b_bad_rows, columns=["event_id", "week", "req_room_type", "room_id", "assigned_room_type"])
        print(df.head(20).to_string(index=False))

    # Sanity(3a): start_hour + L_slots validity
    def valid_start_hour(x) -> bool:
        try:
            h = int(x)
        except Exception:
            return False
        return h in HOUR2SLOT

    def valid_L(x) -> bool:
        try:
            L = int(x)
        except Exception:
            return False
        return L >= 1 and L <= NUM_SLOTS

    s3a_bad = sol[~sol["assigned_start_hour"].apply(valid_start_hour) | ~sol["L_slots"].apply(valid_L)]
    print(f"Sanity(3a): rows with invalid start_hour or L_slots: {len(s3a_bad)}")
    if len(s3a_bad):
        print(s3a_bad[["event_id", "week", "assigned_start_hour", "L_slots"]].head(20).to_string(index=False))

    # Sanity(3b): long events overflow day
    overflow_rows = []
    for _, row in sol.iterrows():
        if not valid_start_hour(row["assigned_start_hour"]) or not valid_L(row["L_slots"]):
            continue
        st = HOUR2SLOT[int(row["assigned_start_hour"])]
        L = int(row["L_slots"])
        if st + L > NUM_SLOTS:
            overflow_rows.append((row["event_id"], row["week"], row["assigned_day"], row["assigned_start_hour"], L))
    print(f"Sanity(3b): long events overflow day (start+L > {NUM_SLOTS}): {len(overflow_rows)}")
    if overflow_rows:
        df = pd.DataFrame(overflow_rows, columns=["event_id","week","day","start_hour","L_slots"])
        print(df.head(20).to_string(index=False))

    # Sanity(4a): day validity
    s4a_bad = sol[~sol["assigned_day"].astype(str).isin(DAYS)]
    print(f"Sanity(4a): rows with invalid day (not in {DAYS}): {len(s4a_bad)}")
    if len(s4a_bad):
        print(s4a_bad[["event_id", "week", "assigned_day"]].head(20).to_string(index=False))

    # Pattern(3.2.5): same day/start across weeks for each event_id
    pattern_bad = []
    for eid, g in sol.groupby("event_id", sort=False):
        # ignore rows missing day/start
        gg = g.dropna(subset=["assigned_day", "assigned_start_hour"])
        if gg.empty:
            continue
        pairs = set(zip(gg["assigned_day"].astype(str), gg["assigned_start_hour"].astype(int)))
        if len(pairs) > 1:
            pattern_bad.append((eid, len(pairs), list(pairs)[:5]))
    print(f"Pattern(3.2.5): event_id with inconsistent day/start across weeks: {len(pattern_bad)}")
    if pattern_bad:
        df = pd.DataFrame(pattern_bad, columns=["event_id", "num_distinct(day,start)", "examples"])
        print(df.head(20).to_string(index=False))

    # Conflict(3.2.3): no (week, room_id, day, slot) overlap for room-required rows
    occ: Set[Tuple[int, str, int, int]] = set()
    conflicts = []
    checked_cells = 0

    room_required_rows = sol[
        (sol["req_room_type_norm"] != NO_ROOM_FLAG) &
        (~sol["room_id"].apply(is_empty_room)) &
        (sol["week_num"].notna())
    ]

    for _, row in room_required_rows.iterrows():
        wk = int(row["week_num"])
        rid = str(row["room_id"])
        day = str(row["assigned_day"])
        if day not in DAY2IDX:
            continue
        d_idx = DAY2IDX[day]
        if not valid_start_hour(row["assigned_start_hour"]) or not valid_L(row["L_slots"]):
            continue
        start_slot = HOUR2SLOT[int(row["assigned_start_hour"])]
        L = int(row["L_slots"])

        for s in range(start_slot, start_slot + L):
            key = (wk, rid, d_idx, s)
            checked_cells += 1
            if key in occ:
                conflicts.append((row["event_id"], wk, rid, day, SLOT_START_HOURS[s]))
            else:
                occ.add(key)

    print(f"Conflict(3.2.3): total occupied cells checked = {checked_cells}")
    print(f"Conflict(3.2.3): conflicts = {len(conflicts)}")
    if conflicts:
        print(conflicts[:20])

    # ------------------------------------------------------------------
    # VERDICT
    failed = (
        len(week_bad) > 0 or
        len(s1_bad) > 0 or
        len(s1b_bad) > 0 or
        len(s2a_bad) > 0 or
        len(s2b_bad_rows) > 0 or
        len(s3a_bad) > 0 or
        len(overflow_rows) > 0 or
        len(s4a_bad) > 0 or
        len(pattern_bad) > 0 or
        len(conflicts) > 0
    )

    print("\n=== VERDICT ===")
    print("FAILED (see counts above)" if failed else "PASSED (all hard checks satisfied)")

if __name__ == "__main__":
    main()