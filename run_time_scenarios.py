# run_time_scenarios.py

from step1_hard_feasibility import main as run_step1
from step2_assign_rooms_by_week import main as run_step2
from step3_soft_evaluation import main as run_step3

from split_events import main as run_split_events
from split_student_events import main as run_split_student_events
from build_event_overlap import main as build_event_overlap

SCENARIOS = [
    "baseline",
    "mon_fri_9_5",
    "no_friday_afternoon",
]

def prepare_all_inputs():
    print("\n" + "=" * 80)
    print("Preparing all derived input files...")
    print("=" * 80)

    # 1. split events for mon_fri_9_5
    print("\n[Prepare 1] split events")
    run_split_events()

    # 2. split student-event records accordingly
    print("\n[Prepare 2] split student-event data")
    run_split_student_events()

    # 3. build original overlap
    print("\n[Prepare 3] build original overlap")
    build_event_overlap("student.xlsx", "event_overlap.csv")

    # 4. build split overlap
    print("\n[Prepare 4] build split overlap")
    build_event_overlap("student_split.xlsx", "event_overlap_split.csv")

    print("\nAll derived input files are ready.")

def run_one_scenario(scenario: str):
    print("\n" + "=" * 80)
    print(f"Running scenario: {scenario}")
    print("=" * 80)

    step1_file = f"step1_solution_{scenario}.csv"
    step2_file = f"step2_solution_with_rooms_by_week_{scenario}.csv"
    fail_file = f"step2_failed_occurrences_{scenario}.csv"

    # choose data files by scenario
    if scenario == "mon_fri_9_5":
        events_file = "events_split.xlsx"
        overlap_file = "event_overlap_split.csv"
    else:
        events_file = "events.xlsx"
        overlap_file = "event_overlap.csv"

    # Step 1
    print(f"\n[Step 1] {scenario}")
    run_step1(
        time_limit_sec=3600,
        N_EVENTS=None,
        stop_after_first_solution=True,
        scenario=scenario,
        events_xlsx=events_file
    )

    # Step 2
    print(f"\n[Step 2] {scenario}")
    run_step2(
        step1_sol=step1_file,
        out_csv=step2_file,
        fail_csv=fail_file
    )

    # Step 3
    print(f"\n[Step 3] {scenario}")
    summary = run_step3(
        step2_csv=step2_file,
        events_xlsx=events_file,
        overlap_csv=overlap_file,
        scenario=scenario
    )

    return summary

def main():
    all_results = []

    try:
        prepare_all_inputs()
    except Exception as e:
        print("\nPreprocessing failed.")
        print("Reason:", e)
        return

    for scenario in SCENARIOS:
        try:
            summary = run_one_scenario(scenario)
            if summary is not None:
                summary["scenario"] = scenario
                all_results.append(summary)
        except Exception as e:
            print(f"\nScenario {scenario} failed.")
            print("Reason:", e)

    if all_results:
        import pandas as pd

        result_df = pd.DataFrame(all_results)[[
            "scenario",
            "objective",

            # ===== counts =====
            "clash_count",
            "evening_count",
            "wed_count",
            "lunch_count",
            "same_room_bad_events",
            "cap_bad_count",
            "campus_bad_count",

            # ===== percentages =====
            "clash_pct",
            "evening_pct",
            "wed_pct",
            "lunch_pct",
            "same_room_pct",
            "cap_pct",
            "campus_pct",

            # ===== utilisation =====
            "timeslot_utilisation",
            "avg_events_per_used_timeslot",
            "avg_room_utilisation",

            # ===== peak =====
            "peak_day",
            "peak_hour",
            "peak_events",
        ]]
        
        
        # ===== format columns for display / csv =====
        pct_cols = [
            "clash_pct",
            "evening_pct",
            "wed_pct",
            "lunch_pct",
            "same_room_pct",
            "cap_pct",
            "campus_pct",
        ]

        util_pct_cols = [
            "timeslot_utilisation",
            "avg_room_utilisation",
        ]

        # 先复制一份，避免把原数值表改坏
        display_df = result_df.copy()

        # objective 保留两位小数
        display_df["objective"] = display_df["objective"].map(lambda x: f"{x:.2f}")

        # 普通百分比列：本来就是 1.38 / 22.66 这种，直接加 %
        for col in pct_cols:
            display_df[col] = display_df[col].map(lambda x: f"{x:.2f}%")

        # utilisation 列：本来是 1.0 / 0.55 这种，要先乘100再加 %
        for col in util_pct_cols:
            display_df[col] = display_df[col].map(lambda x: f"{x * 100:.2f}%")

        # 其他保留两位小数
        display_df["avg_events_per_used_timeslot"] = display_df["avg_events_per_used_timeslot"].map(lambda x: f"{x:.2f}")

        print("\n" + "=" * 120)
        print("SCENARIO SUMMARY")
        print("=" * 120)
        print(display_df.to_string(index=False))

        display_df.to_csv("scenario_summary.csv", index=False)
        print("\nSaved summary file: scenario_summary.csv")
        
if __name__ == "__main__":
    main()