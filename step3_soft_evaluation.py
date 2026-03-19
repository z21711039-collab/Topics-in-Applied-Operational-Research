# step3_soft_evaluation.py
# 评估当前课表的软约束表现
# 包含：
# 1. student clash
# 2. after 5pm
# 3. lunch break（近似版：12点/13点开始就记惩罚）
# 4. same room across weeks
# 5. room capacity violation

import pandas as pd

STEP2_CSV = "step2_solution_with_rooms_by_week.csv"
OVERLAP_CSV = "event_overlap.csv"
ROOMS_XLSX = "room.xlsx"
EVENTS_XLSX = "events.xlsx"

OUTPUT_CLASH_DETAIL_CSV = "student_clash_details.csv"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
HOUR2SLOT = {h: i for i, h in enumerate(range(9, 18))}  # 9点~17点 -> 0~8

NO_ROOM_FLAG = "No room required"

ROOMTYPE_MAP = {
    "NHS Room": "General Teaching",
}


def norm_room_type(x):
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s.lower() in ["nan", "none", "null", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)


def 区间是否重叠(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)


def 读取并整理step2课表(step2_csv):
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


def 读取room数据():
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


def 读取event数据():
    ev = pd.read_excel(EVENTS_XLSX).copy()
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

# 给student_clashs设定wholeclass和subgroup的不同权重
def clash_weight(wc1, wc2):
    wc1 = str(wc1).strip().upper()
    wc2 = str(wc2).strip().upper()

    if wc1 == "TRUE" and wc2 == "TRUE":
        return 1.0
    elif wc1 == "TRUE" or wc2 == "TRUE":
        return 0.7
    else:
        return 0.3

def 评估_student_clash(sol, ev):
    whole_class_map = dict(
        zip(ev["event_id"].astype(str), ev["whole_class"].astype(str))
    )
    
    # 建 event -> [(week, day, start_slot, end_slot)] 字典
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

    chunks = pd.read_csv(OVERLAP_CSV, chunksize=200000)

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

                    if 区间是否重叠(s1, e1_end, s2, e2_end):
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


def 评估_after_5pm(sol, ev):
    # 这里只惩罚 whole class 在17:00开始的情况
    # 因为你们的slot是9~17，17点开始已经属于 after 5pm
    whole_class_set = set(
        ev.loc[ev["whole_class"] == "TRUE", "event_id"].astype(str).tolist()
    )

    bad = sol[
        (sol["event_id"].isin(whole_class_set))
        & (sol["assigned_start_hour"] >= 17)
    ].copy()

    penalty = len(bad)
    return len(bad), penalty

def 评估_wednesday_afternoon_wholeclass(sol, ev):
    whole_class_set = set(
        ev.loc[ev["whole_class"] == "TRUE", "event_id"].astype(str).tolist()
    )

    bad = sol[
        (sol["event_id"].isin(whole_class_set))
        & (sol["assigned_day"] == "Wednesday")
        & (sol["assigned_start_hour"] >= 13)
    ].copy()

    penalty = len(bad)
    return len(bad), penalty


def 评估_lunch_break_近似(sol):
    # 近似版：
    # 只要 event 在12点或13点开始，就记一次 lunch penalty
    bad = sol[sol["assigned_start_hour"].isin([12, 13])].copy()
    penalty = len(bad)
    return len(bad), penalty


def 评估_same_room_across_weeks(sol):
    # 对每个 event，看它 across weeks 是否用了多个不同room
    # 空房间不算
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


def 评估_room_capacity(sol, ev, rm):
    tmp = sol.copy()

    # 如果 step2 里已经有 size，就直接用
    # 没有的话，再从 events.xlsx 补
    if "size" not in tmp.columns:
        tmp = tmp.merge(
            ev[["event_id", "size"]],
            on="event_id",
            how="left"
        )

    # 合并 room capacity
    tmp = tmp.merge(
        rm[["room_id", "cap"]],
        on="room_id",
        how="left"
    )

    tmp["size"] = pd.to_numeric(tmp["size"], errors="coerce").fillna(0)
    tmp["cap"] = pd.to_numeric(tmp["cap"], errors="coerce")

    # 只看真正分了房间的
    bad = tmp[
        tmp["room_id"].notna()
        & (tmp["room_id"].astype(str).str.strip() != "")
        & tmp["cap"].notna()
        & (tmp["size"] > tmp["cap"])
    ].copy()

    # penalty = 超出人数总和
    bad["overflow"] = bad["size"] - bad["cap"]

    count_bad = len(bad)
    penalty = bad["overflow"].sum()

    return count_bad, penalty

def 评估_expected_campus_mismatch(sol, ev):
    tmp = sol.copy()

    # merge event expected campus
    tmp = tmp.merge(
        ev[["event_id", "event_campus"]],
        on="event_id",
        how="left"
    )

    # 只看真正分了房间的
    tmp = tmp[
        tmp["room_id"].notna()
        & (tmp["room_id"].astype(str).str.strip() != "")
    ].copy()

    # step2结果里已经有 room_campus，不要再 merge room 表
    tmp["event_campus"] = tmp["event_campus"].fillna(NO_ROOM_FLAG).astype(str).str.strip()
    tmp["room_campus"] = tmp["room_campus"].fillna("").astype(str).str.strip()

    # 只对需要房间的课判断 mismatch
    bad = tmp[
        (tmp["event_campus"] != NO_ROOM_FLAG)
        & (tmp["event_campus"] != tmp["room_campus"])
    ].copy()

    count_bad = len(bad)
    penalty = count_bad

    return count_bad, penalty

def 百分比(part, whole):
    if whole == 0:
        return 0.0
    return 100.0 * part / whole

def main(step2_csv="step2_solution_with_rooms_by_week_baseline.csv"):
    print(">>> DEBUG: entering step3 main")
    sol = 读取并整理step2课表(step2_csv)
    rm = 读取room数据()
    ev = 读取event数据()

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
    clash_count, clash_penalty, total_overlap_pairs = 评估_student_clash(sol, ev)

    # 2a. after 5pm
    evening_count, evening_penalty = 评估_after_5pm(sol, ev)
    # 2b. Wednesday afternoon whole-class
    wed_count, wed_penalty = 评估_wednesday_afternoon_wholeclass(sol, ev)
    
    
    # 3. lunch break（近似）
    lunch_count, lunch_penalty = 评估_lunch_break_近似(sol)

    # 4. same room across weeks
    same_room_bad_events, same_room_penalty = 评估_same_room_across_weeks(sol)

    # 5. room capacity violation
    cap_bad_count, cap_penalty = 评估_room_capacity(sol, ev, rm)

    # 6. campus mismatch
    campus_bad_count, campus_penalty = 评估_expected_campus_mismatch(sol, ev)

    print("=== 软约束评估结果 ===")
    print()

    print("[1] Student Clash")
    print("冲突的 event pair 数量:", clash_count)
    print("占全部 overlap pair 的比例: {:.2f}%".format(百分比(clash_count, total_overlap_pairs)))
    print("总 clash penalty:", clash_penalty)
    print()

    print("[2a] Core Teaching After 5pm")
    print("违反数量:", evening_count)
    print("占 whole-class occurrence 的比例: {:.2f}%".format(百分比(evening_count, total_wholeclass_occurrences)))
    print("penalty:", evening_penalty)
    print()

    print("[2b] Wednesday Afternoon Whole-Class")
    print("违反数量:", wed_count)
    print("占 whole-class occurrence 的比例: {:.2f}%".format(百分比(wed_count, total_wholeclass_occurrences)))
    print("penalty:", wed_penalty)
    print()
    
    print(">>> DEBUG: about to print lunch")
    print("[3] Lunch Break (近似版)")
    print("落在12点或13点开始的事件数:", lunch_count)
    print("占全部 occurrence 的比例: {:.2f}%".format(百分比(lunch_count, total_occurrences)))
    print("penalty:", lunch_penalty)
    print()

    print(">>> DEBUG: about to print same room")
    print("[4] Same Room Across Weeks")
    print("使用多个不同room的event数量:", same_room_bad_events)
    print("占全部 event 的比例: {:.2f}%".format(百分比(same_room_bad_events, total_events)))
    print("penalty:", same_room_penalty)
    print()

    print("[5] Room Capacity Violation")
    print("容量超限的occurrence数量:", cap_bad_count)
    print("占有房间 occurrence 的比例: {:.2f}%".format(百分比(cap_bad_count, total_room_occurrences)))
    print("penalty(超出人数总和):", cap_penalty)
    print()

    print("[6] Expected Campus Mismatch")
    print("不符合Expected Campus的occurrence数量:", campus_bad_count)
    print("占适用 occurrence 的比例: {:.2f}%".format(百分比(campus_bad_count, campus_applicable_total)))
    print("penalty:", campus_penalty)
    print()

    print("student clash 明细文件:", OUTPUT_CLASH_DETAIL_CSV)

    # ===== objective =====
    w_clash = 1000
    w_evening = 10
    w_wed = 8
    w_lunch = 5
    w_same_room = 2
    w_capacity = 500
    w_campus = 20

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
    print("Total objective:", objective)
    print()

    print("=== Objective Contribution Breakdown ===")
    print("Student Clash contribution:", clash_contrib, "({:.2f}%)".format(百分比(clash_contrib, objective)))
    print("After 5pm contribution:", evening_contrib, "({:.2f}%)".format(百分比(evening_contrib, objective)))
    print("Wednesday contribution:", wed_contrib, "({:.2f}%)".format(百分比(wed_contrib, objective)))
    print("Lunch contribution:", lunch_contrib, "({:.2f}%)".format(百分比(lunch_contrib, objective)))
    print("Same Room contribution:", same_room_contrib, "({:.2f}%)".format(百分比(same_room_contrib, objective)))
    print("Capacity contribution:", capacity_contrib, "({:.2f}%)".format(百分比(capacity_contrib, objective)))
    print("Campus contribution:", campus_contrib, "({:.2f}%)".format(百分比(campus_contrib, objective)))

if __name__ == "__main__":
    main()
    
    
    
