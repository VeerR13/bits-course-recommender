import json
import os
import re
import pdfplumber

HANDOUTS_DIR = "/Users/veerraghuvanshi/Downloads/dataset/handouts"
UNVERIFIED_PATH = "data/unverified.json"

TRAILER_MARKERS = ["instructor-in-charge", "please d o not print unless necessary", "please do not print unless necessary"]

# some handouts nest fields like "1. a) Course Number: ..." / "b) Course Title: ..."
# this strips that outer numbering/lettering so the field patterns below still match
LETTERING_PREFIX = re.compile(r"^\d{0,2}\.?\s*\(?[a-h]\)\s*", re.IGNORECASE)

# a numbered heading with a colon on the same line, e.g. "9. Make-up Policy: text starts here"
HEADING_WITH_COLON = re.compile(r"^\d{1,2}\.\s*[A-Za-z][^:]{1,55}?\s*:")
# a numbered heading standing alone on its own line, e.g. "1. Course Description" - a numbered
# list item like "4. Utilize AI tools effectively" won't match since it has no colon and doesn't
# stop at 55 plain letters/spaces
HEADING_ALONE = re.compile(r"^\d{1,2}\.\s*[A-Za-z][A-Za-z /&,\-\(\)]{2,55}$")
PAGE_FOOTER = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.IGNORECASE)

# \d{0,2}\.? swallows plain numbering like "9. "; strip_lettering (below) handles "b) " style nesting
NUM_PREFIX = r"^\d{0,2}\.?\s*"
TOPIC_PATTERN = re.compile(
    NUM_PREFIX + r"(?:course\s+)?(?:description|scope\s*(?:and|&)?\s*objectiv\w*|objectiv\w*(?:\s*(?:and|&)\s*scope)?)\s*(?:of the course)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
MAKEUP_PATTERN = re.compile(NUM_PREFIX + r"make[\s\-]?up\s+policy\s*:?\s*(.*)$", re.IGNORECASE)
ATTENDANCE_PATTERN = re.compile(NUM_PREFIX + r"attendance\s+policy\s*:?\s*(.*)$", re.IGNORECASE)
COURSE_NO_LINE = re.compile(r"^course\s*(no\.?|number)\s*:?\s*(.*)$", re.IGNORECASE)
COURSE_TITLE_LINE = re.compile(r"^course\s*title\s*:?\s*(.*)$", re.IGNORECASE)
IC_LINE = re.compile(r"^instructor[\s\-]*in[\s\-]*charge\s*:?\s*(.*)$", re.IGNORECASE)
OTHER_INSTRUCTOR_LINE = re.compile(r"^(instructor\(s\)|team of instructors|instructors?)\s*:?\s*(.*)$", re.IGNORECASE)

unverified = []


def flag(rel_filename, course_code, field, reason):
    unverified.append({"file": rel_filename, "course_code": course_code, "field": field, "reason": reason})


def course_code_from_filename(filename):
    stem = filename[:-4]
    parts = stem.split("_")
    return parts[1] + " " + parts[2]


def strip_lettering(line):
    return LETTERING_PREFIX.sub("", line, count=1)


def is_boundary_line(line):
    if not line:
        return False
    if HEADING_WITH_COLON.match(line) or HEADING_ALONE.match(line) or PAGE_FOOTER.match(line):
        return True
    return line.lower() in TRAILER_MARKERS


def load_lines(pdf):
    lines = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        lines.extend(raw.strip() for raw in text.split("\n"))
    return lines


# finds every place in the document where a line matches keyword_pattern, and returns the text
# that follows each match up to the next heading. topics can have several matches (description +
# scope are often separate headings); makeup/attendance only ever need the first one.
def find_sections(lines, keyword_pattern):
    chunks = []
    used_up_to = -1
    for i, line in enumerate(lines):
        if i <= used_up_to:
            continue
        m = keyword_pattern.match(strip_lettering(line))
        if not m:
            continue
        end = len(lines)
        for j in range(i + 1, len(lines)):
            if is_boundary_line(lines[j]):
                end = j
                break
        parts = [m.group(1).strip()] if m.group(1).strip() else []
        parts.extend(l for l in lines[i + 1:end] if l)
        chunk = " ".join(" ".join(parts).split())
        if chunk:
            chunks.append(chunk)
        # end itself is the next heading line, not part of this chunk - leave it free to match too
        used_up_to = end - 1
    return chunks


def clean_name(text):
    text = re.sub(r"\[IC\]|\(IC\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[\(\[].*?@.*?[\)\]]", "", text)
    return text.strip(" :-") or None


def extract_header_fields(lines, rel_filename, course_code):
    course_no_value = None
    course_title = None
    instructor_in_charge = None
    raw_instructor_names = []

    for i, line in enumerate(lines):
        test_line = strip_lettering(line)
        m = COURSE_NO_LINE.match(test_line)
        if m and course_no_value is None:
            course_no_value = m.group(2).strip()
        m = COURSE_TITLE_LINE.match(test_line)
        if m and course_title is None:
            course_title = m.group(1).strip() or None
        m = IC_LINE.match(test_line)
        if m and instructor_in_charge is None:
            instructor_in_charge = clean_name(m.group(1))
            continue
        m = OTHER_INSTRUCTOR_LINE.match(test_line)
        if m:
            value = m.group(2).strip()
            if value and value not in ("-", "--", "N/A", "n/a"):
                raw_instructor_names.append(value)
            j = i + 1
            while j < len(lines) and lines[j].startswith(":"):
                raw_instructor_names.append(lines[j][1:].strip())
                j += 1

    other_instructors = []
    for raw_name in raw_instructor_names:
        if "[ic]" in raw_name.lower() or "(ic)" in raw_name.lower():
            if instructor_in_charge is None:
                instructor_in_charge = clean_name(raw_name)
        else:
            name = clean_name(raw_name)
            if name:
                other_instructors.append(name)

    if not course_title:
        flag(rel_filename, course_code, "course_title", "no 'Course Title' line found in the header")
    if not instructor_in_charge:
        flag(rel_filename, course_code, "instructor_in_charge", "no 'Instructor-in-Charge' line found in the header")
    if course_no_value and " ".join(course_no_value.upper().split()) != " ".join(course_code.upper().split()):
        flag(rel_filename, course_code, "course_code", "handout text says '" + course_no_value + "' but filename implies '" + course_code + "'")

    return course_title, instructor_in_charge, other_instructors


# the evaluation table's column names differ between departments, so we find the column that
# names the component (e.g. "Evaluation Component", or just "Component") by keyword instead of
# assuming a fixed position, and read every other column positionally under whatever header it has
def find_evaluation_table(pdf, rel_filename, course_code):
    found_header_without_rows = False
    for page_index, page in enumerate(pdf.pages):
        for table in page.extract_tables():
            if len(table) < 2:
                continue
            header_row = None
            header_index = None
            name_col = None
            for row_index, row in enumerate(table[:2]):
                for col_index, cell in enumerate(row):
                    low = (cell or "").replace("\n", " ").lower().strip()
                    if "component" in low and "type" not in low and name_col is None:
                        header_row, header_index, name_col = row, row_index, col_index
            if name_col is None:
                continue

            rows_out = []
            components = []
            for data_row in table[header_index + 1:]:
                if name_col >= len(data_row) or not data_row[name_col]:
                    continue
                name_clean = " ".join(data_row[name_col].replace("\n", " ").split())
                if not name_clean:
                    continue
                row_dict = {}
                for col_index, header_cell in enumerate(header_row):
                    key = " ".join((header_cell or "col_" + str(col_index)).replace("\n", " ").split())
                    value = data_row[col_index] if col_index < len(data_row) else None
                    row_dict[key] = " ".join(value.replace("\n", " ").split()) if value else None
                rows_out.append(row_dict)
                components.append(name_clean)

            if rows_out:
                return rows_out, components, page_index + 1
            # the header was there but every row under it failed to parse - keep looking, but
            # remember this so we can say why, instead of claiming no table existed at all
            found_header_without_rows = True

    if found_header_without_rows:
        flag(rel_filename, course_code, "evaluation_scheme", "an evaluation table header was found but no rows could be read from it")
    else:
        flag(rel_filename, course_code, "evaluation_scheme", "no evaluation scheme table found")
    return [], [], None


def derive_flags(components):
    joined = " | ".join(components).lower()
    return {
        "has_midsem": "mid" in joined,
        "has_compre": "compre" in joined,
        "has_project": "project" in joined,
        "has_quiz": "quiz" in joined,
        "has_lab": "lab" in joined,
    }


def parse_one_handout(filename):
    course_code = course_code_from_filename(filename)
    rel_filename = "handouts/" + filename
    pdf = pdfplumber.open(os.path.join(HANDOUTS_DIR, filename))
    lines = load_lines(pdf)

    course_title, instructor_in_charge, other_instructors = extract_header_fields(lines[:30], rel_filename, course_code)

    topic_chunks = find_sections(lines, TOPIC_PATTERN)
    if not topic_chunks:
        flag(rel_filename, course_code, "topics", "no description/scope/objective heading found")
    topics = "\n\n".join(topic_chunks) if topic_chunks else None

    makeup_chunks = find_sections(lines, MAKEUP_PATTERN)
    makeup_policy = makeup_chunks[0] if makeup_chunks else None

    attendance_chunks = find_sections(lines, ATTENDANCE_PATTERN)
    attendance_policy = attendance_chunks[0] if attendance_chunks else None

    eval_rows, components, eval_page = find_evaluation_table(pdf, rel_filename, course_code)
    eval_flags = derive_flags(components)

    record = {
        "course_code": course_code,
        "course_title": course_title,
        "instructor_in_charge": instructor_in_charge,
        "other_instructors": other_instructors,
        "evaluation_components": eval_rows,
        "makeup_policy": makeup_policy,
        "attendance_policy": attendance_policy,
        "topics": topics,
        "source": {"file": rel_filename, "page": eval_page},
    }
    record.update(eval_flags)
    return record


def main():
    if os.path.exists(UNVERIFIED_PATH):
        unverified.extend(json.load(open(UNVERIFIED_PATH)))

    filenames = sorted(f for f in os.listdir(HANDOUTS_DIR) if f.endswith(".pdf"))
    handouts = {}
    for filename in filenames:
        rel_filename = "handouts/" + filename
        try:
            handouts[rel_filename] = parse_one_handout(filename)
        except Exception as e:
            flag(rel_filename, course_code_from_filename(filename), "whole_file", "failed to parse: " + str(e))

    print("handout files found:", len(filenames))
    print("handouts parsed:", len(handouts))

    with open("data/handouts.json", "w") as f:
        json.dump(handouts, f, indent=2)
    with open(UNVERIFIED_PATH, "w") as f:
        json.dump(unverified, f, indent=2)


if __name__ == "__main__":
    main()
