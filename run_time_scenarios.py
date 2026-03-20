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
            "clash_count",
            "evening_count",
            "wed_count",
            "lunch_count",
            "cap_bad_count",
            "campus_bad_count",
            "peak_day",
            "peak_hour",
            "peak_events",
            "avg_room_utilisation",
        ]]

        print("\n" + "=" * 100)
        print("SCENARIO SUMMARY")
        print("=" * 100)
        print(result_df.to_string(index=False))

        result_df.to_csv("scenario_summary.csv", index=False)
        print("\nSaved summary file: scenario_summary.csv")