import pandas as pd
import re
from difflib import SequenceMatcher

# =========================
# 1️⃣ Read Event data
# =========================
print("Reading Event data...")

room_df = pd.read_excel("2024-5 Event Module Room.xlsx", usecols=[
    "Module Code", "Module Name", "Event ID", "Event Name", "Event Type",
    "Duration (minutes)", "Event Size", "WholeClass", "Online Delivery",
    "Timeslot", "Weeks", "Number of Weeks", "Room type 2", "Room",
    "Module Department", "Campus"
])

# =========================
# 2️⃣ Read Student Programme data
# =========================
print("\nReading Student Programme data...")

student_df = pd.read_excel("2024-5 Student Programme Module Event.xlsx", usecols=[
    "Department",
    "Programme",
    "Programme Code-Year",
    "Course Name",
    "Course Code",
    "Event ID"
])

print("Cleaning Student data...")
for col in student_df.columns:
    student_df[col] = student_df[col].astype(str).str.strip()
    student_df[col] = student_df[col].replace('nan', pd.NA).replace('None', pd.NA)

student_df = student_df.dropna(subset=["Event ID", "Course Name"])
print(f"Student data loaded, total {len(student_df)} records")

# =========================
# 3️⃣ Extract Programme Code (take part before first '_' from Programme Code-Year)
# =========================
print("Extracting Programme Code...")


def extract_programme_code(programme_code_year):
    """Extract Programme Code from Programme Code-Year (take part before first '_')"""
    if pd.isna(programme_code_year):
        return None
    code_str = str(programme_code_year).strip()
    if '_' in code_str:
        return code_str.split('_')[0].strip()
    return code_str


student_df['Programme Code'] = student_df['Programme Code-Year'].apply(extract_programme_code)

# =========================
# 4️⃣ Process Student data: Course takes most frequent, Programme keeps all
# =========================
print("Processing Student data: Course takes main value, Programme keeps all...")


def get_most_frequent(series):
    """Return the most frequent value, if multiple return the first"""
    if len(series) == 0:
        return None
    value_counts = series.value_counts()
    return value_counts.index[0]


def combine_all(series):
    """Combine all unique values separated by commas"""
    if len(series) == 0:
        return None
    return ', '.join(sorted(set(series)))


# Group by Event ID, different aggregation for different fields
student_agg = student_df.groupby('Event ID').agg({
    # Course related: take most frequent
    'Course Name': lambda x: get_most_frequent(x),
    'Course Code': lambda x: get_most_frequent(x),
    # Programme related: keep all
    'Programme': lambda x: combine_all(x),
    'Programme Code': lambda x: combine_all(x),
    'Department': lambda x: combine_all(x)
}).reset_index()

# Find Event IDs with multiple different Courses (for reporting)
multi_course_events = student_df.groupby('Event ID').agg({
    'Course Name': lambda x: len(set(x))
}).reset_index()
multi_course_events = multi_course_events[multi_course_events['Course Name'] > 1]

if len(multi_course_events) > 0:
    print(f"\nFound {len(multi_course_events)} Event IDs with multiple different Courses:")
    for _, row in multi_course_events.head(10).iterrows():
        print(f"  Event ID: {row['Event ID']} (has {row['Course Name']} different Courses)")
        courses = student_df[student_df['Event ID'] == row['Event ID']]['Course Name'].unique()
        print(f"    Courses: {', '.join(courses)}")
    if len(multi_course_events) > 10:
        print(f"    ... and {len(multi_course_events) - 10} more")

# Create Student mapping dictionary
student_event_map = {}
for _, row in student_agg.iterrows():
    student_event_map[row['Event ID']] = {
        'Course Name': row['Course Name'],
        'Course Code': row['Course Code'],
        'Programme Name': row['Programme'],
        'Programme Code': row['Programme Code'],
        'Department': row['Department']
    }

print(f"Student data processing complete, total {len(student_event_map)} unique Event IDs")

# =========================
# 5️⃣ Read DPT data
# =========================
print("\nReading DPT data...")

dpt_df = pd.read_excel("2024-5 DPT Data.xlsx", usecols=[
    "Programme Code",
    "Programme Name",
    "Course Code",
    "Course Name"
])

print("Cleaning DPT data...")
for col in dpt_df.columns:
    dpt_df[col] = dpt_df[col].astype(str).str.strip()
    dpt_df[col] = dpt_df[col].replace('nan', pd.NA).replace('None', pd.NA)

dpt_df = dpt_df.dropna(subset=["Course Name"])
print(f"DPT data loaded, total {len(dpt_df)} records")

# =========================
# 6️⃣ Pre-aggregate DPT data: Course takes most frequent, Programme keeps all
# =========================
print("Pre-aggregating DPT data...")


def get_most_frequent_course_code(series):
    """Return the most frequent Course Code"""
    if len(series) == 0:
        return None
    value_counts = pd.Series(series).value_counts()
    return value_counts.index[0]


# Count occurrences of each Course Name
dpt_course_counts = dpt_df.groupby('Course Name').size().reset_index(name='Course_Count')

# Aggregate by Course Name
dpt_agg = dpt_df.groupby('Course Name').agg({
    'Programme Name': lambda x: ', '.join(sorted(set(x))),
    'Programme Code': lambda x: ', '.join(sorted(set(x))),
    'Course Code': lambda x: get_most_frequent_course_code(x)
}).reset_index()

# Merge occurrence counts
dpt_agg = dpt_agg.merge(dpt_course_counts, on='Course Name', how='left')

# Create matching dictionaries
dpt_exact_map = {}
dpt_normalized_map = {}

for _, row in dpt_agg.iterrows():
    course_name = row['Course Name']
    dpt_exact_map[course_name] = {
        'Programme Name': row['Programme Name'],
        'Programme Code': row['Programme Code'],
        'Course Code': row['Course Code'],
        'Course_Count': row['Course_Count']
    }
    normalized = course_name.lower().strip()
    dpt_normalized_map[normalized] = course_name

# Save all Course Names (sorted alphabetically)
all_course_names = sorted(list(dpt_exact_map.keys()))
print(f"DPT data aggregation complete, total {len(dpt_exact_map)} unique Course Names")

# =========================
# 7️⃣ Save original Event ID
# =========================
print("Saving original Event ID...")
room_df["Original Event ID"] = room_df["Event ID"]

# =========================
# 8️⃣ Basic cleaning
# =========================
print("Basic cleaning...")

for col in ["Module Code", "Module Name", "Event ID", "Event Name",
            "Event Type", "Timeslot", "Weeks", "Room type 2", "Room",
            "Module Department", "Campus"]:
    room_df[col] = room_df[col].astype(str).str.strip()
    room_df[col] = room_df[col].replace('nan', pd.NA).replace('None', pd.NA)

room_df["Room"] = room_df["Room"].str.upper()
room_df["Duration (minutes)"] = pd.to_numeric(room_df["Duration (minutes)"], errors='coerce')
room_df["Event Size"] = pd.to_numeric(room_df["Event Size"], errors='coerce').fillna(0).astype(int)
room_df["WholeClass"] = room_df["WholeClass"].fillna(False).astype(bool)
room_df["Online Delivery"] = room_df["Online Delivery"].fillna(False).astype(bool)
room_df["Number of Weeks"] = pd.to_numeric(room_df["Number of Weeks"], errors='coerce').fillna(0).astype(int)

original_count = len(room_df)
room_df = room_df.dropna(subset=["Module Code", "Event ID"])
print(f"After removing nulls: {original_count} -> {len(room_df)}")

# =========================
# 9️⃣ Handle duplicate Event IDs
# =========================
print("Checking for duplicate Event IDs...")

duplicate_mask = room_df.duplicated(subset=["Event ID"], keep=False)
duplicates = room_df[duplicate_mask]

if not duplicates.empty:
    print(f"\nFound {len(duplicates)} duplicate records, involving {duplicates['Event ID'].nunique()} unique IDs")

    for dup_id in sorted(duplicates["Event ID"].unique()):
        mask = room_df["Event ID"] == dup_id
        indices = sorted(room_df[mask].index)
        suffixes = [f"{dup_id}_{i + 1}" for i in range(len(indices))]
        room_df.loc[mask, "Event ID"] = suffixes

    print(f"Duplicate IDs processed")
else:
    print("No duplicate Event IDs found")

# =========================
# 🔟 Room type correction
# =========================
print("\nReading Room file...")

room_lookup = pd.read_excel("room.xlsx")
room_lookup["Id"] = room_lookup["Id"].astype(str).str.strip().str.upper()
room_lookup["Specialist room type"] = room_lookup["Specialist room type"].astype(str).str.strip()
room_type_map = dict(zip(room_lookup["Id"], room_lookup["Specialist room type"]))

print("Correcting Room type 2...")
problem_types = ["Centrally Allocated Space", "Locally Allocated Space"]

mask = room_df["Room type 2"].isin(problem_types)
room_df.loc[mask & room_df["Room"].isin(room_type_map), "Room type 2"] = room_df.loc[
    mask & room_df["Room"].isin(room_type_map), "Room"].map(room_type_map)
room_df.loc[mask & ~room_df["Room"].isin(room_type_map), "Room type 2"] = "General Teaching"

# =========================
# 1️⃣1️⃣ Time filtering
# =========================
print("\nExtracting time and filtering...")


def extract_time_info(timeslot, duration):
    if pd.isna(timeslot) or pd.isna(duration):
        return pd.Series([None, None, False])

    timeslot_str = str(timeslot)

    weekday = None
    for day in ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']:
        if timeslot_str.startswith(day):
            weekday = day
            break

    if not weekday:
        return pd.Series([None, None, False])

    time_match = re.search(r'(\d{1,2}):(\d{2})', timeslot_str)
    if not time_match:
        return pd.Series([None, None, False])

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))

    start_minutes = hour * 60 + minute
    end_minutes = start_minutes + duration
    keep = (start_minutes >= 510) and (end_minutes <= 1110)

    return pd.Series([weekday, f"{hour:02d}:{minute:02d}", keep])


time_info = room_df.apply(lambda row: extract_time_info(row['Timeslot'], row['Duration (minutes)']), axis=1)
room_df[['Weekday', 'Start_Time', 'Keep']] = time_info

before_count = len(room_df)
filtered_df = room_df[room_df['Keep'] == True].copy()
filtered_df = filtered_df.drop(columns=['Keep'])

print(f"\nBefore filtering: {before_count}")
print(f"After filtering: {len(filtered_df)}")
print(f"Excluded: {before_count - len(filtered_df)}")

# =========================
# 1️⃣2️⃣ First round matching: Use Student data (Course takes main value, Programme keeps all)
# =========================
print("\n" + "=" * 60)
print("First round matching: Using Student data")
print("=" * 60)

filtered_df['Match_Source'] = None
filtered_df['Course Name'] = None
filtered_df['Course Code'] = None
filtered_df['Programme Name'] = None
filtered_df['Programme Code'] = None
filtered_df['Department'] = None

filtered_df['Student_Info'] = filtered_df['Original Event ID'].map(student_event_map)
student_matched_mask = filtered_df['Student_Info'].notna()
student_matched = student_matched_mask.sum()
student_unmatched = (~student_matched_mask).sum()

filtered_df.loc[student_matched_mask, 'Course Name'] = filtered_df.loc[student_matched_mask, 'Student_Info'].apply(
    lambda x: x['Course Name'])
filtered_df.loc[student_matched_mask, 'Course Code'] = filtered_df.loc[student_matched_mask, 'Student_Info'].apply(
    lambda x: x['Course Code'])
filtered_df.loc[student_matched_mask, 'Programme Name'] = filtered_df.loc[student_matched_mask, 'Student_Info'].apply(
    lambda x: x['Programme Name'])
filtered_df.loc[student_matched_mask, 'Programme Code'] = filtered_df.loc[student_matched_mask, 'Student_Info'].apply(
    lambda x: x['Programme Code'])
filtered_df.loc[student_matched_mask, 'Department'] = filtered_df.loc[student_matched_mask, 'Student_Info'].apply(
    lambda x: x['Department'])
filtered_df.loc[student_matched_mask, 'Match_Source'] = 'Student'

filtered_df = filtered_df.drop(columns=['Student_Info'])

print(f"Student matching results:")
print(f"  Successfully matched: {student_matched} records")
print(f"  Pending second round matching: {student_unmatched} records")

# =========================
# 1️⃣3️⃣ Second round matching: Use DPT data
# =========================
if student_unmatched > 0:
    print("\n" + "=" * 60)
    print("Second round matching: Using DPT data")
    print("=" * 60)


    def extract_course_key(event_name):
        if pd.isna(event_name):
            return None
        event_name_str = str(event_name).strip()
        if '-' in event_name_str:
            return event_name_str.split('-')[0].strip()
        return event_name_str


    def find_best_match(match_key, course_list):
        """Matching algorithm: highest similarity first, then highest occurrence count"""
        if pd.isna(match_key):
            return None, None

        match_key = str(match_key).strip()
        match_key_lower = match_key.lower()

        # 1. Exact match
        if match_key in dpt_exact_map:
            return match_key, dpt_exact_map[match_key]

        if match_key_lower in dpt_normalized_map:
            original_name = dpt_normalized_map[match_key_lower]
            return original_name, dpt_exact_map[original_name]

        # 2. Partial match
        candidates = []
        for course_name in course_list:
            course_lower = course_name.lower()
            if (match_key_lower in course_lower) or (course_lower in match_key_lower):
                similarity = SequenceMatcher(None, match_key_lower, course_lower).ratio()
                occurrence_count = dpt_exact_map[course_name]['Course_Count']
                candidates.append({
                    'course_name': course_name,
                    'similarity': similarity,
                    'occurrence': occurrence_count
                })

        # Sort by similarity descending, then by occurrence descending if similarity is same
        candidates.sort(key=lambda x: (-x['similarity'], -x['occurrence']))

        if candidates and candidates[0]['similarity'] > 0.6:
            best_course = candidates[0]['course_name']
            return best_course, dpt_exact_map[best_course]

        return None, None


    # Extract keywords
    unmatched_mask = filtered_df['Match_Source'].isna()
    filtered_df.loc[unmatched_mask, 'Match_Key'] = filtered_df.loc[unmatched_mask, 'Event Name'].apply(
        extract_course_key)

    # Matching
    dpt_matched = 0
    for idx in filtered_df[unmatched_mask].index:
        match_key = filtered_df.loc[idx, 'Match_Key']
        best_course, dpt_info = find_best_match(match_key, all_course_names)

        if best_course and dpt_info:
            filtered_df.at[idx, 'Course Name'] = best_course
            filtered_df.at[idx, 'Course Code'] = dpt_info['Course Code']
            filtered_df.at[idx, 'Programme Name'] = dpt_info['Programme Name']
            filtered_df.at[idx, 'Programme Code'] = dpt_info['Programme Code']
            filtered_df.at[idx, 'Department'] = None
            filtered_df.at[idx, 'Match_Source'] = 'DPT'
            dpt_matched += 1

    filtered_df = filtered_df.drop(columns=['Match_Key'], errors='ignore')

    dpt_unmatched = student_unmatched - dpt_matched

    print(f"DPT matching results:")
    print(f"  Successfully matched: {dpt_matched} records")
    print(f"  Final unmatched: {dpt_unmatched} records")
else:
    dpt_matched = 0
    dpt_unmatched = 0
    print("\nAll records successfully matched in first round")

# =========================
# 1️⃣4️⃣ Delete unmatched records
# =========================
print("\n" + "=" * 60)
print("Deleting unmatched records")
print("=" * 60)

total_before = len(filtered_df)
unmatched_mask = filtered_df['Match_Source'].isna()
unmatched_indices = filtered_df[unmatched_mask].index.tolist()

if unmatched_indices:
    unmatched_df = filtered_df.loc[unmatched_indices].copy()
    unmatched_df.to_excel("deleted_unmatched_events.xlsx", index=False)
    filtered_df = filtered_df.drop(index=unmatched_indices)

    print(f"Records before deletion: {total_before}")
    print(f"Deleted unmatched records: {len(unmatched_indices)}")
    print(f"Records after deletion: {len(filtered_df)}")
else:
    print(f"All {total_before} records matched successfully")

# =========================
# 1️⃣5️⃣ Final statistics
# =========================
print("\n" + "=" * 60)
print("Final Statistics")
print("=" * 60)

student_count = len(filtered_df[filtered_df['Match_Source'] == 'Student'])
dpt_count = len(filtered_df[filtered_df['Match_Source'] == 'DPT'])

print(f"Final retained records: {len(filtered_df)}")
print(f"  - Student matched: {student_count} records ({student_count / len(filtered_df) * 100:.1f}%)")
print(f"  - DPT matched: {dpt_count} records ({dpt_count / len(filtered_df) * 100:.1f}%)")
print(f"Deleted records: {len(unmatched_indices) if unmatched_indices else 0}")

# =========================
# 1️⃣6️⃣ Output results
# =========================
print("\nOutputting result files...")

# Column order for output: Event info + Course info + Programme info + Other
column_order = [
    # Event basic info
    'Event ID', 'Original Event ID', 'Event Name', 'Event Type',
    # Campus info (from original Event data)
    'Campus',
    # Course info (main value)
    'Course Name', 'Course Code',
    # Programme info (may be multiple)
    'Programme Name', 'Programme Code',
    # Department
    'Department',
    # Module info
    'Module Code', 'Module Name', 'Module Department',
    # Time info
    'Weekday', 'Start_Time', 'Timeslot', 'Duration (minutes)', 'Number of Weeks', 'Weeks',
    # Room info
    'Room', 'Room type 2',
    # Other
    'Event Size', 'WholeClass', 'Online Delivery', 'Match_Source'
]

existing_columns = [col for col in column_order if col in filtered_df.columns]
final_df = filtered_df[existing_columns]
final_df.to_excel("events-final.xlsx", index=False)

# Output matching report
with pd.ExcelWriter('matching-report.xlsx', engine='openpyxl') as writer:
    final_df.to_excel(writer, sheet_name='Matching Results', index=False)

    stats_df = pd.DataFrame({
        'Matching Stage': ['Student Match', 'DPT Match', 'Unmatched (Deleted)', 'Total'],
        'Record Count': [
            student_count,
            dpt_count,
            len(unmatched_indices) if unmatched_indices else 0,
            total_before
        ],
        'Percentage': [
            f"{student_count / total_before * 100:.1f}%",
            f"{dpt_count / total_before * 100:.1f}%",
            f"{len(unmatched_indices) / total_before * 100:.1f}%" if unmatched_indices else "0%",
            "100%"
        ]
    })
    stats_df.to_excel(writer, sheet_name='Statistics', index=False)

print("\n✅ Processing complete:")
print(f"   - events-final.xlsx (total {len(final_df)} records)")
print(f"     Course: takes main value, Programme: keeps all, Campus: from original Event data")
print(f"   - matching-report.xlsx (detailed matching report)")
if unmatched_indices:
    print(f"   - deleted_unmatched_events.xlsx ({len(unmatched_indices)} records deleted)")