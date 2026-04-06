# evaluate_from_excel.py
# Directly evaluate all soft constraint metrics from three Excel files:
# student_split / event_split / room, without any intermediate files

import pandas as pd
import math
import re
from itertools import combinations
from collections import defaultdict

# ============================================================
#  ★ Modify file paths here
# ============================================================
EVENT_XLSX = "events_split.xlsx"  # Timetable file
STUDENT_XLSX = "student_split.xlsx"  # Student course selection file
ROOM_XLSX = "room.xlsx"  # Room capacity file

# ============================================================
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ──────────────────────────────────────────────
# 1. Read & clean event_split
# ──────────────────────────────────────────────
def load_events(path):
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip()

    # Column name mapping (handles case/spacing variations)
    rename = {
        "Event ID": "event_id",
        "Event Name": "event_name",
        "Event Type": "event_type",
        "Expected Campus": "expected_campus",
        "Weekday": "assigned_day",
        "Start_Time": "start_time_raw",
        "Timeslot": "timeslot_raw",
        "Duration (minutes)": "duration_min",
        "Number of Weeks": "num_weeks",
        "Weeks": "weeks_raw",
        "Room type 2": "room_type2",
        "Event Size": "size",
        "WholeClass": "whole_class",
        "Online Delivery": "online_delivery",
        "Module Code": "module_code",
        "Module Name": "module_name",
        "Room": "room_id",
        "Building": "building",
        "Campus": "room_campus",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    # ── Parse start hour ──────────────────────────────
    def _parse_hour(row):
        for col in ["start_time_raw", "timeslot_raw"]:
            val = row.get(col, None)
            if pd.notna(val):
                m = re.search(r"(\d{1,2}):(\d{2})", str(val))
                if m:
                    return int(m.group(1))
        return None

    df["assigned_start_hour"] = df.apply(_parse_hour, axis=1)

    # ── Parse assigned_day ──
    if "assigned_day" not in df.columns or df["assigned_day"].isna().all():
        def _parse_day(ts):
            if pd.isna(ts):
                return None
            for d in DAYS:
                if str(ts).strip().startswith(d):
                    return d
            return None

        df["assigned_day"] = df.get("timeslot_raw", pd.Series()).apply(_parse_day)

    # ── Duration -> L_slots (round up to full hour) ──
    df["L_slots"] = df["duration_min"].apply(
        lambda x: math.ceil(float(x) / 60) if pd.notna(x) else 1
    )

    # ── Expand Weeks ────────────────────────────────
    def _parse_weeks(w):
        if pd.isna(w):
            return [1]
        weeks = []
        for part in re.split(r"[,;]", str(w)):
            part = part.strip()
            m = re.match(r"^(\d+)-(\d+)$", part)
            if m:
                weeks.extend(range(int(m.group(1)), int(m.group(2)) + 1))
            elif part.isdigit():
                weeks.append(int(part))
        return weeks if weeks else [1]

    rows_expanded = []
    for _, row in df.iterrows():
        weeks_list = _parse_weeks(row.get("weeks_raw"))
        for wk in weeks_list:
            r = row.to_dict()
            r["week"] = wk
            rows_expanded.append(r)

    sol = pd.DataFrame(rows_expanded)

    # ── Data cleaning ─────────────────────────────────
    sol["event_id"] = sol["event_id"].astype(str).str.strip()
    sol["assigned_day"] = sol["assigned_day"].astype(str).str.strip()
    sol["assigned_start_hour"] = pd.to_numeric(sol["assigned_start_hour"], errors="coerce")
    sol["L_slots"] = pd.to_numeric(sol["L_slots"], errors="coerce")
    sol["size"] = pd.to_numeric(sol.get("size", 0), errors="coerce").fillna(0).astype(int)
    sol["week"] = pd.to_numeric(sol["week"], errors="coerce").fillna(1).astype(int)

    sol["whole_class"] = sol.get("whole_class", "FALSE").astype(str).str.strip().str.upper()
    sol.loc[sol["whole_class"].isin(["NAN", "NONE", "NULL", ""]), "whole_class"] = "FALSE"

    if "room_id" in sol.columns:
        sol["room_id"] = sol["room_id"].astype(str).str.strip()
        sol.loc[sol["room_id"].isin(["0", "nan", "None", "NULL", ""]), "room_id"] = ""
    else:
        sol["room_id"] = ""

    if "room_campus" not in sol.columns:
        sol["room_campus"] = ""
    sol["room_campus"] = sol["room_campus"].fillna("").astype(str).str.strip()

    if "expected_campus" not in sol.columns:
        sol["expected_campus"] = ""
    sol["expected_campus"] = sol["expected_campus"].fillna("").astype(str).str.strip()

    # Filter invalid rows
    sol = sol[
        sol["assigned_day"].isin(DAYS)
        & sol["assigned_start_hour"].notna()
        & sol["L_slots"].notna()
        ].copy()

    sol["start_slot"] = sol["assigned_start_hour"].astype(int)
    sol["end_slot"] = sol["start_slot"] + sol["L_slots"].astype(int)

    # Add a unique identifier for each class instance (each course per week)
    sol["class_instance_id"] = sol["event_id"] + "_w" + sol["week"].astype(str)

    print(f"[event_split] Read {len(df)} courses → Expanded to {len(sol)} class instances (courses × weeks)")
    return sol


# ──────────────────────────────────────────────
# 2. Read rooms
# ──────────────────────────────────────────────
def load_rooms(path):
    rm = pd.read_excel(path)
    rm.columns = rm.columns.str.strip()

    rename = {
        "Id": "room_id",
        "Capacity": "cap",
        "Campus": "room_campus",
        "Room Type": "room_type",
        "Specialist room type": "specialist_type",
        "Building": "building",
    }
    rm = rm.rename(columns={k: v for k, v in rename.items() if k in rm.columns})

    rm["room_id"] = rm["room_id"].astype(str).str.strip()
    rm["cap"] = pd.to_numeric(rm["cap"], errors="coerce")

    print(f"[room] Read {len(rm)} rooms")
    return rm


# ──────────────────────────────────────────────
# 3. Build event_overlap from student_split
# ──────────────────────────────────────────────
def build_event_overlap(path):
    """
    Expected student_split format (any of the following):
      A) Wide table: one row per student, columns as Event IDs
      B) Long table: two columns [student_id, event_id] (or similar names)

    Function automatically detects format and generates event_overlap:
      { (event1, event2) -> shared_student_count }
    """
    df = pd.read_excel(path)
    df.columns = df.columns.str.strip()
    print(f"[student_split] Read {len(df)} rows, columns: {df.columns.tolist()[:10]}...")

    # ── Detect format ──────────────────────────────────
    student_col = None
    event_col = None

    # Try to identify student column
    for c in df.columns:
        if re.search(r"student|stu|matric|id", c, re.I):
            student_col = c
            break

    # Try to identify event column
    for c in df.columns:
        if re.search(r"event", c, re.I):
            event_col = c
            break

    if student_col and event_col:
        # ── Long table mode ──────────────────────────────
        print(f"  → Long table mode: student='{student_col}', event='{event_col}'")
        df[student_col] = df[student_col].astype(str).str.strip()
        df[event_col] = df[event_col].astype(str).str.strip()
        student_events = df.groupby(student_col)[event_col].apply(list).to_dict()

    else:
        # ── Wide table mode ──────────────────────────────
        print("  → Wide table mode (one row per student, columns as event IDs)")
        id_col = df.columns[0]
        event_cols = df.columns[1:]
        student_events = {}
        for _, row in df.iterrows():
            sid = str(row[id_col]).strip()
            evs = [str(row[c]).strip() for c in event_cols
                   if pd.notna(row[c]) and str(row[c]).strip() not in ("", "nan", "NULL")]
            if evs:
                student_events[sid] = evs

    # ── Calculate overlap ─────────────────────────────
    overlap = defaultdict(int)
    total_students = len(student_events)

    for idx, (sid, events) in enumerate(student_events.items()):
        if idx % 5000 == 0:
            print(f"  Processing student {idx}/{total_students}...", end="\r")
        events = list(set(events))
        for e1, e2 in combinations(sorted(events), 2):
            overlap[(e1, e2)] += 1

    print(f"\n  → Generated {len(overlap)} event pairs (with shared students)")
    return overlap


# ──────────────────────────────────────────────
# Utility functions
# ──────────────────────────────────────────────
def overlaps(s1, e1, s2, e2):
    return max(s1, s2) < min(e1, e2)


def pct(part, whole):
    return 100.0 * part / whole if whole else 0.0


def clash_weight(wc1, wc2):
    wc1, wc2 = str(wc1).upper(), str(wc2).upper()
    if wc1 == "TRUE" and wc2 == "TRUE":
        return 1.0
    if wc1 == "TRUE" or wc2 == "TRUE":
        return 0.7
    return 0.3


# ──────────────────────────────────────────────
# Metric functions (all violations based on expanded class instances)
# ──────────────────────────────────────────────

def eval_student_clash(sol, overlap_dict):
    """[1] Student Clash - Check time conflicts for courses students take simultaneously"""
    wc_map = dict(zip(sol["event_id"], sol["whole_class"]))

    # Build schedule for each event: [(week, day, start_slot, end_slot)]
    sched = defaultdict(list)
    for r in sol.itertuples(index=False):
        sched[r.event_id].append((r.week, r.assigned_day, r.start_slot, r.end_slot))

    clash_count = 0  # Number of conflicting course-pair-week combinations
    total_penalty = 0.0
    details = []

    for (e1, e2), shared in overlap_dict.items():
        if e1 not in sched or e2 not in sched:
            continue

        # Check each week for conflicts
        for wk1, d1, s1, end1 in sched[e1]:
            for wk2, d2, s2, end2 in sched[e2]:
                # Must be same week and same day
                if wk1 != wk2 or d1 != d2:
                    continue
                # Check if times overlap
                if overlaps(s1, end1, s2, end2):
                    clash_count += 1
                    w = clash_weight(wc_map.get(e1, "FALSE"), wc_map.get(e2, "FALSE"))
                    total_penalty += shared * w
                    if len(details) < 50000:
                        details.append({
                            "event1": e1, "event2": e2, "shared": shared,
                            "week": wk1, "day": d1,
                            "start1": s1, "end1": end1, "start2": s2, "end2": end2
                        })
                    break  # Record one conflict per course pair per week

    return clash_count, total_penalty, len(overlap_dict), pd.DataFrame(details)


def eval_after_5pm(sol):
    """[2a] WholeClass events ending after 17:00 - counted by class instances"""
    tmp = sol[sol["whole_class"] == "TRUE"].copy()
    tmp["end_hour"] = tmp["assigned_start_hour"] + tmp["L_slots"]
    bad = tmp[tmp["end_hour"] > 17]
    return len(bad)  # Number of violating class instances


def eval_wednesday_afternoon(sol):
    """[2b] WholeClass events occupying Wednesday afternoon (course time overlaps with 13:00-17:00) - counted by class instances"""
    # Filter WholeClass class instances on Wednesday
    tmp = sol[
        (sol["whole_class"] == "TRUE") & (sol["assigned_day"] == "Wednesday")
        ].copy()

    # Define Wednesday afternoon time period
    AFTERNOON_START = 13  # 13:00
    AFTERNOON_END = 17    # 17:00

    def overlaps_with_afternoon(start_hour, duration):
        """Check if course time overlaps with Wednesday afternoon period"""
        end_hour = start_hour + duration
        # Overlap condition: not entirely before afternoon and not entirely after afternoon
        return not (end_hour <= AFTERNOON_START or start_hour >= AFTERNOON_END)

    # Mark which class instances violate the constraint
    tmp["violates"] = tmp.apply(
        lambda row: overlaps_with_afternoon(row["assigned_start_hour"], row["L_slots"]),
        axis=1
    )

    bad = tmp[tmp["violates"]]
    return len(bad)  # Number of violating class instances


def eval_lunch_break(sol):
    """[3] Classes during lunch time (starting at 12:00 or 13:00) - counted by class instances"""
    bad = sol[sol["assigned_start_hour"].isin([12, 13])]
    return len(bad)  # Number of violating class instances


def eval_same_room(sol):
    """[4] Same course using different rooms across weeks - violations counted by course, penalty by number of room changes"""
    tmp = sol[sol["room_id"] != ""].copy()
    event_rooms = defaultdict(set)

    # Collect all rooms used by each course
    for _, row in tmp.iterrows():
        event_rooms[row["event_id"]].add(row["room_id"])

    # Count how many courses use multiple rooms
    multi_room_events = 0
    total_room_changes = 0

    for event_id, rooms in event_rooms.items():
        if len(rooms) > 1:
            multi_room_events += 1
            total_room_changes += len(rooms) - 1  # Number of room changes = number of rooms - 1

    return multi_room_events, total_room_changes


def eval_room_capacity(sol, rm):
    """[5] Room capacity insufficient - counted by class instances"""
    tmp = sol[sol["room_id"] != ""].copy()
    tmp = tmp.merge(rm[["room_id", "cap"]], on="room_id", how="left")
    tmp["size"] = pd.to_numeric(tmp["size"], errors="coerce")
    tmp["cap"] = pd.to_numeric(tmp["cap"], errors="coerce")

    # Find class instances exceeding capacity
    bad = tmp[tmp["cap"].notna() & tmp["size"].notna() & (tmp["size"] > tmp["cap"])].copy()
    bad["overflow"] = bad["size"] - bad["cap"]

    return len(bad), bad["overflow"].sum() if len(bad) else 0


def eval_campus_mismatch(sol):
    """[6] Campus mismatch - counted by class instances"""
    NO_ROOM = "no room required"
    tmp = sol[sol["room_id"] != ""].copy()
    tmp["ec"] = tmp["expected_campus"].str.lower().str.strip()
    tmp["rc"] = tmp["room_campus"].str.lower().str.strip()

    bad = tmp[
        (~tmp["ec"].isin(["", NO_ROOM, "nan", "none", "null"]))
        & (tmp["ec"] != tmp["rc"])
        ]
    return len(bad)  # Number of violating class instances


# ──────────────────────────────────────────────
# Main program
# ──────────────────────────────────────────────
def main():
    print("=" * 60)
    print("Reading data...")
    print("=" * 60)

    sol = load_events(EVENT_XLSX)
    rm = load_rooms(ROOM_XLSX)
    overlap_dict = build_event_overlap(STUDENT_XLSX)

    # Basic statistics - all based on expanded class instances
    total_class_instances = len(sol)  # Total class instances (courses × weeks)
    wc_class_instances = len(sol[sol["whole_class"] == "TRUE"])  # WholeClass class instances
    room_class_instances = len(sol[sol["room_id"] != ""])  # Class instances with room assignment

    campus_applicable = len(
        sol[
            (sol["room_id"] != "")
            & (~sol["expected_campus"].str.lower().isin(["", "no room required", "nan", "none", "null"]))
            ]
    )  # Class instances applicable for campus check

    unique_events = sol["event_id"].nunique()  # Number of unique courses

    print()
    print("=" * 60)
    print(f"Statistics Summary (based on expanded data):")
    print(f"  Total class instances:          {total_class_instances}")
    print(f"  WholeClass class instances:     {wc_class_instances}")
    print(f"  Class instances with rooms:     {room_class_instances}")
    print(f"  Class instances applicable for campus check: {campus_applicable}")
    print(f"  Unique courses:                 {unique_events}")
    print("=" * 60)

    print()
    print("Running metric evaluation...")
    print("=" * 60)

    # Evaluate each metric
    c1_count, c1_pen, c1_total_pairs, clash_df = eval_student_clash(sol, overlap_dict)
    c2a_count = eval_after_5pm(sol)
    c2b_count = eval_wednesday_afternoon(sol)
    c3_count = eval_lunch_break(sol)
    c4_count, c4_pen = eval_same_room(sol)
    c5_count, c5_pen = eval_room_capacity(sol, rm)
    c6_count = eval_campus_mismatch(sol)

    # ── Print report ─────────────────────────────────
    print()
    print("=" * 60)
    print("Soft Constraint Evaluation Results")
    print("=" * 60)

    print("\n[1] Student Clash")
    print(f"  Conflicting course-pair-week count:   {c1_count}")
    print(f"  Percentage of all course-pair-weeks:   {pct(c1_count, c1_total_pairs):.2f}%  ({c1_count}/{c1_total_pairs})")
    print(f"  Weighted clash penalty:                {c1_pen:.2f}")

    print("\n[2a] WholeClass After 5pm")
    print(f"  Violating class instances:             {c2a_count}")
    print(f"  Percentage of WholeClass instances:    {pct(c2a_count, wc_class_instances):.2f}%  ({c2a_count}/{wc_class_instances})")
    print(f"  Penalty:                               {c2a_count}")

    print("\n[2b] Wednesday Afternoon WholeClass")
    print(f"  Violating class instances:             {c2b_count}")
    print(f"  Percentage of WholeClass instances:    {pct(c2b_count, wc_class_instances):.2f}%  ({c2b_count}/{wc_class_instances})")
    print(f"  Penalty:                               {c2b_count}")

    print("\n[3] Lunch Break (12:00 or 13:00)")
    print(f"  Violating class instances:             {c3_count}")
    print(f"  Percentage of total class instances:   {pct(c3_count, total_class_instances):.2f}%  ({c3_count}/{total_class_instances})")
    print(f"  Penalty:                               {c3_count}")

    print("\n[4] Same Room Across Weeks")
    print(f"  Courses changing rooms across weeks:   {c4_count}")
    print(f"  Percentage of all courses:             {pct(c4_count, unique_events):.2f}%  ({c4_count}/{unique_events})")
    print(f"  Penalty (total room changes):          {c4_pen}")

    print("\n[5] Room Capacity Violation")
    print(f"  Over-capacity class instances:         {c5_count}")
    print(f"  Percentage of room-assigned instances: {pct(c5_count, room_class_instances):.2f}%  ({c5_count}/{room_class_instances})")
    print(f"  Penalty (total overflow sum):          {c5_pen:.0f}")

    print("\n[6] Campus Mismatch")
    print(f"  Campus-mismatched class instances:     {c6_count}")
    print(f"  Percentage of applicable instances:    {pct(c6_count, campus_applicable):.2f}%  ({c6_count}/{campus_applicable})")
    print(f"  Penalty:                               {c6_count}")

    # ── Objective Score ──────────────────────────
    W = dict(clash=250, evening=40, wed=30, lunch=20, same_room=20, capacity=30, campus=10)

    contribs = {
        "Student Clash": W["clash"] * c1_pen,
        "After 5pm": W["evening"] * c2a_count,
        "Wednesday Afternoon": W["wed"] * c2b_count,
        "Lunch Break": W["lunch"] * c3_count,
        "Same Room": W["same_room"] * c4_pen,
        "Room Capacity": W["capacity"] * c5_pen,
        "Campus Mismatch": W["campus"] * c6_count,
    }
    objective = sum(contribs.values())

    print()
    print("=" * 60)
    print(f"Objective Score: {objective:.2f}")
    print("=" * 60)
    print("Contribution by metric:")
    for name, val in contribs.items():
        print(f"  {name:<25} {val:>12.2f}   ({pct(val, objective):.1f}%)")

    # ── Save clash details ───────────────────────────
    if not clash_df.empty:
        clash_df.to_csv("student_clash_details.csv", index=False)
        print(f"\nStudent clash details saved to: student_clash_details.csv  ({len(clash_df)} rows)")

    return {
        "objective": round(objective, 2),
        "total_class_instances": total_class_instances,
        "wc_class_instances": wc_class_instances,
        "room_class_instances": room_class_instances,
        "clash_count": c1_count,
        "clash_penalty": c1_pen,
        "evening_count": c2a_count,
        "evening_pct": round(pct(c2a_count, wc_class_instances), 2),
        "wed_count": c2b_count,
        "wed_pct": round(pct(c2b_count, wc_class_instances), 2),
        "lunch_count": c3_count,
        "lunch_pct": round(pct(c3_count, total_class_instances), 2),
        "same_room_count": c4_count,
        "same_room_pct": round(pct(c4_count, unique_events), 2),
        "cap_count": c5_count,
        "cap_pct": round(pct(c5_count, room_class_instances), 2),
        "campus_count": c6_count,
        "campus_pct": round(pct(c6_count, campus_applicable), 2),
    }


if __name__ == "__main__":
    main()