import pandas as pd

STUDENT_FILE = "student.xlsx"
SPLIT_EVENTS_FILE = "events_split.xlsx"
OUTPUT_FILE = "student_split.xlsx"

def main():
    stu = pd.read_excel(STUDENT_FILE).copy()
    stu.columns = stu.columns.str.strip()

    ev_split = pd.read_excel(SPLIT_EVENTS_FILE).copy()
    ev_split.columns = ev_split.columns.str.strip()

    # 建一个映射：原 Event ID -> [原ID_A, 原ID_B]
    split_map = {}
    for eid in ev_split["Event ID"].astype(str).str.strip():
        if eid.endswith("_A") or eid.endswith("_B"):
            base = eid[:-2]
            split_map.setdefault(base, []).append(eid)

    new_rows = []

    for _, row in stu.iterrows():
        eid = str(row["Event ID"]).strip()

        if eid in split_map:
            # 原来选这门课的学生，现在要同时选 A 和 B
            for new_eid in split_map[eid]:
                rr = row.copy()
                rr["Event ID"] = new_eid
                new_rows.append(rr)
        else:
            new_rows.append(row)

    out = pd.DataFrame(new_rows)
    out.to_excel(OUTPUT_FILE, index=False)

    print(f"{OUTPUT_FILE} generated")
    print("original rows:", len(stu))
    print("new rows:", len(out))

if __name__ == "__main__":
    main()