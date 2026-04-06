import pandas as pd
from itertools import combinations
from collections import Counter

def main(input_file="student.xlsx", output_file="event_overlap.csv"):
    df = pd.read_excel(input_file)
    df.columns = df.columns.str.strip()

    df = df[["AnonID", "Event ID"]].copy()
    df["AnonID"] = df["AnonID"].astype(str).str.strip()
    df["Event ID"] = df["Event ID"].astype(str).str.strip()

    grouped = df.groupby("AnonID")["Event ID"].apply(list)

    pair_counter = Counter()

    for events in grouped:
        events = list(set(events))
        if len(events) < 2:
            continue

        for e1, e2 in combinations(sorted(events), 2):
            pair_counter[(e1, e2)] += 1

    pairs = pd.DataFrame(
        [(e1, e2, c) for (e1, e2), c in pair_counter.items()],
        columns=["event1", "event2", "shared_students"]
    )

    pairs.to_csv(output_file, index=False)

    print("Done")
    print("Input:", input_file)
    print("Output:", output_file)
    print("Number of pairs:", len(pairs))

if __name__ == "__main__":
    main()