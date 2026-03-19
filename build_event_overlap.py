# build_event_overlap.py

import pandas as pd
from itertools import combinations
from collections import Counter

INPUT_FILE = "student.xlsx"
OUTPUT_FILE = "event_overlap.csv"

# 读取Excel
df = pd.read_excel(INPUT_FILE)

# 去掉列名可能的空格
df.columns = df.columns.str.strip()

# 只保留需要的列
df = df[["AnonID", "Event ID"]]

# 按学生分组
grouped = df.groupby("AnonID")["Event ID"].apply(list)

pair_counter = Counter()

for events in grouped:
    events = list(set(events))  # 去重
    if len(events) < 2:
        continue

    for e1, e2 in combinations(sorted(events), 2):
        pair_counter[(e1, e2)] += 1

# 转成DataFrame
pairs = pd.DataFrame(
    [(e1, e2, c) for (e1, e2), c in pair_counter.items()],
    columns=["event1", "event2", "shared_students"]
)


pairs.to_csv(OUTPUT_FILE, index=False)

print("Done")
print("Number of pairs:", len(pairs))