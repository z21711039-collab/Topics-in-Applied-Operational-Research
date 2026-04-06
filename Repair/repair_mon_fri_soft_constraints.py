from __future__ import annotations

import os
import shutil
import pandas as pd

from step2_assign_rooms_by_week import main as run_step2
from step3_soft_evaluation import main as run_step3


STEP2_ORIG = "step2_solution_with_rooms_by_week_mon_fri_9_5.csv"
EVENTS_XLSX = "events_split.xlsx"
OVERLAP_CSV = "event_overlap_split.csv"
STEP1_OUT = "step1_solution_mon_fri_9_5_repaired.csv"
STEP2_OUT = "step2_solution_with_rooms_by_week_mon_fri_9_5_repaired.csv"
FAIL_OUT = "step2_failed_occurrences_mon_fri_9_5_repaired.csv"

MAX_SWAPS = 1200
ALLOWED_MOVE_HOURS = [9, 10, 11, 14, 15, 16]
ALLOWED_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
W_AFTER5 = 40
W_WED = 30
W_LUNCH = 20
MAX_AFTER5_INCREASE = 1
MAX_WED_INCREASE = 2
MAX_OBJECTIVE_INCREASE_RATIO = 0.01
MIN_LUNCH_REDUCTION = 1000


def event_flags(day: str, start_hour: int, L_slots: int, whole_class: bool) -> tuple[int, int, int]:
    end_hour = int(start_hour) + int(L_slots)
    after5 = int(bool(whole_class and end_hour > 17))
    wed = int(bool(whole_class and str(day) == "Wednesday" and end_hour > 13))
    lunch = int(bool(int(start_hour) in (12, 13)))
    return after5, wed, lunch


def local_delta(old_flags: tuple[int, int, int], new_flags: tuple[int, int, int]) -> tuple[int, int, int, int]:
    after5_delta = new_flags[0] - old_flags[0]
    wed_delta = new_flags[1] - old_flags[1]
    lunch_delta = new_flags[2] - old_flags[2]
    weighted_delta = (
        W_AFTER5 * after5_delta
        + W_WED * wed_delta
        + W_LUNCH * lunch_delta
    )
    return weighted_delta, after5_delta, wed_delta, lunch_delta


def main() -> None:
    step2_in = STEP2_OUT if os.path.exists(STEP2_OUT) else STEP2_ORIG
    baseline_summary = run_step3(
        step2_csv=step2_in,
        events_xlsx=EVENTS_XLSX,
        overlap_csv=OVERLAP_CSV,
        scenario="mon_fri_9_5_repaired_current",
    )
    baseline_objective = float(baseline_summary["objective"])
    baseline_lunch = int(baseline_summary["lunch_count"])

    sol = pd.read_csv(step2_in).copy()
    ev = pd.read_excel(EVENTS_XLSX).copy()
    ev.columns = ev.columns.str.strip()
    ev = ev.rename(columns={
        "Event ID": "event_id",
        "WholeClass": "whole_class",
    })
    ev["event_id"] = ev["event_id"].astype(str).str.strip()
    ev["whole_class"] = ev["whole_class"].astype(str).str.strip().str.upper()
    whole_class_map = dict(zip(ev["event_id"], ev["whole_class"] == "TRUE"))

    rm = pd.read_excel("room.xlsx").copy()
    rm.columns = rm.columns.str.strip()
    rm = rm.rename(columns={"Specialist room type": "room_type"})
    rm["room_type"] = rm["room_type"].astype(str).str.strip()
    type_capacity = rm.groupby("room_type").size().to_dict()

    step1_like = (
        sol.groupby("event_id", sort=False)
        .agg({
            "weeks": "first",
            "req_room_type": "first",
            "size": "first",
            "L_slots": "first",
            "assigned_day": "first",
            "assigned_start_hour": "first",
        })
        .reset_index()
    )
    step1_like["event_id"] = step1_like["event_id"].astype(str)
    step1_like["whole_class"] = step1_like["event_id"].map(whole_class_map).fillna(False)
    step1_like["weeks_key"] = (
        step1_like["weeks"]
        .fillna("")
        .astype(str)
        .str.replace(" ", "", regex=False)
    )
    step1_like["weeks_list"] = step1_like["weeks_key"].apply(
        lambda s: [int(tok) for tok in str(s).split(",") if tok.strip().isdigit()]
    )
    flags = step1_like.apply(
        lambda r: event_flags(
            r["assigned_day"],
            int(r["assigned_start_hour"]),
            int(r["L_slots"]),
            bool(r["whole_class"]),
        ),
        axis=1,
    )
    step1_like[["p2a", "p2b", "p3"]] = pd.DataFrame(flags.tolist(), index=step1_like.index)

    group_to_indices = {}
    for idx, row in step1_like.iterrows():
        key = (
            str(row["req_room_type"]).strip(),
            int(row["L_slots"]),
        )
        group_to_indices.setdefault(key, []).append(idx)

    type_slot_loads = {}

    def add_event_load(row, day: str, start_hour: int, delta: int) -> None:
        room_type = str(row["req_room_type"]).strip()
        L_slots = int(row["L_slots"])
        for wk in row["weeks_list"]:
            for slot in range(int(start_hour), int(start_hour) + L_slots):
                key = (room_type, int(wk), str(day), int(slot))
                type_slot_loads[key] = type_slot_loads.get(key, 0) + delta
                if type_slot_loads[key] == 0:
                    type_slot_loads.pop(key, None)

    def can_place(row, day: str, start_hour: int) -> bool:
        room_type = str(row["req_room_type"]).strip()
        cap = int(type_capacity.get(room_type, 0))
        if cap <= 0:
            return False
        L_slots = int(row["L_slots"])
        for wk in row["weeks_list"]:
            for slot in range(int(start_hour), int(start_hour) + L_slots):
                key = (room_type, int(wk), str(day), int(slot))
                if type_slot_loads.get(key, 0) + 1 > cap:
                    return False
        return True

    for _, row in step1_like.iterrows():
        add_event_load(row, str(row["assigned_day"]), int(row["assigned_start_hour"]), 1)

    template_loads = (
        step1_like.groupby(["assigned_day", "assigned_start_hour"])
        .size()
        .to_dict()
    )

    def template_load(day: str, hour: int) -> int:
        return int(template_loads.get((str(day), int(hour)), 0))

    swap_count = 0
    move_count = 0
    improved = True

    while improved and swap_count < MAX_SWAPS:
        improved = False
        bad_indices = step1_like.index[step1_like["p3"] > 0].tolist()
        bad_indices.sort(
            key=lambda i: (
                -int(step1_like.at[i, "p3"]),
                -int(step1_like.at[i, "p2b"]),
                -int(step1_like.at[i, "p2a"]),
                -len(str(step1_like.at[i, "weeks_key"]).split(",")),
                str(step1_like.at[i, "event_id"]),
            )
        )

        for idx in bad_indices:
            row = step1_like.loc[idx]
            key = (
                str(row["req_room_type"]).strip(),
                int(row["L_slots"]),
            )
            candidates = group_to_indices.get(key, [])
            old_day = str(row["assigned_day"])
            old_hour = int(row["assigned_start_hour"])
            add_event_load(row, old_day, old_hour, -1)

            # 1) Try one-sided move first: lunch must decrease and 2a/2b must not worsen.
            best_move = None
            best_move_score = (0, 0, 0)
            old_flags = (int(row["p2a"]), int(row["p2b"]), int(row["p3"]))
            for day in ALLOWED_DAYS:
                for hour in ALLOWED_MOVE_HOURS:
                    if not can_place(row, day, int(hour)):
                        continue
                    new_flags = event_flags(
                        day,
                        int(hour),
                        int(row["L_slots"]),
                        bool(row["whole_class"]),
                    )
                    weighted_delta, after5_delta, wed_delta, lunch_delta = local_delta(old_flags, new_flags)
                    if lunch_delta >= 0:
                        continue
                    if after5_delta > MAX_AFTER5_INCREASE or wed_delta > MAX_WED_INCREASE:
                        continue
                    if weighted_delta > 0:
                        continue
                    score = (
                        -weighted_delta,
                        -lunch_delta,
                        template_load(old_day, old_hour) - template_load(day, int(hour)),
                        -(after5_delta + wed_delta),
                    )
                    if score > best_move_score:
                        best_move_score = score
                        best_move = (day, hour, new_flags)

            if best_move is not None:
                new_day, new_hour, new_flags = best_move
                template_loads[(old_day, old_hour)] = max(template_load(old_day, old_hour) - 1, 0)
                template_loads[(new_day, int(new_hour))] = template_load(new_day, int(new_hour)) + 1
                step1_like.at[idx, "assigned_day"] = new_day
                step1_like.at[idx, "assigned_start_hour"] = int(new_hour)
                step1_like.loc[idx, ["p2a", "p2b", "p3"]] = list(new_flags)
                add_event_load(step1_like.loc[idx], new_day, int(new_hour), 1)
                move_count += 1
                swap_count += 1
                improved = True
                if swap_count >= MAX_SWAPS:
                    break
                continue

            best_idx = None
            best_gain = (0, 0, 0, 0)

            for j in candidates:
                if j == idx:
                    continue

                row2 = step1_like.loc[j]
                row2_day = str(row2["assigned_day"])
                row2_hour = int(row2["assigned_start_hour"])
                add_event_load(row2, row2_day, row2_hour, -1)

                can_swap = can_place(row, row2_day, row2_hour) and can_place(row2, old_day, old_hour)
                if not can_swap:
                    add_event_load(row2, row2_day, row2_hour, 1)
                    continue

                p1_old = (int(row["p2a"]), int(row["p2b"]), int(row["p3"]))
                p2_old = (int(row2["p2a"]), int(row2["p2b"]), int(row2["p3"]))
                p1_new = event_flags(
                    row2["assigned_day"],
                    int(row2["assigned_start_hour"]),
                    int(row["L_slots"]),
                    bool(row["whole_class"]),
                )
                p2_new = event_flags(
                    row["assigned_day"],
                    int(row["assigned_start_hour"]),
                    int(row2["L_slots"]),
                    bool(row2["whole_class"]),
                )

                old_after5 = p1_old[0] + p2_old[0]
                old_wed = p1_old[1] + p2_old[1]
                old_lunch = p1_old[2] + p2_old[2]
                new_after5 = p1_new[0] + p2_new[0]
                new_wed = p1_new[1] + p2_new[1]
                new_lunch = p1_new[2] + p2_new[2]

                pair_old = (old_after5, old_wed, old_lunch)
                pair_new = (new_after5, new_wed, new_lunch)
                weighted_delta, after5_delta, wed_delta, lunch_delta = local_delta(pair_old, pair_new)
                if lunch_delta >= 0:
                    continue
                if after5_delta > MAX_AFTER5_INCREASE or wed_delta > MAX_WED_INCREASE:
                    continue
                if weighted_delta > 0:
                    continue

                gain = (
                    -weighted_delta,
                    -lunch_delta,
                    template_load(old_day, old_hour) + template_load(row2_day, row2_hour),
                    -(after5_delta + wed_delta),
                )
                if gain > best_gain:
                    best_gain = gain
                    best_idx = j

                add_event_load(row2, row2_day, row2_hour, 1)

            if best_idx is None:
                add_event_load(row, old_day, old_hour, 1)
                continue

            day_i = step1_like.at[idx, "assigned_day"]
            hour_i = step1_like.at[idx, "assigned_start_hour"]
            day_j = step1_like.at[best_idx, "assigned_day"]
            hour_j = step1_like.at[best_idx, "assigned_start_hour"]
            row2 = step1_like.loc[best_idx]
            add_event_load(row2, day_j, int(hour_j), -1)
            template_loads[(day_i, int(hour_i))] = template_load(day_i, int(hour_i))
            template_loads[(day_j, int(hour_j))] = template_load(day_j, int(hour_j))

            step1_like.at[idx, "assigned_day"] = day_j
            step1_like.at[idx, "assigned_start_hour"] = hour_j
            step1_like.at[best_idx, "assigned_day"] = day_i
            step1_like.at[best_idx, "assigned_start_hour"] = hour_i

            new_flags_i = event_flags(
                step1_like.at[idx, "assigned_day"],
                int(step1_like.at[idx, "assigned_start_hour"]),
                int(step1_like.at[idx, "L_slots"]),
                bool(step1_like.at[idx, "whole_class"]),
            )
            new_flags_j = event_flags(
                step1_like.at[best_idx, "assigned_day"],
                int(step1_like.at[best_idx, "assigned_start_hour"]),
                int(step1_like.at[best_idx, "L_slots"]),
                bool(step1_like.at[best_idx, "whole_class"]),
            )
            step1_like.loc[idx, ["p2a", "p2b", "p3"]] = list(new_flags_i)
            step1_like.loc[best_idx, ["p2a", "p2b", "p3"]] = list(new_flags_j)
            add_event_load(step1_like.loc[idx], day_j, int(hour_j), 1)
            add_event_load(step1_like.loc[best_idx], day_i, int(hour_i), 1)
            template_loads[(day_j, int(hour_j))] = template_load(day_j, int(hour_j)) + 1
            template_loads[(day_i, int(hour_i))] = template_load(day_i, int(hour_i)) + 1

            swap_count += 1
            improved = True
            if swap_count >= MAX_SWAPS:
                break

        if not improved:
            break

    out = step1_like[
        [
            "event_id",
            "weeks",
            "req_room_type",
            "size",
            "L_slots",
            "assigned_day",
            "assigned_start_hour",
        ]
    ].copy()
    out["room_id"] = ""
    out["room_campus"] = ""
    out.to_csv(STEP1_OUT, index=False)

    print(f"Repair input: {step2_in}")
    print(f"Applied moves: {move_count}")
    print(f"Applied swaps: {swap_count}")
    print(f"Wrote repaired step1-like timetable to: {STEP1_OUT}")

    run_step2(
        step1_sol=STEP1_OUT,
        out_csv=STEP2_OUT,
        fail_csv=FAIL_OUT,
        events_xlsx=EVENTS_XLSX,
    )

    summary = run_step3(
        step2_csv=STEP2_OUT,
        events_xlsx=EVENTS_XLSX,
        overlap_csv=OVERLAP_CSV,
        scenario="mon_fri_9_5_repaired_swap",
    )
    objective_ok = float(summary["objective"]) <= baseline_objective * (1.0 + MAX_OBJECTIVE_INCREASE_RATIO)
    lunch_ok = int(summary["lunch_count"]) <= baseline_lunch - MIN_LUNCH_REDUCTION
    if objective_ok and lunch_ok:
        print("Repair summary:", summary)
        print("Accepted repaired timetable.")
        return

    print("Repair summary:", summary)
    print("Repair rejected; reverting to previous repaired timetable.")
    shutil.copyfile("step1_solution_mon_fri_9_5_repaired.bak.csv", STEP1_OUT)
    shutil.copyfile("step2_solution_with_rooms_by_week_mon_fri_9_5_repaired.bak.csv", STEP2_OUT)


if __name__ == "__main__":
    main()
