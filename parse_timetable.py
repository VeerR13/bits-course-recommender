import json
import pdfplumber

TIMETABLE_PATH = "/Users/veerraghuvanshi/Downloads/dataset/timetable.pdf"
OUT_COURSES = "data/courses.json"

DAY_TOKENS = ["M", "T", "W", "Th", "F", "S"]

RESTRICTION_NOTE = (
    "Courses with com cod >=5000 are meant only for 2026 admissions into FD, HD and PHD and not for others"
)

unverified = []


def flag(file, course_code, field, reason):
    unverified.append({"file": file, "course_code": course_code, "field": field, "reason": reason})


# header rows repeat on every page, sometimes split into two lines, so check both patterns
def is_header_row(row):
    first = row[0] or ""
    if "COM" in first and "COD" in first:
        return True
    if row[3] == "L" and row[4] == "P" and row[5] == "T" and row[6] == "S":
        return True
    return False


def clean_text(cell):
    if not cell:
        return None
    text = cell.replace("\n", " ")
    text = " ".join(text.split())
    return text if text else None


# credit numbers sometimes wrap onto two lines inside a narrow cell, e.g. "1\n0" for 10
def parse_credit(cell, course_code, field_name):
    if not cell:
        return 0
    text = cell.replace("\n", "").strip()
    if text == "-" or text == "":
        return 0
    try:
        return int(text)
    except ValueError:
        flag(TIMETABLE_PATH, course_code, field_name, "credit value not a plain number: " + repr(cell))
        return None


def parse_com_cod(cell, course_code):
    text = (cell or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        flag(TIMETABLE_PATH, course_code, "com_cod", "com_cod not numeric: " + repr(cell))
        return None


# "M W 3 Th 9" means Monday+Wednesday hour 3, then Thursday hour 9
# "T 8 9" means Tuesday hour 8 and Tuesday hour 9 (same day group gets both numbers)
def parse_meetings(cell, course_code):
    text = clean_text(cell)
    if not text or text == "CANCLED":
        return []
    tokens = text.split()
    meetings = []
    pending_days = []
    have_assigned = False
    for tok in tokens:
        if tok in DAY_TOKENS:
            if have_assigned:
                pending_days = []
                have_assigned = False
            pending_days.append(tok)
        elif tok.isdigit():
            if not pending_days:
                flag(TIMETABLE_PATH, course_code, "meetings", "hour with no day before it: " + repr(text))
                continue
            for day in pending_days:
                meetings.append({"day": day, "hour": int(tok)})
            have_assigned = True
        else:
            flag(TIMETABLE_PATH, course_code, "meetings", "unrecognised token '" + tok + "' in: " + repr(text))
    return meetings


# "05/10 AN1" -> date "05/10", session "AN1"
def parse_date_session(cell, course_code, field_name):
    text = clean_text(cell)
    if not text:
        return None, None
    parts = text.split()
    if len(parts) != 2:
        flag(TIMETABLE_PATH, course_code, field_name, "could not split date/session cleanly: " + repr(text))
        return text, None
    return parts[0], parts[1]


def new_course_record(page_num, com_cod, course_code, title, row):
    credits = {
        "L": parse_credit(row[3], course_code, "credits.L"),
        "P": parse_credit(row[4], course_code, "credits.P"),
        "T": parse_credit(row[5], course_code, "credits.T"),
        "S": parse_credit(row[6], course_code, "credits.S"),
        "units": parse_credit(row[7], course_code, "credits.units"),
    }
    return {
        "course_code": course_code,
        "title": title,
        "credits": credits,
        "com_cod": com_cod,
        "sections": [],
        "source": {"file": "timetable.pdf", "page": page_num},
    }


def make_section(page_num, course_code, row):
    section = clean_text(row[8])
    instructor = clean_text(row[9])
    room = clean_text(row[10])
    meetings = parse_meetings(row[11], course_code)
    midsem_date, midsem_session = parse_date_session(row[12], course_code, "midsem")
    compre_date, compre_session = parse_date_session(row[13], course_code, "compre")
    if not section:
        flag(TIMETABLE_PATH, course_code, "section", "section row has no section label on page " + str(page_num))
    if room and "(" in room:
        # room text like "1234(T) 1202(M W)" means a different room per day, we store it raw and don't split it
        flag(TIMETABLE_PATH, course_code, "room", "room differs by day, stored as raw text: " + repr(room))
    return {
        "section": section,
        "instructor": instructor,
        "other_instructors": [],
        "room": room,
        "meetings": meetings,
        "midsem_date": midsem_date,
        "midsem_session": midsem_session,
        "compre_date": compre_date,
        "compre_session": compre_session,
    }


def parse_timetable():
    courses = []
    current_course = None
    current_section = None

    pdf = pdfplumber.open(TIMETABLE_PATH)
    for page_index, page in enumerate(pdf.pages):
        page_num = page_index + 1
        tables = page.extract_tables()
        for table in tables:
            if not table or not table[0] or len(table[0]) != 14:
                continue
            for row in table:
                if is_header_row(row):
                    continue

                com_cod_raw = (row[0] or "").strip()
                sec_raw = (row[8] or "").strip()
                instructor_raw = (row[9] or "").strip()

                if com_cod_raw:
                    course_code = clean_text(row[1])
                    title = clean_text(row[2])
                    if not course_code:
                        flag(TIMETABLE_PATH, None, "course_code", "com_cod present but course code blank on page " + str(page_num))
                        course_code = "UNKNOWN"
                    if not title:
                        flag(TIMETABLE_PATH, course_code, "title", "course code present but title blank on page " + str(page_num))
                    com_cod = parse_com_cod(com_cod_raw, course_code)
                    current_course = new_course_record(page_num, com_cod, course_code, title, row)
                    courses.append(current_course)
                    current_section = make_section(page_num, course_code, row)
                    current_course["sections"].append(current_section)
                    continue

                if current_course is None:
                    # stray row before we have ever seen a real course start, skip it
                    continue

                if sec_raw:
                    current_section = make_section(page_num, current_course["course_code"], row)
                    current_course["sections"].append(current_section)
                    continue

                if instructor_raw:
                    # a co-instructor line under the previous section, no new section info here
                    if current_section is not None:
                        current_section["other_instructors"].append(instructor_raw)
                    continue

                # otherwise this is a blank filler row (e.g. a lone "Practical" label) - nothing to record

    return courses


def main():
    courses = parse_timetable()

    distinct_codes = set()
    total_sections = 0
    for c in courses:
        distinct_codes.add(c["course_code"])
        total_sections += len(c["sections"])

    print("parsed course records:", len(courses))
    print("distinct course codes:", len(distinct_codes))
    print("total section rows:", total_sections)
    print("unverified entries so far:", len(unverified))

    output = {
        "note_com_cod_restriction": RESTRICTION_NOTE,
        "courses": courses,
    }

    with open(OUT_COURSES, "w") as f:
        json.dump(output, f, indent=2)

    with open("data/unverified.json", "w") as f:
        json.dump(unverified, f, indent=2)


if __name__ == "__main__":
    main()
