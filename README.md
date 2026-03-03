[README.md](https://github.com/user-attachments/files/25728758/README.md)
# Timetabling Hard-Constraint Feasibility Framework

This project implements a hard-constraint timetabling framework for university scheduling.  
The current implementation focuses on finding feasible solutions only.

## Model Structure

### Step 1 – Hard-constraint feasibility scheduling (CP-SAT)

At this step, we only generate time templates and do not make specific room allocations.

We divide step1 into two stages:

- Stage A: schedule only need-room events
- Stage B: fix Stage A time templates for need-room events, then schedule no-room events

Hard constraints:

- (H1) Exactly One Start Time per Event
- (H2) Duration and Consecutiveness
- (H3) Fixed Weeks
- (H4) Room-Type Capacity (need-room events only)
- (H5) Pattern Constraint: Same Time Template Across Weeks

### Step 2 – Room Assignment by Week (Greedy)

Given the fixed time template from Step 1, Step 2 assigns a concrete room to each (event, week) occurrence.

Hard constraints:

- (H6) Room Assignment per Weekly Occurrence
- (H7) Strict Room-Type Compatibility
- (H8) Room–Time Conflicts

## Validation

The script `check.py` verifies that all hard constraints are satisfied, including:

- Valid week values
- No-room events not assigned a room
- Room existence and type consistency
- Valid time ranges and no overflow
- Consistent day/start pattern across weeks
- No (week, room, day, slot) conflicts

## Repository Structure

```
step1_hard_feasibility.py
step2_assign_rooms_by_week.py
check.py
events.xlsx
room.xlsx
```

## Installation

Python 3.10+

Install required packages:

```
pip install pandas ortools
```

## Usage

Run in the following order:

```
python step1_hard_feasibility.py
python step2_assign_rooms_by_week.py
python check.py
```

## AI Assistance

We use AI tools to assist in coding check.py. All modelling logic and constraint implementation were reviewed and validated.
