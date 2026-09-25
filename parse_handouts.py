import json
import os
import re
import pdfplumber

HANDOUTS_DIR = "/Users/veerraghuvanshi/Downloads/dataset/handouts"
OUT_HANDOUTS = "data/handouts.json"
UNVERIFIED_PATH = "data/unverified.json"

TRAILER_MARKERS = [
    "instructor-in-charge",
    "please d o not print unless necessary",
    "please do not print unless necessary",
]

# some handouts nest fields like "1. a) Course Number: ..." / "b) Course Title: ..."
# this strips that outer numbering/lettering so the field patterns below still match
LETTERING_PREFIX = re.compile(r"^\d{0,2}\.?\s*\(?[a-h]\)\s*", re.IGNORECASE)


def strip_lettering(line):
    return LETTERING_PREFIX.sub("", line, count=1)

# a numbered heading with a colon on the same line, e.g. "9. Make-up Policy: text starts here"
HEADING_WITH_COLON = re.compile(r"^\d{1,2}\.\s*([A-Za-z][^:]{1,55}?)\s*:\s*(.*)$")
# a numbered heading standing alone on its own line, e.g. "1. Course Description"
HEADING_ALONE = re.compile(r"^\d{1,2}\.\s*([A-Za-z][A-Za-z /&,\-\(\)]{2,55})$")
PAGE_FOOTER = re.compile(r"^page\s+\d+\s+of\s+\d+$", re.IGNORECASE)

unverified = []


def flag(file, course_code, field, reason):
    unverified.append({"file": file, "course_code": course_code, "field": field, "reason": reason})


def course_code_from_filename(filename):
    stem = filename[:-4]
    parts = stem.split("_")
    dept = parts[1]
    code = parts[2]
    return dept + " " + code


def is_boundary_line(stripped_line):
    if not stripped_line:
        return False
    if HEADING_WITH_COLON.match(stripped_line):
        return True
    if HEADING_ALONE.match(stripped_line):
        return True
    if PAGE_FOOTER.match(stripped_line):
        return True
    low = stripped_line.lower().strip()
    for marker in TRAILER_MARKERS:
        if low == marker:
            return True
    return False


def load_lines(pdf):
    lines = []
    for page in pdf.pages:
        text = page.extract_text() or ""
        for raw_line in text.split("\n"):
            lines.append(raw_line.strip())
    return lines


# looks for the first line whose start matches keyword_pattern (a compiled regex), whether or not
# it starts with a heading number, and returns the joined text up to the next boundary line
def extract_section(lines, keyword_pattern, rel_filename, course_code, field_name):
    start_index = None
    same_line_content = ""
    for i, line in enumerate(lines):
        m = keyword_pattern.match(strip_lettering(line))
        if m:
            start_index = i
            same_line_content = m.group(1).strip() if m.groups() else ""
            break

    if start_index is None:
        return None

    end_index = len(lines)
    for j in range(start_index + 1, len(lines)):
        if is_boundary_line(lines[j]):
            end_index = j
            break

    body_lines = lines[start_index + 1:end_index]
    parts = []
    if same_line_content:
        parts.append(same_line_content)
    parts.extend([l for l in body_lines if l])
    body = " ".join(parts)
    body = " ".join(body.split())

    if not body:
        flag(rel_filename, course_code, field_name, "heading found but no text followed before the next section")
        return None
    if len(body) < 15:
        flag(rel_filename, course_code, field_name, "extracted text looks too short, may be cut off: " + repr(body))

    return body


TOPIC_PATTERN = re.compile(
    r"^\d{0,2}\.?\s*(?:course\s+)?(?:description|scope\s*(?:and|&)?\s*objectiv\w*|objectiv\w*(?:\s*(?:and|&)\s*scope)?)\s*(?:of the course)?\s*:?\s*(.*)$",
    re.IGNORECASE,
)
MAKEUP_PATTERN = re.compile(r"^\d{0,2}\.?\s*make[\s\-]?up\s+policy\s*:?\s*(.*)$", re.IGNORECASE)
ATTENDANCE_PATTERN = re.compile(r"^\d{0,2}\.?\s*attendance\s+policy\s*:?\s*(.*)$", re.IGNORECASE)


def extract_topics(lines, rel_filename, course_code):
    found = []
    seen_starts = set()
    for i, line in enumerate(lines):
        if i in seen_starts:
            continue
        m = TOPIC_PATTERN.match(strip_lettering(line))
        if not m:
            continue
        same_line_content = m.group(1).strip()
        end_index = len(lines)
        for j in range(i + 1, len(lines)):
            if is_boundary_line(lines[j]):
                end_index = j
                break
        body_lines = lines[i + 1:end_index]
        parts = []
        if same_line_content:
            parts.append(same_line_content)
        parts.extend([l for l in body_lines if l])
        chunk = " ".join(parts)
        chunk = " ".join(chunk.split())
        if chunk:
            found.append(chunk)
        for k in range(i, end_index):
            seen_starts.add(k)

    if not found:
        flag(rel_filename, course_code, "topics", "no description/scope/objective heading found")
        return None

    topics = "\n\n".join(found)
    if len(topics) < 15:
        flag(rel_filename, course_code, "topics", "extracted topics text looks too short: " + repr(topics))
    return topics


COURSE_NO_LINE = re.compile(r"^course\s*(no\.?|number)\s*:?\s*(.*)$", re.IGNORECASE)
COURSE_TITLE_LINE = re.compile(r"^course\s*title\s*:?\s*(.*)$", re.IGNORECASE)
IC_LINE = re.compile(r"^instructor[\s\-]*in[\s\-]*charge\s*:?\s*(.*)$", re.IGNORECASE)
OTHER_INSTRUCTOR_LINE = re.compile(r"^(instructor\(s\)|team of instructors|instructors?)\s*:?\s*(.*)$", re.IGNORECASE)


def clean_name(text):
    text = re.sub(r"\[IC\]", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(IC\)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\(.*?@.*?\)", "", text)
    text = re.sub(r"\[.*?@.*?\]", "", text)
    text = text.strip(" :-")
    return text if text else None


def extract_header_fields(header_lines, rel_filename, course_code):
    course_no_value = None
    course_title = None
    instructor_in_charge = None
    other_instructors = []

    raw_instructor_names = []

    for i, line in enumerate(header_lines):
        test_line = strip_lettering(line)
        if course_no_value is None:
            m = COURSE_NO_LINE.match(test_line)
            if m:
                course_no_value = m.group(2).strip()
        if course_title is None:
            m = COURSE_TITLE_LINE.match(test_line)
            if m:
                course_title = m.group(1).strip() or None
        if instructor_in_charge is None:
            m = IC_LINE.match(test_line)
            if m:
                instructor_in_charge = clean_name(m.group(1))
        m = OTHER_INSTRUCTOR_LINE.match(test_line)
        if m and not IC_LINE.match(test_line):
            value = m.group(2).strip()
            if value and value not in ("-", "--", "N/A", "n/a"):
                raw_instructor_names.append(value)
            # continuation lines for a wrapped instructor list start with a lone ':'
            j = i + 1
            while j < len(header_lines) and header_lines[j].startswith(":"):
                cont = header_lines[j][1:].strip()
                if cont:
                    raw_instructor_names.append(cont)
                j += 1

    # a name tagged [IC] or (IC) in a combined "Instructors :" list is the instructor-in-charge, not a co-instructor
    for raw_name in raw_instructor_names:
        low_name = raw_name.lower()
        if "[ic]" in low_name or "(ic)" in low_name:
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

    if course_no_value:
        normalized = " ".join(course_no_value.upper().split())
        expected = " ".join(course_code.upper().split())
        if normalized != expected:
            flag(rel_filename, course_code, "course_code", "handout text says '" + course_no_value + "' but filename implies '" + course_code + "'")

    return course_title, instructor_in_charge, other_instructors


COMPONENT_HEADER_WORDS = {
    "component": "component",
    "weight": "weightage",
    "duration": "duration",
    "date": "date",
    "s.no": "sno",
}


def find_evaluation_table(pdf, rel_filename, course_code):
    for page_index, page in enumerate(pdf.pages):
        tables = page.extract_tables()
        for table in tables:
            if len(table) < 2:
                continue
            header_end = None
            name_col = None
            for row_index in (0, 1):
                if row_index >= len(table):
                    break
                row = table[row_index]
                for col_index, cell in enumerate(row):
                    if not cell:
                        continue
                    low = cell.replace("\n", " ").lower().strip()
                    if "weightage" in low or low == "weight" or "duration" in low:
                        header_end = row_index
                    if "component" in low and "type" not in low and name_col is None:
                        name_col = col_index
                        header_end = row_index
            if name_col is None or header_end is None:
                continue

            header_row = table[header_end]
            weight_col = None
            for col_index, cell in enumerate(header_row):
                if cell and "weight" in cell.lower():
                    weight_col = col_index

            rows_out = []
            components = []
            misaligned_seen = False
            for data_row in table[header_end + 1:]:
                if name_col >= len(data_row):
                    continue
                name_cell = data_row[name_col]
                if not name_cell:
                    continue
                name_clean = " ".join(name_cell.replace("\n", " ").split())
                if not name_clean:
                    continue
                row_dict = {}
                if len(header_row) == len(data_row):
                    for col_index, header_cell in enumerate(header_row):
                        key = header_cell.replace("\n", " ").strip() if header_cell else ("col_" + str(col_index))
                        value = data_row[col_index]
                        value_clean = " ".join(value.replace("\n", " ").split()) if value else None
                        row_dict[key] = value_clean
                else:
                    flag(rel_filename, course_code, "evaluation_scheme", "header and row column counts do not match, storing row positionally")
                    for col_index, value in enumerate(data_row):
                        value_clean = " ".join(value.replace("\n", " ").split()) if value else None
                        row_dict["col_" + str(col_index)] = value_clean
                rows_out.append(row_dict)
                components.append(name_clean)

                if weight_col is not None and not misaligned_seen:
                    weight_value = data_row[weight_col] if weight_col < len(data_row) else None
                    row_text = " ".join([v for v in data_row if v])
                    if not weight_value and "%" in row_text:
                        flag(rel_filename, course_code, "evaluation_scheme", "weightage column looks misaligned, values stored positionally may be shifted")
                        misaligned_seen = True

            return rows_out, components, page_index + 1

    flag(rel_filename, course_code, "evaluation_scheme", "no evaluation scheme table found")
    return [], [], None


def derive_flags(components):
    joined = " | ".join(components).lower()
    return {
        "has_midsem": "mid" in joined or "midsem" in joined,
        "has_compre": "compre" in joined,
        "has_project": "project" in joined,
        "has_quiz": "quiz" in joined,
        "has_lab": "lab" in joined,
    }


def parse_one_handout(filename):
    course_code = course_code_from_filename(filename)
    rel_filename = "handouts/" + filename
    full_path = os.path.join(HANDOUTS_DIR, filename)

    pdf = pdfplumber.open(full_path)
    lines = load_lines(pdf)
    header_lines = lines[:30]

    course_title, instructor_in_charge, other_instructors = extract_header_fields(header_lines, rel_filename, course_code)
    topics = extract_topics(lines, rel_filename, course_code)
    makeup_policy = extract_section(lines, MAKEUP_PATTERN, rel_filename, course_code, "makeup_policy")
    attendance_policy = extract_section(lines, ATTENDANCE_PATTERN, rel_filename, course_code, "attendance_policy")

    eval_rows, components, eval_page = find_evaluation_table(pdf, rel_filename, course_code)
    eval_flags = derive_flags(components)

    record = {
        "course_code": course_code,
        "course_title": course_title,
        "instructor_in_charge": instructor_in_charge,
        "other_instructors": other_instructors,
        "evaluation_components": eval_rows,
        "has_midsem": eval_flags["has_midsem"],
        "has_compre": eval_flags["has_compre"],
        "has_project": eval_flags["has_project"],
        "has_quiz": eval_flags["has_quiz"],
        "has_lab": eval_flags["has_lab"],
        "makeup_policy": makeup_policy,
        "attendance_policy": attendance_policy,
        "topics": topics,
        "source": {"file": rel_filename, "page": eval_page},
    }
    return record


def main():
    if os.path.exists(UNVERIFIED_PATH):
        with open(UNVERIFIED_PATH) as f:
            existing = json.load(f)
        unverified.extend(existing)

    filenames = sorted(f for f in os.listdir(HANDOUTS_DIR) if f.endswith(".pdf"))
    handouts = {}
    for filename in filenames:
        try:
            record = parse_one_handout(filename)
        except Exception as e:
            flag("handouts/" + filename, course_code_from_filename(filename), "whole_file", "failed to parse: " + str(e))
            continue
        handouts[filename] = record

    print("handout files found:", len(filenames))
    print("handouts parsed:", len(handouts))

    with open(OUT_HANDOUTS, "w") as f:
        json.dump(handouts, f, indent=2)

    with open(UNVERIFIED_PATH, "w") as f:
        json.dump(unverified, f, indent=2)


if __name__ == "__main__":
    main()
