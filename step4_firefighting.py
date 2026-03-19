# step4_firefighting.py
# Firefighting local search:
# 只在 Step1 的时间模板上做改动
# 优先修 student clash，同时兼顾 after 5pm 和 lunch
# 跑完后会输出新的 step1_solution_firefight.csv
# 然后你再用这个新文件去跑 step2 / check / step3

import pandas as pd
from collections import defaultdict

STEP1_SOL = "step1_solution.csv"
EVENTS_XLSX = "events.xlsx"
ROOMS_XLSX = "room.xlsx"
CLASH_DETAIL_CSV = "student_clash_details.csv"

OUTPUT_STEP1 = "step1_solution_firefight.csv"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
DAY_TO_IDX = {d: i for i, d in enumerate(DAYS)}
IDX_TO_DAY = {i: d for i, d in enumerate(DAYS)}

SLOT_START_HOURS = list(range(9, 18))   # 9..17
NUM_SLOTS = len(SLOT_START_HOURS)

NO_ROOM_FLAG = "No room required"

ROOMTYPE_MAP = {
    "NHS Room": "General Teaching",
}

# 目标函数权重（先用你前面那套）
W_CLASH = 1000
W_EVENING = 10
W_LUNCH = 5

# 最多处理多少个热点event
TOP_EVENTS_TO_TRY = 200


def norm_room_type(x):
    if pd.isna(x):
        return NO_ROOM_FLAG
    s = str(x).strip()
    if s.lower() in ["nan", "none", "null", ""]:
        return NO_ROOM_FLAG
    return ROOMTYPE_MAP.get(s, s)


def parse_weeks(x):
    if pd.isna(x):
        return set()
    out = set()
    for tok in str(x).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


def intervals_overlap(start1, end1, start2, end2):
    return max(start1, start2) < min(end1, end2)


def load_step1():
    df = pd.read_csv(STEP1_SOL).copy()
    df["event_id"] = df["event_id"].astype(str).str.strip()
    df["assigned_day"] = df["assigned_day"].astype(str).str.strip()
    df["assigned_start_hour"] = pd.to_numeric(df["assigned_start_hour"], errors="coerce")
    df["L_slots"] = pd.to_numeric(df["L_slots"], errors="coerce")
    df["size"] = pd.to_numeric(df["size"], errors="coerce").fillna(0).astype(int)
    df["req_room_type"] = df["req_room_type"].apply(norm_room_type)
    df["weeks_set"] = df["weeks"].apply(parse_weeks)
    return df


def load_events_meta():
    ev = pd.read_excel(EVENTS_XLSX).copy()
    ev.columns = ev.columns.str.strip()

    ev = ev.rename(columns={
        "Event ID": "event_id",
        "WholeClass": "whole_class",
    })

    ev["event_id"] = ev["event_id"].astype(str).str.strip()

    if "whole_class" in ev.columns:
        ev["whole_class"] = ev["whole_class"].astype(str).str.strip().str.upper()
    else:
        ev["whole_class"] = "FALSE"

    return ev[["event_id", "whole_class"]]


def load_room_type_capacity():
    rm = pd.read_excel(ROOMS_XLSX).copy()
    rm.columns = rm.columns.str.strip()

    rm = rm.rename(columns={
        "Specialist room type": "room_type"
    })
    rm["room_type"] = rm["room_type"].apply(norm_room_type)

    type_capacity = rm.groupby("room_type").size().to_dict()
    return type_capacity


def build_event_info(step1, ev_meta):
    df = step1.merge(ev_meta, on="event_id", how="left")
    df["whole_class"] = df["whole_class"].fillna("FALSE").astype(str).str.upper()

    event_info = {}
    for row in df.itertuples(index=False):
        event_info[row.event_id] = {
            "day": row.assigned_day,
            "day_idx": DAY_TO_IDX[row.assigned_day],
            "start_hour": int(row.assigned_start_hour),
            "start_slot": int(row.assigned_start_hour) - 9,
            "L_slots": int(row.L_slots),
            "end_slot": int(row.assigned_start_hour) - 9 + int(row.L_slots),
            "weeks_set": set(row.weeks_set),
            "room_type": row.req_room_type,
            "whole_class": row.whole_class,
        }
    return event_info


def build_occupancy(step1):
    # occupancy[(room_type, week, day_idx, slot)] = count
    occ = defaultdict(int)

    for row in step1.itertuples(index=False):
        room_type = row.req_room_type
        if room_type == NO_ROOM_FLAG:
            continue

        day_idx = DAY_TO_IDX[row.assigned_day]
        start_slot = int(row.assigned_start_hour) - 9
        L = int(row.L_slots)
        end_slot = start_slot + L

        for wk in row.weeks_set:
            for s in range(start_slot, end_slot):
                occ[(room_type, wk, day_idx, s)] += 1

    return occ


def load_clash_details():
    # 这个文件来自你当前的 step3 overlap 版本
    # 用它来定位“热点 event”
    df = pd.read_csv(CLASH_DETAIL_CSV).copy()
    df["event1"] = df["event1"].astype(str).str.strip()
    df["event2"] = df["event2"].astype(str).str.strip()
    df["shared_students"] = pd.to_numeric(df["shared_students"], errors="coerce").fillna(0).astype(int)
    return df


def build_hotspot_and_neighbors(clash_df):
    # hotspot_score[event] = 当前 clash 里这个 event 的总权重
    hotspot_score = defaultdict(int)

    # neighbor_weight[e1][e2] = 共享学生权重（用于局部打分）
    neighbor_weight = defaultdict(lambda: defaultdict(int))

    for row in clash_df.itertuples(index=False):
        e1 = row.event1
        e2 = row.event2
        w = int(row.shared_students)

        hotspot_score[e1] += w
        hotspot_score[e2] += w

        # 同一对可能在 detail 里重复出现，这里直接累加
        neighbor_weight[e1][e2] += w
        neighbor_weight[e2][e1] += w

    return hotspot_score, neighbor_weight


def local_score(event_id, cand_day_idx, cand_start_slot, event_info, neighbor_weight):
    """
    只计算这个 event 的局部目标：
    1. 与当前已知冲突邻居的 clash penalty
    2. after 5pm penalty
    3. lunch penalty
    """
    info = event_info[event_id]
    cand_end_slot = cand_start_slot + info["L_slots"]
    score = 0

    # 1. clash
    for other, w in neighbor_weight.get(event_id, {}).items():
        if other not in event_info:
            continue

        other_info = event_info[other]

        if cand_day_idx != other_info["day_idx"]:
            continue

        if intervals_overlap(
            cand_start_slot, cand_end_slot,
            other_info["start_slot"], other_info["end_slot"]
        ):
            score += W_CLASH * w

    # 2. evening
    cand_start_hour = 9 + cand_start_slot
    if info["whole_class"] == "TRUE" and cand_start_hour >= 17:
        score += W_EVENING

    # 3. lunch
    if cand_start_hour in [12, 13]:
        score += W_LUNCH

    return score


def feasible_under_type_capacity(event_id, old_info, cand_day_idx, cand_start_slot, occ, type_capacity):
    """
    用 Step1 的 room-type capacity 规则检查这个 move 是否可行
    """
    room_type = old_info["room_type"]
    if room_type == NO_ROOM_FLAG:
        return True

    cap = type_capacity.get(room_type, 0)
    if cap <= 0:
        return False

    L = old_info["L_slots"]
    cand_end_slot = cand_start_slot + L

    # 先假设把旧位置拿掉，再看新位置能不能放进去
    temp_delta = defaultdict(int)

    # 旧位置 -1
    for wk in old_info["weeks_set"]:
        for s in range(old_info["start_slot"], old_info["end_slot"]):
            temp_delta[(room_type, wk, old_info["day_idx"], s)] -= 1

    # 新位置 +1
    for wk in old_info["weeks_set"]:
        for s in range(cand_start_slot, cand_end_slot):
            temp_delta[(room_type, wk, cand_day_idx, s)] += 1

    # 检查是否超过 type capacity
    for key, delta in temp_delta.items():
        new_count = occ.get(key, 0) + delta
        if new_count > cap:
            return False

    return True


def apply_move_to_occ(event_id, old_info, new_day_idx, new_start_slot, occ):
    """
    接受 move 后，把 occupancy 更新掉
    """
    room_type = old_info["room_type"]
    if room_type == NO_ROOM_FLAG:
        return

    # 旧位置 -1
    for wk in old_info["weeks_set"]:
        for s in range(old_info["start_slot"], old_info["end_slot"]):
            occ[(room_type, wk, old_info["day_idx"], s)] -= 1

    # 新位置 +1
    new_end_slot = new_start_slot + old_info["L_slots"]
    for wk in old_info["weeks_set"]:
        for s in range(new_start_slot, new_end_slot):
            occ[(room_type, wk, new_day_idx, s)] += 1


def main():
    step1 = load_step1()
    ev_meta = load_events_meta()
    type_capacity = load_room_type_capacity()
    clash_df = load_clash_details()

    event_info = build_event_info(step1, ev_meta)
    occ = build_occupancy(step1)

    hotspot_score, neighbor_weight = build_hotspot_and_neighbors(clash_df)

    # 按热点程度排序，只处理最差的一批
    hotspot_events = sorted(
        hotspot_score.items(),
        key=lambda x: x[1],
        reverse=True
    )[:TOP_EVENTS_TO_TRY]

    improved = 0

    for event_id, _ in hotspot_events:
        if event_id not in event_info:
            continue

        info = event_info[event_id]

        # 当前局部分数
        current_score = local_score(
            event_id,
            info["day_idx"],
            info["start_slot"],
            event_info,
            neighbor_weight
        )

        best_day_idx = info["day_idx"]
        best_start_slot = info["start_slot"]
        best_score = current_score

        # 穷举所有可行时间模板
        for cand_day_idx in range(len(DAYS)):
            for cand_start_slot in range(NUM_SLOTS):
                # 持续时间不能越界
                if cand_start_slot + info["L_slots"] > NUM_SLOTS:
                    continue

                # 当前时间跳过
                if cand_day_idx == info["day_idx"] and cand_start_slot == info["start_slot"]:
                    continue

                # 检查 Step1 的 room-type capacity feasibility
                if not feasible_under_type_capacity(
                    event_id, info, cand_day_idx, cand_start_slot, occ, type_capacity
                ):
                    continue

                cand_score = local_score(
                    event_id,
                    cand_day_idx,
                    cand_start_slot,
                    event_info,
                    neighbor_weight
                )

                if cand_score < best_score:
                    best_score = cand_score
                    best_day_idx = cand_day_idx
                    best_start_slot = cand_start_slot

        # 如果找到更好位置，就接受
        if best_score < current_score:
            apply_move_to_occ(event_id, info, best_day_idx, best_start_slot, occ)

            event_info[event_id]["day_idx"] = best_day_idx
            event_info[event_id]["day"] = IDX_TO_DAY[best_day_idx]
            event_info[event_id]["start_slot"] = best_start_slot
            event_info[event_id]["start_hour"] = 9 + best_start_slot
            event_info[event_id]["end_slot"] = best_start_slot + info["L_slots"]

            improved += 1

    # 写回新的 step1_solution
    out = step1.copy()

    for i, row in out.iterrows():
        eid = row["event_id"]
        if eid in event_info:
            out.at[i, "assigned_day"] = event_info[eid]["day"]
            out.at[i, "assigned_start_hour"] = event_info[eid]["start_hour"]

    out.to_csv(OUTPUT_STEP1, index=False)

    print("Firefighting completed.")
    print("Improved events:", improved)
    print("New step1 solution written to:", OUTPUT_STEP1)


if __name__ == "__main__":
    main()