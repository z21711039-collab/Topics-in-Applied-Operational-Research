import pandas as pd

# 读取失败列表
fail = pd.read_csv("step2_failed_occurrences.csv")

# 读取事件信息
events = pd.read_excel("events.xlsx")

events = events.rename(columns={
    "Event ID": "event_id",
    "Event Size": "size",
    "Room type 2": "room_type"
})

# 合并
df = fail.merge(events[["event_id", "size", "room_type"]], on="event_id", how="left")

print("\n===== 失败 occurrence 总数 =====")
print(len(df))

print("\n===== 涉及的 unique event 数 =====")
print(df["event_id"].nunique())

print("\n===== 最大的课 (size top10) =====")
print(df.sort_values("size", ascending=False)[["event_id","size"]].head(10))

print("\n===== 哪些 room type 最难排 =====")
print(df["room_type"].value_counts().head(10))

print("\n===== size 分布 =====")
print(df["size"].describe())