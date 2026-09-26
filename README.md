# BITS Course Recommender

An assistant that helps a BITS student pick courses for a semester. It is meant to use the
actual academic data (timetable, handouts, bulletin, regulations) instead of guessing, so any
recommendation it gives is backed by real rules and real course details.

## What's here right now

This is the data extraction stage. The raw college PDFs (timetable, course handouts) get turned
into clean, structured JSON that later code can search and reason over.

- `parse_timetable.py` reads the semester timetable PDF and writes `data/courses.json`
- `parse_handouts.py` reads all the course handout PDFs and writes `data/handouts.json`
- `check_data.py` prints a few sanity checks on the extracted data
- `data/unverified.json` lists anything that could not be extracted reliably, instead of guessing it

Not built yet: the student profile, the eligibility rules, the natural-language question
answering, and the dashboard.

## Setup

1. Install the one dependency:
   ```
   pip install -r requirements.txt
   ```
2. `parse_timetable.py` and `parse_handouts.py` currently point at a fixed folder on one
   machine. Open each file and update these lines to point at your own copy of the dataset:
   ```
   TIMETABLE_PATH = "/path/to/dataset/timetable.pdf"
   HANDOUTS_DIR = "/path/to/dataset/handouts"
   ```

## Running it

Run the timetable parser first, then the handout parser. The handout parser adds to the same
problem list instead of overwriting it, so this order matters.

```
python3 parse_timetable.py
python3 parse_handouts.py
python3 check_data.py
```

This produces:

- `data/courses.json`
- `data/handouts.json`
- `data/unverified.json`
