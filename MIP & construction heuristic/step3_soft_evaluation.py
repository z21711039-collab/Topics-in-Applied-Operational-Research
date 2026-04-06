# step3_soft_evaluation.py
# Evaluate soft constraint performance of current timetable
# Includes:
# 1. student clash
# 2. after 5pm
# 3. lunch break (approximate version: penalty if starts at 12pm/1pm)
# 4. same room across weeks
# 5. room capacity violation

import pandas as pd

STEP2_CSV = "step2_solution_with_rooms_by_week.csv"
OVERLAP_CSV = "event_overlap.csv"
ROOMS_XLSX = "room.xlsx"
EVENTS_XLSX = "events.xlsx"

OUTPUT_CLASH_DETAIL_CSV = "student_clash_details.csv"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
HOUR2SLOT = {h: i for i, h in enumerate(range(9, 18))}  # 9am~5pm -> 0~8

NO_ROOM_FLAG = "No room required"

ROOMTYPE_MAP = {}


def norm_room_type(x):
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s.lower() in ["nan", "none", "null", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)


def intervals_overlap(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)


def read_and_clean_step2_timetable(step2_csv):
    sol = pd.read_csv(step2_csv).copy()

    sol["event_id"] = sol["event_id"].astype(str).str.strip()
    sol["assigned_day"] = sol["assigned_day"].astype(str).str.strip()
    sol["week"] = pd.to_numeric(sol["week"], errors="coerce")
    sol["assigned_start_hour"] = pd.to_numeric(sol["assigned_start_hour"], errors="coerce")
    sol["L_slots"] = pd.to_numeric(sol["L_slots"], errors="coerce")

    sol = sol[
        sol["week"].notna()
        & sol["assigned_start_hour"].notna()
        & sol["L_slots"].notna()
        & sol["assigned_day"].isin(DAYS)
        ].copy()

    sol["week"] = sol["week"].astype(int)
    sol["assigned_start_hour"] = sol["assigned_start_hour"].astype(int)
    sol["L_slots"] = sol["L_slots"].astype(int)

    sol["start_slot"] = sol["assigned_start_hour"].map(HOUR2SLOT)
    sol["end_slot"] = sol["start_slot"] + sol["L_slots"]

    return sol


def read_room_data():
    rm = pd.read_excel(ROOMS_XLSX).copy()
    rm.columns = rm.columns.str.strip()

    rm = rm.rename(columns={
        "Id": "room_id",
        "Capacity": "cap",
        "Campus": "room_campus",
        "Specialist room type": "room_type",
    })

    rm["room_id"] = rm["room_id"].astype(str).str.strip()
    rm["cap"] = pd.to_numeric(rm["cap"], errors="coerce")
    rm["room_type"] = rm["room_type"].apply(norm_room_type)
    rm["room_campus"] = rm["room_campus"].fillna("").astype(str).str.strip()

    return rm


def read_event_data(events_xlsx):
    ev = pd.read_excel(events_xlsx).copy()
    ev.columns = ev.columns.str.strip()

    ev = ev.rename(columns={
        "Event ID": "event_id",
        "Event Size": "size",
        "WholeClass": "whole_class",
        "Expected Campus": "event_campus",
    })

    ev["event_id"] = ev["event_id"].astype(str).str.strip()
    ev["size"] = pd.to_numeric(ev["size"], errors="coerce").fillna(0).astype(int)
    ev["event_campus"] = ev["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()

    if "whole_class" in ev.columns:
        ev["whole_class"] = ev["whole_class"].astype(str).str.strip().str.upper()
    else:
        ev["whole_class"] = "FALSE"

    return ev


# Set different weights for wholeclass and subgroup for student clashes
def clash_weight(wc1, wc2):
    wc1 = str(wc1).strip().upper()
    wc2 = str(wc2).strip().upper()

    if wc1 == "TRUE" and wc2 == "TRUE":
        return 1.0
    elif wc1 == "TRUE" or wc2 == "TRUE":
        return 0.7
    else:
        return 0.3


def evaluate_student_clash(sol, ev, overlap_csv):
    whole_class_map = dict(
        zip(ev["event_id"].astype(str), ev["whole_class"].astype(str))
    )

    # Build event -> [(week, day, start_slot, end_slot)] dictionary
    event_schedule = {}
    for row in sol.itertuples(index=False):
        eid = row.event_id
        item = (row.week, row.assigned_day, row.start_slot, row.end_slot)
        if eid not in event_schedule:
            event_schedule[eid] = [item]
        else:
            event_schedule[eid].append(item)

    total_penalty = 0
    clash_count = 0
    detail_rows = []
    total_overlap_pairs = 0

    chunks = pd.read_csv(overlap_csv, chunksize=200000)

    for chunk in chunks:
        chunk["event1"] = chunk["event1"].astype(str).str.strip()
        chunk["event2"] = chunk["event2"].astype(str).str.strip()
        chunk["shared_students"] = pd.to_numeric(
            chunk["shared_students"], errors="coerce"
        ).fillna(0).astype(int)

        total_overlap_pairs += len(chunk)

        for row in chunk.itertuples(index=False):
            e1 = row.event1
            e2 = row.event2
            shared = row.shared_students

            if e1 not in event_schedule or e2 not in event_schedule:
                continue

            sched1 = event_schedule[e1]
            sched2 = event_schedule[e2]

            found_clash = False

            for wk1, day1, s1, e1_end in sched1:
                for wk2, day2, s2, e2_end in sched2:
                    if wk1 != wk2:
                        continue
                    if day1 != day2:
                        continue

                    if intervals_overlap(s1, e1_end, s2, e2_end):
                        clash_count += 1
                        w = clash_weight(
                            whole_class_map.get(e1, "FALSE"),
                            whole_class_map.get(e2, "FALSE")
                        )
                        total_penalty += shared * w

                        found_clash = True

                        if len(detail_rows) < 50000:
                            detail_rows.append([
                                e1, e2, shared, wk1, day1, s1, e1_end, s2, e2_end
                            ])
                        break
                if found_clash:
                    break

    if detail_rows:
        detail_df = pd.DataFrame(
            detail_rows,
            columns=[
                "event1", "event2", "shared_students",
                "week", "day",
                "start1", "end1",
                "start2", "end2"
            ]
        )
        detail_df.to_csv(OUTPUT_CLASH_DETAIL_CSV, index=False)

    return clash_count, total_penalty, total_overlap_pairs


def evaluate_after_5pm(sol, ev):
    whole_class_set = set(
        ev.loc[ev["whole_class"] == "TRUE", "event_id"].astype(str).tolist()
    )

    tmp = sol[sol["event_id"].isin(whole_class_set)].copy()
    tmp["end_hour"] = tmp["assigned_start_hour"] + tmp["L_slots"]

    # If end time > 17, it means part of it falls after 5pm
    bad = tmp[tmp["end_hour"] > 17].copy()

    penalty = len(bad)
    return len(bad), penalty


def evaluate_wednesday_afternoon_wholeclass(sol, ev):
    whole_class_set = set(
        ev.loc[ev["whole_class"] == "TRUE", "event_id"].astype(str).tolist()
    )

    tmp = sol[
        (sol["event_id"].isin(whole_class_set))
        & (sol["assigned_day"] == "Wednesday")
        ].copy()

    tmp["end_hour"] = tmp["assigned_start_hour"] + tmp["L_slots"]

    # If the course covers any time after 13:00 on Wednesday, it's a violation
    # i.e., [start, end) intersects with [13, +∞) => end_hour > 13
    bad = tmp[tmp["end_hour"] > 13].copy()

    penalty = len(bad)
    return len(bad), penalty


def evaluate_lunch_break_approximate(sol):
    # Approximate version:
    # If an event starts at 12pm or 1pm, count one lunch penalty
    bad = sol[sol["assigned_start_hour"].isin([12, 13])].copy()
    penalty = len(bad)
    return len(bad), penalty


def evaluate_same_room_across_weeks(sol):
    # For each event, check if multiple different rooms are used across weeks
    # Empty rooms are not counted
    tmp = sol.copy()
    tmp["room_id"] = tmp["room_id"].fillna("").astype(str).str.strip()
    tmp = tmp[tmp["room_id"] != ""]

    count_bad_events = 0
    penalty = 0

    for eid, g in tmp.groupby("event_id", sort=False):
        rooms = set(g["room_id"].tolist())
        if len(rooms) > 1:
            count_bad_events += 1
            penalty += (len(rooms) - 1)

    return count_bad_events, penalty


def evaluate_room_capacity(sol, rm):
    tmp = sol.copy()

    # Merge room capacity
    tmp = tmp.merge(
        rm[["room_id", "cap"]],
        on="room_id",
        how="left"
    )

    tmp["size"] = pd.to_numeric(tmp["size"], errors="coerce")
    tmp["cap"] = pd.to_numeric(tmp["cap"], errors="coerce")

    # Only look at those that actually have a room assigned
    bad = tmp[
        tmp["room_id"].notna()
        & (tmp["room_id"].astype(str).str.strip() != "")
        & tmp["cap"].notna()
        & tmp["size"].notna()
        & (tmp["size"] > tmp["cap"])
        ].copy()

    # penalty = sum of excess people
    bad["overflow"] = bad["size"] - bad["cap"]

    count_bad = len(bad)
    penalty = bad["overflow"].sum()

    return count_bad, penalty


def evaluate_expected_campus_mismatch(sol, ev):
    tmp = sol.copy()

    # Merge event expected campus
    tmp = tmp.merge(
        ev[["event_id", "event_campus"]],
        on="event_id",
        how="left"
    )

    # Only look at those that actually have a room assigned
    tmp = tmp[
        tmp["room_id"].notna()
        & (tmp["room_id"].astype(str).str.strip() != "")
        ].copy()

    # step2 results already have room_campus, no need to merge room table again
    tmp["event_campus"] = tmp["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()
    tmp["room_campus"] = tmp["room_campus"].fillna("").astype(str).str.strip()

    # Only judge mismatch for events that require a room
    bad = tmp[
        (tmp["event_campus"] != NO_ROOM_FLAG)
        & (tmp["event_campus"] != tmp["room_campus"])
        ].copy()

    count_bad = len(bad)
    penalty = count_bad

    return count_bad, penalty


def percentage(part, whole):
    if whole == 0:
        return 0.0
    return 100.0 * part / whole


def calculate_utilisation_metrics(sol, scenario):
    # Only look at occurrences that actually have a room assigned
    room_only = sol[
        sol["room_id"].notna() & (sol["room_id"].astype(str).str.strip() != "")
        ].copy()

    # Total number of rooms
    total_rooms = room_only["room_id"].nunique()

    # How many different rooms were used in each time slot
    ts_room_usage = (
        room_only.groupby(["assigned_day", "assigned_start_hour"])["room_id"]
        .nunique()
        .reset_index(name="rooms_used")
    )

    # Peak timeslot: still look at total number of events in that time slot
    ts_event_usage = (
        sol.groupby(["assigned_day", "assigned_start_hour"])
        .size()
        .reset_index(name="event_count")
    )
    peak = ts_event_usage.loc[ts_event_usage["event_count"].idxmax()]

    # Timeslot utilisation (time perspective)
    # = proportion of rooms occupied in each time slot, averaged over all time slots
    if total_rooms > 0 and len(ts_room_usage) > 0:
        ts_room_usage["utilisation"] = ts_room_usage["rooms_used"] / total_rooms
        timeslot_utilisation = ts_room_usage["utilisation"].mean()
    else:
        timeslot_utilisation = 0.0

    # Room utilisation (space perspective)
    # = occupied (room, timeslot) / total (room, timeslot)
    if scenario == "no_friday_afternoon":
        total_timeslots = 4 * 9 + 3  # 39
    else:
        total_timeslots = 5 * 9  # 45

    total_room_timeslots = total_rooms * total_timeslots
    used_room_timeslots = ts_room_usage["rooms_used"].sum() if len(ts_room_usage) > 0 else 0

    room_utilisation = (
        used_room_timeslots / total_room_timeslots
        if total_room_timeslots > 0 else 0.0
    )

    # Average number of events per used time slot
    avg_events_per_used_timeslot = (
        ts_event_usage["event_count"].mean()
        if len(ts_event_usage) > 0 else 0.0
    )

    return {
        "peak_day": peak["assigned_day"],
        "peak_hour": int(peak["assigned_start_hour"]),
        "peak_events": int(peak["event_count"]),
        "timeslot_utilisation": round(float(timeslot_utilisation), 2),
        "avg_events_per_used_timeslot": round(float(avg_events_per_used_timeslot), 2),
        "avg_room_utilisation": round(float(room_utilisation), 2),
    }


def main(step2_csv="step2_solution_with_rooms_by_week_baseline.csv",
         events_xlsx="events.xlsx",
         overlap_csv="event_overlap.csv",
         scenario="baseline"):
    sol = read_and_clean_step2_timetable(step2_csv)
    rm = read_room_data()
    ev = read_event_data(events_xlsx)

    total_occurrences = len(sol)

    total_room_occurrences = len(
        sol[
            sol["room_id"].notna()
            & (sol["room_id"].astype(str).str.strip() != "")
            ]
    )

    total_events = sol["event_id"].nunique()

    whole_class_set = set(
        ev.loc[ev["whole_class"] == "TRUE", "event_id"].astype(str)
    )
    total_wholeclass_occurrences = len(
        sol[sol["event_id"].isin(whole_class_set)]
    )

    tmp_campus = sol.merge(
        ev[["event_id", "event_campus"]],
        on="event_id",
        how="left"
    ).copy()

    campus_applicable_total = len(
        tmp_campus[
            tmp_campus["room_id"].notna()
            & (tmp_campus["room_id"].astype(str).str.strip() != "")
            & (tmp_campus["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip() != NO_ROOM_FLAG)
            ]
    )

    # 1. student clash
    clash_count, clash_penalty, total_overlap_pairs = evaluate_student_clash(sol, ev, overlap_csv)

    # 2a. after 5pm
    evening_count, evening_penalty = evaluate_after_5pm(sol, ev)
    # 2b. Wednesday afternoon whole-class
    wed_count, wed_penalty = evaluate_wednesday_afternoon_wholeclass(sol, ev)

    # 3. lunch break (approximate)
    lunch_count, lunch_penalty = evaluate_lunch_break_approximate(sol)

    # 4. same room across weeks
    same_room_bad_events, same_room_penalty = evaluate_same_room_across_weeks(sol)

    # 5. room capacity violation
    cap_bad_count, cap_penalty = evaluate_room_capacity(sol, rm)

    # 6. campus mismatch
    campus_bad_count, campus_penalty = evaluate_expected_campus_mismatch(sol, ev)

    print("=== Soft Constraint Evaluation Results ===")
    print()

    print("[1] Student Clash")
    print("Number of conflicting event pairs:", clash_count)
    print("Proportion of all overlap pairs: {:.2f}%".format(percentage(clash_count, total_overlap_pairs)))
    print("Total clash penalty: {:.2f}".format(float(clash_penalty)))
    print()

    print("[2a] Core Teaching After 5pm")
    print("Number of violations:", evening_count)
    print("Proportion of whole-class occurrences: {:.2f}%".format(
        percentage(evening_count, total_wholeclass_occurrences)))
    print("penalty: {:.2f}".format(float(evening_penalty)))
    print()

    print("[2b] Wednesday Afternoon Whole-Class")
    print("Number of violations:", wed_count)
    print("Proportion of whole-class occurrences: {:.2f}%".format(percentage(wed_count, total_wholeclass_occurrences)))
    print("penalty: {:.2f}".format(float(wed_penalty)))
    print()

    print("[3] Lunch Break (Approximate Version)")
    print("Number of events starting at 12pm or 1pm:", lunch_count)
    print("Proportion of all occurrences: {:.2f}%".format(percentage(lunch_count, total_occurrences)))
    print("penalty: {:.2f}".format(float(lunch_penalty)))
    print()

    print("[4] Same Room Across Weeks")
    print("Number of events using multiple different rooms:", same_room_bad_events)
    print("Proportion of all events: {:.2f}%".format(percentage(same_room_bad_events, total_events)))
    print("penalty: {:.2f}".format(float(same_room_penalty)))
    print()

    print("[5] Room Capacity Violation")
    print("Number of occurrences exceeding capacity:", cap_bad_count)
    print("Proportion of room-assigned occurrences: {:.2f}%".format(percentage(cap_bad_count, total_room_occurrences)))
    print("penalty (sum of excess people): {:.2f}".format(float(cap_penalty)))
    print()

    print("[6] Expected Campus Mismatch")
    print("Number of occurrences not matching Expected Campus:", campus_bad_count)
    print("Proportion of applicable occurrences: {:.2f}%".format(percentage(campus_bad_count, campus_applicable_total)))
    print("penalty: {:.2f}".format(float(campus_penalty)))
    print()

    print("Student clash details file:", OUTPUT_CLASH_DETAIL_CSV)

    # ===== objective =====
    w_clash = 250
    w_capacity = 30
    w_evening = 40
    w_wed = 30
    w_lunch = 20
    w_campus = 10
    w_same_room = 20

    clash_contrib = w_clash * clash_penalty
    evening_contrib = w_evening * evening_penalty
    wed_contrib = w_wed * wed_penalty
    lunch_contrib = w_lunch * lunch_penalty
    same_room_contrib = w_same_room * same_room_penalty
    capacity_contrib = w_capacity * cap_penalty
    campus_contrib = w_campus * campus_penalty

    objective = (
            clash_contrib
            + evening_contrib
            + wed_contrib
            + lunch_contrib
            + same_room_contrib
            + capacity_contrib
            + campus_contrib
    )

    print()
    print("=== Objective Score ===")
    print("Total objective: {:.2f}".format(float(objective)))
    print()

    print("=== Objective Contribution Breakdown ===")
    print("Student Clash contribution: {:.2f} ({:.2f}%)".format(
        float(clash_contrib), percentage(clash_contrib, objective)
    ))
    print("After 5pm contribution: {:.2f} ({:.2f}%)".format(
        float(evening_contrib), percentage(evening_contrib, objective)
    ))
    print("Wednesday contribution: {:.2f} ({:.2f}%)".format(
        float(wed_contrib), percentage(wed_contrib, objective)
    ))
    print("Lunch contribution: {:.2f} ({:.2f}%)".format(
        float(lunch_contrib), percentage(lunch_contrib, objective)
    ))
    print("Same Room contribution: {:.2f} ({:.2f}%)".format(
        float(same_room_contrib), percentage(same_room_contrib, objective)
    ))
    print("Capacity contribution: {:.2f} ({:.2f}%)".format(
        float(capacity_contrib), percentage(capacity_contrib, objective)
    ))
    print("Campus contribution: {:.2f} ({:.2f}%)".format(
        float(campus_contrib), percentage(campus_contrib, objective)
    ))

    util_summary = calculate_utilisation_metrics(sol, scenario)

    print()
    print("=" * 60)
    print("UTILISATION ANALYSIS")
    print("=" * 60)

    print(
        f"Peak timeslot: {util_summary['peak_day']} at {util_summary['peak_hour']}:00 "
        f"({util_summary['peak_events']} events)"
    )

    print("Timeslot utilisation: {:.2f}%".format(util_summary["timeslot_utilisation"] * 100))
    print("Average events per used timeslot: {:.2f}".format(util_summary["avg_events_per_used_timeslot"]))
    print("Average room utilisation: {:.2f}%".format(util_summary["avg_room_utilisation"] * 100))

    return {
        "objective": round(float(objective), 2),

        # ===== counts =====
        "clash_count": clash_count,
        "evening_count": evening_count,
        "wed_count": wed_count,
        "lunch_count": lunch_count,
        "same_room_bad_events": same_room_bad_events,
        "cap_bad_count": cap_bad_count,
        "campus_bad_count": campus_bad_count,

        # ===== percentages (all two decimal places) =====
        "clash_pct": round(percentage(clash_count, total_overlap_pairs), 2),
        "evening_pct": round(percentage(evening_count, total_wholeclass_occurrences), 2),
        "wed_pct": round(percentage(wed_count, total_wholeclass_occurrences), 2),
        "lunch_pct": round(percentage(lunch_count, total_occurrences), 2),
        "same_room_pct": round(percentage(same_room_bad_events, total_events), 2),
        "cap_pct": round(percentage(cap_bad_count, total_room_occurrences), 2),
        "campus_pct": round(percentage(campus_bad_count, campus_applicable_total), 2),

        # ===== utilisation =====
        "peak_day": util_summary["peak_day"],
        "peak_hour": util_summary["peak_hour"],
        "peak_events": util_summary["peak_events"],

        "timeslot_utilisation": util_summary["timeslot_utilisation"],
        "avg_events_per_used_timeslot": util_summary["avg_events_per_used_timeslot"],
        "avg_room_utilisation": util_summary["avg_room_utilisation"],
    }


if __name__ == "__main__":
    main()