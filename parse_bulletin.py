import json
import os
import re
import pdfplumber

BULLETIN_PATH = "/Users/veerraghuvanshi/Downloads/dataset/bulletin.pdf"
UNVERIFIED_PATH = "data/unverified.json"

# pages 313-335 (0-indexed) hold the per-discipline Core/Elective course lists, then the
# Humanities elective pool. Everything before or after that is out of scope for today.
FIRST_PAGE = 313
LAST_PAGE = 335

OPEN_ELECTIVE_RULE = (
    "Open Electives enable students to pursue courses that are not part of the discipline "
    "requirement nor part of the Humanities requirement. Normally any elective course will be "
    "treated as an Open Elective once the student's requirements under Discipline Electives and "
    "Humanities Electives have been accounted for. (Academic Regulations, page 9)"
)

COURSE_LINE = re.compile(r"^([A-Z]{2,6})\s+([A-Z]\d{2,4}[A-Z]{0,2})\s+(.*)$")
TRACK_LINE = re.compile(r"^(Track|Pool)\b")
ALL_CAPS_LINE = re.compile(r"^[A-Z][A-Z .,&\-–]{2,70}$")

unverified = []


def flag(course_code, field, reason):
    unverified.append({"file": "bulletin.pdf", "course_code": course_code, "field": field, "reason": reason})


# pulls the trailing L/P/U numbers off the end of a course line, e.g.
# "Structural Mechanics 3 0 3" -> ("Structural Mechanics", ["3","0","3"])
def split_title_and_numbers(text):
    tokens = text.split()
    numbers = []
    while tokens:
        last = tokens[-1].rstrip("*")
        if last == "":
            tokens.pop()
        elif last.isdigit() or last == "-":
            numbers.insert(0, last)
            tokens.pop()
        else:
            break
    return " ".join(tokens), numbers


def numbers_to_credits(numbers, course_code):
    values = [0 if n == "-" else int(n) for n in numbers]
    if len(values) == 3:
        return {"L": values[0], "P": values[1], "U": values[2]}
    if len(values) == 1:
        return {"L": None, "P": None, "U": values[0]}
    flag(course_code, "credits", "could not read L/P/U cleanly, found numbers: " + str(numbers))
    return {"L": None, "P": None, "U": None}


# a genuine wrapped title continuation is short (1-2 words, e.g. "Visualization" or "Empirical
# Analysis") and title-case, never ALL CAPS - an all-caps line is a department name instead
def looks_like_continuation(line):
    if line.isupper():
        return False
    words = line.split()
    if not words or len(words) > 2:
        return False
    first_word = words[0].lower().strip("(")
    return first_word not in ("track", "pool", "core", "discipline", "other", "list", "project", "course")


def flush(pending, courses):
    if pending is None:
        return
    credits = numbers_to_credits(pending["numbers"], pending["code"])
    if not pending["numbers"]:
        flag(pending["code"], "credits", "no L/P/U numbers found for this course")
    courses.append({
        "course_code": pending["code"],
        "title": pending["title"],
        "credits": credits,
        "discipline": pending["discipline"],
        "category": pending["category"],
        "track": pending["track"],
    })


def parse_course_lines(lines):
    courses = []
    pending = None
    discipline = None
    category = None
    track = None
    name_buffer = []
    stop = False

    for line in lines:
        if stop:
            break
        line = line.strip()
        if not line:
            continue

        if line == "List of Audit Type Courses":
            flush(pending, courses)
            stop = True
            continue

        if line.lower().startswith("pool of humanities courses"):
            flush(pending, courses)
            pending = None
            discipline, category, track, name_buffer = "Humanities Electives", "elective", None, []
            continue

        if line == "Other Courses":
            flush(pending, courses)
            pending = None
            discipline, category, track = "Other Electives", "elective", None
            continue

        if line == "CORE COURSES" or line.startswith("CORE COURSES "):
            flush(pending, courses)
            pending = None
            if name_buffer:
                discipline = " ".join(name_buffer)
            category, track, name_buffer = "core", None, []
            continue

        if line.startswith("DISCIPLINE ELECTIVE COURSES"):
            flush(pending, courses)
            pending = None
            category, track = "elective", None
            continue

        if TRACK_LINE.match(line):
            flush(pending, courses)
            pending = None
            track = line
            continue

        if "Course Title" in line or line in ("No.", "No", "L P U"):
            continue  # a repeated column header, not real data

        m = COURSE_LINE.match(line)
        if m:
            flush(pending, courses)
            title, numbers = split_title_and_numbers(m.group(3))
            pending = {
                "code": m.group(1) + " " + m.group(2),
                "title": title,
                "numbers": numbers,
                "discipline": discipline,
                "category": category,
                "track": track,
            }
            continue

        if pending is not None and looks_like_continuation(line):
            extra_title, extra_numbers = split_title_and_numbers(line)
            pending["title"] = (pending["title"] + " " + extra_title).strip()
            if not pending["numbers"] and extra_numbers:
                pending["numbers"] = extra_numbers
            continue

        # "OR OR" shows up where the table lists alternative courses stacked vertically - not a name
        is_just_or = all(w.upper() == "OR" for w in line.split())
        if ALL_CAPS_LINE.match(line) and not is_just_or:
            name_buffer.append(line)
        # else: an explanatory paragraph line, not part of any course entry - skip it

    flush(pending, courses)
    return courses


def parse_discipline_courses():
    pdf = pdfplumber.open(BULLETIN_PATH)
    lines = []
    for page in pdf.pages[FIRST_PAGE:LAST_PAGE + 1]:
        mid = page.width / 2
        for half in [(0, 0, mid, page.height), (mid, 0, page.width, page.height)]:
            text = page.crop(half).extract_text() or ""
            lines.extend(text.split("\n"))
    return parse_course_lines(lines)


RENAME_CATEGORY = {
    "Core": "Discipline Core",
    "Elective": "Discipline Elective",
    "(III) Open Electives": "Open Electives",
}
SKIP_CATEGORY = ("Category", "Sub-Total", "Course-work Sub-Total")
GENERAL_REQ_SOURCE = {"file": "bulletin.pdf", "page": 209}


# "6 to 9" -> (6, 9), "8" -> (8, 8), "129 (min)" -> (129, None) since "(min)" means no ceiling
def parse_range(text):
    is_min_only = "(min)" in text
    text = text.replace("(min)", "").strip()
    if " to " in text:
        low, high = text.split(" to ")
        return int(low.strip()), (None if is_min_only else int(high.strip()))
    number = int(text.strip())
    return number, (None if is_min_only else number)


def parse_general_requirements():
    pdf = pdfplumber.open(BULLETIN_PATH)
    table = pdf.pages[208].extract_tables()[0]
    rows = []
    for row in table:
        name, units, num_courses = row[0], row[1], row[2]
        if not name or units is None:
            continue
        name = " ".join(name.replace("\n", " ").split())
        units = " ".join(units.replace("\n", " ").split())
        num_courses = " ".join((num_courses or "").replace("\n", " ").split())

        if name in SKIP_CATEGORY:
            continue

        # this row is an either/or (25 units PS, or 9 to 20 units thesis) not a single range
        if "PS-I and II" in name:
            options = []
            for u, c in zip(units.split(" OR "), num_courses.split(" OR ")):
                min_u, max_u = parse_range(u)
                min_c, max_c = parse_range(c)
                options.append({"min_units": min_u, "max_units": max_u, "min_courses": min_c, "max_courses": max_c})
            rows.append({"category": "PS-I and II or Thesis", "options": options, "source": GENERAL_REQ_SOURCE})
            continue

        name = RENAME_CATEGORY.get(name, name)
        min_units, max_units = parse_range(units)
        min_courses, max_courses = parse_range(num_courses)
        rows.append({
            "category": name,
            "min_units": min_units,
            "max_units": max_units,
            "min_courses": min_courses,
            "max_courses": max_courses,
            "source": GENERAL_REQ_SOURCE,
        })
    return rows


def main():
    if os.path.exists(UNVERIFIED_PATH):
        unverified.extend(json.load(open(UNVERIFIED_PATH)))

    general = parse_general_requirements()
    courses = parse_discipline_courses()

    disciplines = set(c["discipline"] for c in courses)
    core_count = len([c for c in courses if c["category"] == "core"])
    elective_count = len([c for c in courses if c["category"] == "elective"])

    print("disciplines/pools found:", len(disciplines))
    print("core course entries:", core_count)
    print("elective course entries:", elective_count)
    print("total course entries:", len(courses))
    print("unverified entries so far:", len(unverified))

    with open("data/degree_requirements.json", "w") as f:
        json.dump({
            "general_institute_requirement": general,
            "open_elective_rule": OPEN_ELECTIVE_RULE,
            "source": {"file": "bulletin.pdf", "page": 209},
        }, f, indent=2)

    with open("data/discipline_courses.json", "w") as f:
        json.dump(courses, f, indent=2)

    with open(UNVERIFIED_PATH, "w") as f:
        json.dump(unverified, f, indent=2)


if __name__ == "__main__":
    main()
