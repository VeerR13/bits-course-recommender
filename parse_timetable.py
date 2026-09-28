import json
import pdfplumber

TIMETABLE_PATH = "/Users/veerraghuvanshi/Downloads/dataset/timetable.pdf"
DAY_TOKENS = ["M", "T", "W", "Th", "F", "S"]
RESTRICTION_NOTE = "Courses with com cod >=5000 are meant only for 2026 admissions into FD, HD and PHD and not for others"

unverified = []


def flag(course_code, field, reason):
    unverified.append({"file": "timetable.pdf", "course_code": course_code, "field": field, "reason": reason})


# header rows repeat on every page, sometimes split into two lines, so check both
def is_header_row(row):
    first = row[0] or ""
    return ("COM" in first and "COD" in first) or row[3] == "L"


def clean_text(cell):
    if not cell:
        return None
    text = " ".join(cell.replace("\n", " ").split())
    return text if text else None


# credits sometimes wrap onto two lines in a narrow cell, e.g. "1\n0" for 10
def parse_credit(cell, course_code, field_name):
    text = (cell or "").replace("\n", "").strip()
    if text in ("", "-"):
        return 0
    try:
        return int(text)
    except ValueError:
        flag(course_code, field_name, "not a plain number: " + repr(cell))
        return None


# "M W 3 Th 9" means Monday+Wednesday hour 3, then Thursday hour 9
# "T 8 9" means Tuesday hour 8 and Tuesday hour 9 (same day group takes both numbers)
def parse_meetings(cell, course_code):
    text = clean_text(cell)
    if not text or text == "CANCLED":
        return []
    meetings = []
    pending_days = []
    have_hour = False
    for tok in text.split():
        if tok in DAY_TOKENS:
            if have_hour:
                pending_days = []
                have_hour = False
            pending_days.append(tok)
        elif tok.isdigit() and pending_days:
            for day in pending_days:
                meetings.append({"day": day, "hour": int(tok)})
            have_hour = True
        else:
            flag(course_code, "meetings", "could not read token '" + tok + "' in: " + repr(text))
    return meetings


# "05/10 AN1" -> date "05/10", session "AN1"
def parse_date_session(cell, course_code, field_name):
    text = clean_text(cell)
    if not text:
        return None, None
    parts = text.split()
    if len(parts) != 2:
        flag(course_code, field_name, "could not split date and session: " + repr(text))
        return text, None
    return parts[0], parts[1]


def make_section(page_num, course_code, row):
    section = clean_text(row[8])
    if not section:
        flag(course_code, "section", "section row with no section label on page " + str(page_num))
    midsem_date, midsem_session = parse_date_session(row[12], course_code, "midsem")
    compre_date, compre_session = parse_date_session(row[13], course_code, "compre")
    return {
        "section": section,
        "instructor": clean_text(row[9]),
        "other_instructors": [],
        "room": clean_text(row[10]),
        "meetings": parse_meetings(row[11], course_code),
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
        for table in page.extract_tables():
            if not table or not table[0] or len(table[0]) != 14:
                continue
            for row in table:
                if is_header_row(row):
                    continue

                com_cod_raw = (row[0] or "").strip()
                sec_raw = (row[8] or "").strip()
                instructor_raw = (row[9] or "").strip()

                if com_cod_raw:
                    course_code = clean_text(row[1]) or "UNKNOWN"
                    title = clean_text(row[2])
                    if not title:
                        flag(course_code, "title", "course code present but title blank on page " + str(page_num))
                    credits = {}
                    for key, col in [("L", 3), ("P", 4), ("T", 5), ("S", 6), ("units", 7)]:
                        credits[key] = parse_credit(row[col], course_code, "credits." + key)
                    current_course = {
                        "course_code": course_code,
                        "title": title,
                        "credits": credits,
                        "com_cod": parse_credit(row[0], course_code, "com_cod"),
                        "sections": [],
                        "source": {"file": "timetable.pdf", "page": page_num},
                    }
                    courses.append(current_course)
                    current_section = make_section(page_num, course_code, row)
                    current_course["sections"].append(current_section)

                elif current_course is None:
                    continue  # stray row before any real course has started

                elif sec_raw:
                    current_section = make_section(page_num, current_course["course_code"], row)
                    current_course["sections"].append(current_section)

                elif instructor_raw and current_section is not None:
                    # a co-instructor line under the previous section, not a new section
                    current_section["other_instructors"].append(instructor_raw)

    return courses


def main():
    courses = parse_timetable()
    codes = set(c["course_code"] for c in courses)
    sections = sum(len(c["sections"]) for c in courses)

    print("parsed course records:", len(courses))
    print("distinct course codes:", len(codes))
    print("total section rows:", sections)
    print("unverified entries so far:", len(unverified))

    with open("data/courses.json", "w") as f:
        json.dump({"note_com_cod_restriction": RESTRICTION_NOTE, "courses": courses}, f, indent=2)

    with open("data/unverified.json", "w") as f:
        json.dump(unverified, f, indent=2)


if __name__ == "__main__":
    main()
