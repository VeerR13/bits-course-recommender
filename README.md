# BITS Course Recommender

An assistant that helps a BITS student pick courses for a semester. It reads the actual
academic data - timetable, course handouts, and the course bulletin - and answers questions
like "suggest DELs related to AI" or "I need an OPEL with no attendance requirement" using that
data, rather than guessing.

## How it works

Raw PDFs are turned into structured JSON once, and the dashboard reads only that JSON at
runtime - it never touches a PDF while running.

```
timetable.pdf   -----> parse_timetable.py -----> data/courses.json
handouts/*.pdf  -----> parse_handouts.py  -----> data/handouts.json
bulletin.pdf    -----> parse_bulletin.py  -----> data/degree_requirements.json
                                            \---> data/discipline_courses.json
                        (all three add to)  ----> data/unverified.json

data/*.json -----> recommend.py (the recommendation logic) -----> app.py (the dashboard)
```

- `recommend.py` has no UI code in it. It loads the JSON files, works out what requirements a
  student still needs, which offered courses they're eligible for, what category each course
  falls into for them, and matches courses against a topic. All of this is ordinary
  deterministic Python - no model calls happen here.
- `app.py` is the Streamlit dashboard. It holds the student's profile, shows their remaining
  requirements, and turns a typed question into a filter either through Gemini or through plain
  filter widgets, then calls `recommend.py` to get results.
- `data/unverified.json` lists every case where something could not be extracted reliably from
  a PDF, instead of guessing at it.

## Setup

1. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
2. The parser scripts point at a fixed folder on one machine. Open each one and update the path
   constants at the top to point at your own copy of the dataset:
   ```
   TIMETABLE_PATH = "/path/to/dataset/timetable.pdf"
   HANDOUTS_DIR = "/path/to/dataset/handouts"
   BULLETIN_PATH = "/path/to/dataset/bulletin.pdf"
   ```
3. (Optional) Set a Gemini API key so typed questions can be parsed by a model instead of the
   filter widgets:
   ```
   export GEMINI_API_KEY=your-key-here
   ```
   The dashboard works fully without this - it falls back to plain filter widgets (category,
   topic, midsem/project/quiz/attendance checkboxes) if the key is missing or the call fails.

## Running it

Re-run the parsers only if the source PDFs change - the data in `data/` is already built.

```
python3 parse_timetable.py
python3 parse_handouts.py
python3 parse_bulletin.py
python3 check_data.py
```

Then start the dashboard:

```
streamlit run app.py
```

## Limitations

- Prerequisites are not present in the supplied data, so eligibility checking does not verify
  them. Every recommended course carries `prerequisites_checked: false`.
- HUEL is classified from the bulletin's own named "Pool of Humanities courses for first degree
  programmes" (PDF page 333). A course from the student's own discipline is excluded from
  counting as HUEL even when it appears in that pool, as stated on the same page.
- A course is treated as an Open Elective if it is an elective in some discipline other than the
  student's own, rather than waiting until the student's Discipline and Humanities elective
  quotas are actually full. This is the interpretation taken, not a limitation.
- 314 of the 586 offered courses do not appear in any parsed discipline course list, so their
  category comes back as UNKNOWN rather than a forced guess.
- 51 handouts have no usable evaluation table, so their properties (midsem, compre, project,
  quiz, lab, attendance) cannot be verified for those courses and are shown as such.
- A recommended course whose properties could not be verified is still shown, never dropped, and
  is labelled as unverified so the student can judge it themselves.
- Topic matching is whole-word matching over the course title and handout topics text, not
  semantic. A small fixed dictionary expands a few acronyms (AI, ML, NLP, OS, DBMS) into the
  phrases that actually appear in course text, and a hit in the title ranks above a hit only in
  the topics text. It will still miss a course phrased very differently from its own text, and
  it will not catch anything outside that short acronym list.
- Timetable clash detection is not implemented.
- Minor programme rules were not extracted, so the profile collects a minor but does not check
  its requirements.
- Dual Degree patterns, Higher Degree (M.E./M.Pharm./MBA/Ph.D.) structure, and general
  institute requirement course lists (Science Foundation, Technical Arts, etc.) were not parsed
  from the bulletin, so remaining-requirement progress for those categories cannot be computed.
