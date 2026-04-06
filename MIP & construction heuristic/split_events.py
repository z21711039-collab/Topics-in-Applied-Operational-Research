import pandas as pd

def main():
    df = pd.read_excel("events.xlsx")
    df.columns = df.columns.str.strip()

    new_rows = []

    for _, row in df.iterrows():
        dur = row["Duration (minutes)"]
        whole = str(row.get("WholeClass", "FALSE")).upper()

        # Only split: whole class and > 8 hours
        if whole == "TRUE" and dur > 480:
            d1 = 240   # 4 hours
            d2 = dur - 240

            r1 = row.copy()
            r2 = row.copy()

            r1["Event ID"] = str(row["Event ID"]) + "_A"
            r2["Event ID"] = str(row["Event ID"]) + "_B"

            r1["Duration (minutes)"] = d1
            r2["Duration (minutes)"] = d2

            new_rows.append(r1)
            new_rows.append(r2)
        else:
            new_rows.append(row)

    out = pd.DataFrame(new_rows)
    out.to_excel("events_split.xlsx", index=False)

    print("events_split.xlsx generated")

if __name__ == "__main__":
    main()