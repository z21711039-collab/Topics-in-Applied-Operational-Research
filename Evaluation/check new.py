from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd


# STEP2_CSV = "step2_solution_with_rooms_by_week_mon_fri_9_5_repaired.csv"
# STEP2_CSV = "events_expanded.csv"
STEP2_CSV = "step2_like_from_cleaned_programme_optimized.csv"
OVERLAP_CSV = "event_overlap.csv"
ROOMS_XLSX = "room.xlsx"
EVENTS_XLSX = "events.xlsx"
OUTPUT_CLASH_DETAIL_CSV = "student_clash_details.csv"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
HOUR_TO_SLOT = {hour: slot for slot, hour in enumerate(range(9, 18))}
NO_ROOM_FLAG = "No room required"
LUNCH_START_HOUR = 12
LUNCH_END_HOUR = 14
ROOMTYPE_MAP: dict[str, str] = {}


@dataclass(frozen=True)
class ObjectiveWeights:
    clash: int = 250
    capacity: int = 30
    after_5pm: int = 40
    wednesday: int = 30
    lunch: int = 20
    campus: int = 10
    same_room: int = 20


def debug_log(enabled: bool, message: str) -> None:
    if enabled:
        print(f"[DEBUG] {message}")


def normalize_room_type(value: object) -> str:
    if pd.isna(value):
        return NO_ROOM_FLAG
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null", ""}:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(text, text)


def intervals_overlap(start1: int, end1: int, start2: int, end2: int) -> bool:
    return max(start1, start2) < min(end1, end2)


def parse_weeks(value: object) -> list[int]:
    if pd.isna(value):
        return []
    weeks: list[int] = []
    for token in str(value).split(","):
        token = token.strip()
        if token.isdigit():
            weeks.append(int(token))
    return weeks


def ensure_columns(frame: pd.DataFrame, required_columns: Iterable[str], frame_name: str) -> None:
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ValueError(f"{frame_name} is missing required columns: {missing}")


def load_schedule(step2_csv: str, debug: bool = False) -> pd.DataFrame:
    schedule = pd.read_csv(step2_csv).copy()
    debug_log(debug, f"Raw schedule rows: {len(schedule)}")

    has_week_column = "week" in schedule.columns

    if (not has_week_column) and "weeks" in schedule.columns and schedule["weeks"].notna().any():
        schedule["weeks_list"] = schedule["weeks"].apply(parse_weeks)
        expanded_rows = []
        for row in schedule.itertuples(index=False):
            weeks_list = list(getattr(row, "weeks_list", []))
            row_dict = row._asdict()
            row_dict.pop("weeks_list", None)
            if weeks_list:
                for week in weeks_list:
                    expanded_row = row_dict.copy()
                    expanded_row["week"] = week
                    expanded_rows.append(expanded_row)
            else:
                expanded_rows.append(row_dict)
        schedule = pd.DataFrame(expanded_rows)
        debug_log(debug, f"Expanded schedule rows by weeks: {len(schedule)}")

    if has_week_column:
        debug_log(debug, "Detected existing 'week' column. Skipping expansion from 'weeks'.")
    elif "weeks" in schedule.columns:
        schedule["week"] = schedule["weeks"].apply(
            lambda value: int(str(value).strip()) if pd.notna(value) and str(value).strip().isdigit() else None
        )

    ensure_columns(
        schedule,
        ["event_id", "assigned_day", "assigned_start_hour", "L_slots", "week"],
        "schedule",
    )

    schedule["event_id"] = schedule["event_id"].astype(str).str.strip()
    schedule["assigned_day"] = schedule["assigned_day"].astype(str).str.strip()
    schedule["week"] = pd.to_numeric(schedule["week"], errors="coerce")
    schedule["assigned_start_hour"] = pd.to_numeric(schedule["assigned_start_hour"], errors="coerce")
    schedule["L_slots"] = pd.to_numeric(schedule["L_slots"], errors="coerce")

    if "size" not in schedule.columns:
        schedule["size"] = None
    if "room_id" not in schedule.columns:
        schedule["room_id"] = ""
    if "room_campus" not in schedule.columns:
        schedule["room_campus"] = ""

    schedule = schedule[
        schedule["week"].notna()
        & schedule["assigned_start_hour"].notna()
        & schedule["L_slots"].notna()
        & schedule["assigned_day"].isin(DAYS)
    ].copy()

    schedule["week"] = schedule["week"].astype(int)
    schedule["assigned_start_hour"] = schedule["assigned_start_hour"].astype(int)
    schedule["L_slots"] = schedule["L_slots"].astype(int)
    schedule["start_slot"] = schedule["assigned_start_hour"].map(HOUR_TO_SLOT)
    schedule = schedule[schedule["start_slot"].notna()].copy()
    schedule["start_slot"] = schedule["start_slot"].astype(int)
    schedule["end_slot"] = schedule["start_slot"] + schedule["L_slots"]
    schedule["end_hour"] = schedule["assigned_start_hour"] + schedule["L_slots"]
    schedule["room_id"] = schedule["room_id"].fillna("").astype(str).str.strip()
    schedule["room_campus"] = schedule["room_campus"].fillna("").astype(str).str.strip()

    debug_log(debug, f"Clean schedule rows: {len(schedule)}")
    return schedule


def load_room_data(rooms_xlsx: str = ROOMS_XLSX) -> pd.DataFrame:
    rooms = pd.read_excel(rooms_xlsx).copy()
    rooms.columns = rooms.columns.str.strip()

    rename_map = {
        "Id": "room_id",
        "Room ID": "room_id",
        "Capacity": "cap",
        "Campus": "room_campus",
        "Specialist room type": "room_type",
    }
    rooms = rooms.rename(columns={k: v for k, v in rename_map.items() if k in rooms.columns})

    ensure_columns(rooms, ["room_id"], "rooms")

    if "cap" not in rooms.columns:
        rooms["cap"] = None
    if "room_type" not in rooms.columns:
        rooms["room_type"] = NO_ROOM_FLAG
    if "room_campus" not in rooms.columns:
        rooms["room_campus"] = ""

    rooms["room_id"] = rooms["room_id"].astype(str).str.strip()
    rooms["cap"] = pd.to_numeric(rooms["cap"], errors="coerce")
    rooms["room_type"] = rooms["room_type"].apply(normalize_room_type)
    rooms["room_campus"] = rooms["room_campus"].fillna("").astype(str).str.strip()
    return rooms


def load_event_data(events_xlsx: str = EVENTS_XLSX) -> pd.DataFrame:
    events = pd.read_excel(events_xlsx).copy()
    events.columns = events.columns.str.strip()

    rename_map = {
        "Event ID": "event_id",
        "Event Size": "size",
        "WholeClass": "whole_class",
        "Expected Campus": "event_campus",
    }
    events = events.rename(columns={k: v for k, v in rename_map.items() if k in events.columns})

    if "event_id" not in events.columns:
        events = events.rename(columns={events.columns[0]: "event_id"})

    if "size" not in events.columns:
        events["size"] = 0
    if "whole_class" not in events.columns:
        events["whole_class"] = "FALSE"
    if "event_campus" not in events.columns:
        events["event_campus"] = NO_ROOM_FLAG

    events["event_id"] = events["event_id"].astype(str).str.strip()
    events["size"] = pd.to_numeric(events["size"], errors="coerce").fillna(0).astype(int)
    events["whole_class"] = events["whole_class"].astype(str).str.strip().str.upper()
    events["event_campus"] = events["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()
    return events


def clash_weight(whole_class_1: str, whole_class_2: str) -> float:
    wc1 = str(whole_class_1).strip().upper()
    wc2 = str(whole_class_2).strip().upper()

    if wc1 == "TRUE" and wc2 == "TRUE":
        return 1.0
    if wc1 == "TRUE" or wc2 == "TRUE":
        return 0.7
    return 0.3


def evaluate_student_clash(schedule: pd.DataFrame, events: pd.DataFrame, overlap_csv: str) -> tuple[int, float, int]:
    whole_class_map = dict(zip(events["event_id"], events["whole_class"]))

    event_schedule: dict[str, list[tuple[int, str, int, int]]] = {}
    for row in schedule.itertuples(index=False):
        event_schedule.setdefault(row.event_id, []).append(
            (row.week, row.assigned_day, row.start_slot, row.end_slot)
        )

    total_penalty = 0.0
    clash_count = 0
    detail_rows: list[list[object]] = []
    total_overlap_pairs = 0

    try:
        chunks = pd.read_csv(overlap_csv, chunksize=200000)
        for chunk in chunks:
            chunk["event1"] = chunk["event1"].astype(str).str.strip()
            chunk["event2"] = chunk["event2"].astype(str).str.strip()
            chunk["shared_students"] = pd.to_numeric(chunk["shared_students"], errors="coerce").fillna(0).astype(int)
            total_overlap_pairs += len(chunk)

            for row in chunk.itertuples(index=False):
                event_1 = row.event1
                event_2 = row.event2
                shared_students = row.shared_students

                if event_1 not in event_schedule or event_2 not in event_schedule:
                    continue

                clash_found = False
                for week_1, day_1, start_1, end_1 in event_schedule[event_1]:
                    for week_2, day_2, start_2, end_2 in event_schedule[event_2]:
                        if week_1 != week_2 or day_1 != day_2:
                            continue
                        if not intervals_overlap(start_1, end_1, start_2, end_2):
                            continue

                        clash_count += 1
                        total_penalty += shared_students * clash_weight(
                            whole_class_map.get(event_1, "FALSE"),
                            whole_class_map.get(event_2, "FALSE"),
                        )
                        clash_found = True

                        if len(detail_rows) < 50000:
                            detail_rows.append(
                                [event_1, event_2, shared_students, week_1, day_1, start_1, end_1, start_2, end_2]
                            )
                        break
                    if clash_found:
                        break
    except FileNotFoundError:
        print(f"Warning: could not find overlap file {overlap_csv}. Student clash evaluation was skipped.")
        return 0, 0.0, 0

    if detail_rows:
        detail_df = pd.DataFrame(
            detail_rows,
            columns=["event1", "event2", "shared_students", "week", "day", "start1", "end1", "start2", "end2"],
        )
        detail_df.to_csv(OUTPUT_CLASH_DETAIL_CSV, index=False)

    return clash_count, total_penalty, total_overlap_pairs


def evaluate_after_5pm(schedule: pd.DataFrame, events: pd.DataFrame) -> tuple[int, int]:
    whole_class_events = set(events.loc[events["whole_class"] == "TRUE", "event_id"])
    bad = schedule[(schedule["event_id"].isin(whole_class_events)) & (schedule["end_hour"] > 17)].copy()
    return len(bad), len(bad)


def evaluate_wednesday_afternoon_wholeclass(schedule: pd.DataFrame, events: pd.DataFrame) -> tuple[int, int]:
    whole_class_events = set(events.loc[events["whole_class"] == "TRUE", "event_id"])
    bad = schedule[
        (schedule["event_id"].isin(whole_class_events))
        & (schedule["assigned_day"] == "Wednesday")
        & (schedule["end_hour"] > 13)
    ].copy()
    return len(bad), len(bad)


def overlaps_lunch_window(start_hour: int, end_hour: int) -> bool:
    return intervals_overlap(start_hour, end_hour, LUNCH_START_HOUR, LUNCH_END_HOUR)


def evaluate_lunch_break(schedule: pd.DataFrame) -> tuple[int, int]:
    lunch_mask = schedule["assigned_start_hour"].isin([12, 13])
    bad = schedule[lunch_mask].copy()
    return len(bad), len(bad)


def evaluate_same_room_across_weeks(schedule: pd.DataFrame) -> tuple[int, int]:
    room_schedule = schedule[schedule["room_id"] != ""].copy()

    count_bad_events = 0
    penalty = 0
    for _, group in room_schedule.groupby("event_id", sort=False):
        rooms = set(group["room_id"])
        if len(rooms) > 1:
            count_bad_events += 1
            penalty += len(rooms) - 1
    return count_bad_events, penalty


def evaluate_room_capacity(schedule: pd.DataFrame, rooms: pd.DataFrame) -> tuple[int, float]:
    room_capacity = schedule.merge(rooms[["room_id", "cap"]], on="room_id", how="left")
    room_capacity["size"] = pd.to_numeric(room_capacity["size"], errors="coerce")
    room_capacity["cap"] = pd.to_numeric(room_capacity["cap"], errors="coerce")

    bad = room_capacity[
        (room_capacity["room_id"] != "")
        & room_capacity["cap"].notna()
        & room_capacity["size"].notna()
        & (room_capacity["size"] > room_capacity["cap"])
    ].copy()
    bad["overflow"] = bad["size"] - bad["cap"]
    return len(bad), float(bad["overflow"].sum()) if len(bad) else 0.0


def evaluate_expected_campus_mismatch(schedule: pd.DataFrame, events: pd.DataFrame) -> tuple[int, int]:
    campus_data = schedule.merge(events[["event_id", "event_campus"]], on="event_id", how="left")
    campus_data["event_campus"] = campus_data["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()
    campus_data["room_campus"] = campus_data["room_campus"].fillna("").astype(str).str.strip()

    bad = campus_data[
        (campus_data["room_id"] != "")
        & (campus_data["event_campus"] != NO_ROOM_FLAG)
        & (campus_data["event_campus"] != campus_data["room_campus"])
    ].copy()
    return len(bad), len(bad)


def percentage(part: float, whole: float) -> float:
    if whole == 0:
        return 0.0
    return 100.0 * part / whole


def calculate_utilisation_metrics(schedule: pd.DataFrame, scenario: str) -> dict[str, object]:
    timeslot_usage = schedule.groupby(["assigned_day", "assigned_start_hour"]).size().reset_index(name="count")

    if len(timeslot_usage) > 0:
        peak = timeslot_usage.loc[timeslot_usage["count"].idxmax()]
        peak_day = peak["assigned_day"]
        peak_hour = int(peak["assigned_start_hour"])
        peak_events = int(peak["count"])
    else:
        peak_day = "None"
        peak_hour = 0
        peak_events = 0

    used_timeslots = len(timeslot_usage)
    avg_events_per_used_timeslot = float(timeslot_usage["count"].mean()) if len(timeslot_usage) else 0.0

    if scenario == "mon_fri_9_5":
        total_available_timeslots = 5 * 8
    elif scenario == "no_friday_afternoon":
        total_available_timeslots = 39
    else:
        total_available_timeslots = 45

    timeslot_utilisation = used_timeslots / total_available_timeslots if total_available_timeslots else 0.0

    room_only = schedule[schedule["room_id"] != ""].copy()
    total_rooms = room_only["room_id"].nunique() if len(room_only) else 0
    if total_rooms > 0:
        room_usage = (
            room_only.groupby(["assigned_day", "assigned_start_hour"])["room_id"]
            .nunique()
            .reset_index(name="rooms_used")
        )
        room_usage["utilisation"] = room_usage["rooms_used"] / total_rooms
        avg_room_utilisation = float(room_usage["utilisation"].mean())
    else:
        avg_room_utilisation = 0.0

    return {
        "peak_day": peak_day,
        "peak_hour": peak_hour,
        "peak_events": peak_events,
        "used_timeslots": int(used_timeslots),
        "total_available_timeslots": int(total_available_timeslots),
        "timeslot_utilisation": round(timeslot_utilisation, 2),
        "avg_events_per_used_timeslot": round(avg_events_per_used_timeslot, 2),
        "avg_room_utilisation": round(avg_room_utilisation, 2),
    }


def print_metric(
    title: str,
    count_label: str,
    count_value: float,
    percentage_label: str,
    percentage_value: float,
    penalty_label: str,
    penalty_value: float,
) -> None:
    print(title)
    print(f"{count_label}: {count_value}")
    print(f"{percentage_label}: {percentage_value:.2f}%")
    print(f"{penalty_label}: {float(penalty_value):.2f}")
    print()


def main(
    step2_csv: str = STEP2_CSV,
    events_xlsx: str = EVENTS_XLSX,
    overlap_csv: str = OVERLAP_CSV,
    scenario: str = "baseline",
    debug: bool = False,
) -> dict[str, object]:
    print("Loading schedule data...")
    schedule = load_schedule(step2_csv, debug=debug)
    print(f"Loaded {len(schedule)} schedule rows")

    print("Loading room data...")
    rooms = load_room_data(ROOMS_XLSX)
    print(f"Loaded {len(rooms)} rooms")

    print("Loading event data...")
    events = load_event_data(events_xlsx)
    print(f"Loaded {len(events)} events")

    total_occurrences = len(schedule)
    total_room_occurrences = len(schedule[schedule["room_id"] != ""])
    total_events = schedule["event_id"].nunique()
    whole_class_events = set(events.loc[events["whole_class"] == "TRUE", "event_id"])
    total_wholeclass_occurrences = len(schedule[schedule["event_id"].isin(whole_class_events)])

    campus_scope = schedule.merge(events[["event_id", "event_campus"]], on="event_id", how="left")
    campus_applicable_total = len(
        campus_scope[
            (campus_scope["room_id"] != "")
            & (campus_scope["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip() != NO_ROOM_FLAG)
        ]
    )

    print("\n" + "=" * 60)
    print("Starting soft-constraint evaluation...")
    print("=" * 60)

    print("\n[1] Evaluating Student Clash...")
    clash_count, clash_penalty, total_overlap_pairs = evaluate_student_clash(schedule, events, overlap_csv)

    print("[2a] Evaluating Core Teaching After 5pm...")
    evening_count, evening_penalty = evaluate_after_5pm(schedule, events)

    print("[2b] Evaluating Wednesday Afternoon Whole-Class...")
    wed_count, wed_penalty = evaluate_wednesday_afternoon_wholeclass(schedule, events)

    print("[3] Evaluating Lunch Break...")
    lunch_count, lunch_penalty = evaluate_lunch_break(schedule)

    print("[4] Evaluating Same Room Across Weeks...")
    same_room_bad_events, same_room_penalty = evaluate_same_room_across_weeks(schedule)

    print("[5] Evaluating Room Capacity...")
    cap_bad_count, cap_penalty = evaluate_room_capacity(schedule, rooms)

    print("[6] Evaluating Campus Mismatch...")
    campus_bad_count, campus_penalty = evaluate_expected_campus_mismatch(schedule, events)

    print("\n" + "=" * 60)
    print("Soft-constraint evaluation summary")
    print("=" * 60)
    print()

    print_metric(
        "[1] Student Clash",
        "Number of conflicting event pairs",
        clash_count,
        "Share of all overlap pairs",
        percentage(clash_count, total_overlap_pairs),
        "Total clash penalty",
        clash_penalty,
    )
    print_metric(
        "[2a] Core Teaching After 5pm",
        "Number of violations",
        evening_count,
        "Share of whole-class occurrences",
        percentage(evening_count, total_wholeclass_occurrences),
        "Penalty",
        evening_penalty,
    )
    print_metric(
        "[2b] Wednesday Afternoon Whole-Class",
        "Number of violations",
        wed_count,
        "Share of whole-class occurrences",
        percentage(wed_count, total_wholeclass_occurrences),
        "Penalty",
        wed_penalty,
    )
    print_metric(
        "[3] Lunch Break",
        "Occurrences overlapping the lunch window (12:00-14:00)",
        lunch_count,
        "Share of all occurrences",
        percentage(lunch_count, total_occurrences),
        "Penalty",
        lunch_penalty,
    )
    print_metric(
        "[4] Same Room Across Weeks",
        "Events assigned to multiple rooms",
        same_room_bad_events,
        "Share of all events",
        percentage(same_room_bad_events, total_events),
        "Penalty",
        same_room_penalty,
    )
    print_metric(
        "[5] Room Capacity Violation",
        "Occurrences over room capacity",
        cap_bad_count,
        "Share of room-based occurrences",
        percentage(cap_bad_count, total_room_occurrences),
        "Penalty (total overflow)",
        cap_penalty,
    )
    print_metric(
        "[6] Expected Campus Mismatch",
        "Occurrences with campus mismatch",
        campus_bad_count,
        "Share of applicable occurrences",
        percentage(campus_bad_count, campus_applicable_total),
        "Penalty",
        campus_penalty,
    )

    if clash_count > 0:
        print(f"Student clash detail file: {OUTPUT_CLASH_DETAIL_CSV}")

    weights = ObjectiveWeights()
    clash_contrib = weights.clash * clash_penalty
    evening_contrib = weights.after_5pm * evening_penalty
    wed_contrib = weights.wednesday * wed_penalty
    lunch_contrib = weights.lunch * lunch_penalty
    same_room_contrib = weights.same_room * same_room_penalty
    capacity_contrib = weights.capacity * cap_penalty
    campus_contrib = weights.campus * campus_penalty
    objective = (
        clash_contrib
        + evening_contrib
        + wed_contrib
        + lunch_contrib
        + same_room_contrib
        + capacity_contrib
        + campus_contrib
    )

    print("\n" + "=" * 60)
    print("Objective Score")
    print("=" * 60)
    print(f"Total objective: {float(objective):.2f}")
    print()

    print("Objective contribution breakdown")
    print(f"Student Clash contribution: {float(clash_contrib):.2f} ({percentage(clash_contrib, objective):.2f}%)")
    print(f"After 5pm contribution: {float(evening_contrib):.2f} ({percentage(evening_contrib, objective):.2f}%)")
    print(f"Wednesday contribution: {float(wed_contrib):.2f} ({percentage(wed_contrib, objective):.2f}%)")
    print(f"Lunch contribution: {float(lunch_contrib):.2f} ({percentage(lunch_contrib, objective):.2f}%)")
    print(f"Same Room contribution: {float(same_room_contrib):.2f} ({percentage(same_room_contrib, objective):.2f}%)")
    print(f"Capacity contribution: {float(capacity_contrib):.2f} ({percentage(capacity_contrib, objective):.2f}%)")
    print(f"Campus contribution: {float(campus_contrib):.2f} ({percentage(campus_contrib, objective):.2f}%)")

    utilisation = calculate_utilisation_metrics(schedule, scenario)

    print("\n" + "=" * 60)
    print("Utilisation Analysis")
    print("=" * 60)
    print(
        f"Peak timeslot: {utilisation['peak_day']} at {utilisation['peak_hour']}:00 "
        f"({utilisation['peak_events']} events)"
    )
    print(f"Timeslot utilisation: {utilisation['timeslot_utilisation'] * 100:.2f}%")
    print(f"Average events per used timeslot: {utilisation['avg_events_per_used_timeslot']:.2f}")
    print(f"Average room utilisation: {utilisation['avg_room_utilisation'] * 100:.2f}%")

    return {
        "objective": round(float(objective), 2),
        "clash_count": clash_count,
        "evening_count": evening_count,
        "wed_count": wed_count,
        "lunch_count": lunch_count,
        "same_room_bad_events": same_room_bad_events,
        "cap_bad_count": cap_bad_count,
        "campus_bad_count": campus_bad_count,
        "clash_pct": round(percentage(clash_count, total_overlap_pairs), 2),
        "evening_pct": round(percentage(evening_count, total_wholeclass_occurrences), 2),
        "wed_pct": round(percentage(wed_count, total_wholeclass_occurrences), 2),
        "lunch_pct": round(percentage(lunch_count, total_occurrences), 2),
        "same_room_pct": round(percentage(same_room_bad_events, total_events), 2),
        "cap_pct": round(percentage(cap_bad_count, total_room_occurrences), 2),
        "campus_pct": round(percentage(campus_bad_count, campus_applicable_total), 2),
        "peak_day": utilisation["peak_day"],
        "peak_hour": utilisation["peak_hour"],
        "peak_events": utilisation["peak_events"],
        "timeslot_utilisation": utilisation["timeslot_utilisation"],
        "avg_events_per_used_timeslot": utilisation["avg_events_per_used_timeslot"],
        "avg_room_utilisation": utilisation["avg_room_utilisation"],
    }


if __name__ == "__main__":
    summary = main(scenario="baseline")

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for key, value in summary.items():
        print(f"{key}: {value}")
