# run_time_scenarios.py

from step1_hard_feasibility import main as run_step1
from step2_assign_rooms_by_week import main as run_step2
from step3_soft_evaluation import main as run_step3

SCENARIOS = [
    "baseline",
    "mon_fri_9_5",
    "no_friday_afternoon",
]

def run_one_scenario(scenario: str):
    print("\n" + "=" * 80)
    print(f"Running scenario: {scenario}")
    print("=" * 80)

    step1_file = f"step1_solution_{scenario}.csv"
    step2_file = f"step2_solution_with_rooms_by_week_{scenario}.csv"
    fail_file = f"step2_failed_occurrences_{scenario}.csv"

    # Step 1
    # 选择数据源
    if scenario == "mon_fri_9_5":
        events_file = "events_split.xlsx"
    else:
        events_file = "events.xlsx"
        
    print(f"\n[Step 1] {scenario}")
    run_step1(
        time_limit_sec=1800,
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
    run_step3(step2_csv=step2_file)


def main():
    for scenario in SCENARIOS:
        try:
            run_one_scenario(scenario)
        except Exception as e:
            print(f"\nScenario {scenario} failed.")
            print("Reason:", e)


if __name__ == "__main__":
    main()