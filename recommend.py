import json
import re

GENERAL_CATEGORY_TO_SHORT = {
    "Discipline Core": "CDC",
    "Discipline Elective": "DEL",
    "Humanities Electives": "HUEL",
    "Open Electives": "OPEL",
}

NO_ATTENDANCE_PHRASES = [
    "not applicable", "no attendance", "not mandatory", "not compulsory", "no minimum attendance",
]


# reads the four data files and builds the lookups every other function needs
def load_data():
    courses = json.load(open("data/courses.json"))["courses"]
    handouts = json.load(open("data/handouts.json"))
    discipline_courses = json.load(open("data/discipline_courses.json"))
    degree_requirements = json.load(open("data/degree_requirements.json"))

    courses_by_code = {}
    for c in courses:
        courses_by_code.setdefault(c["course_code"], []).append(c)

    handouts_by_code = {}
    for h in handouts.values():
        handouts_by_code.setdefault(h["course_code"], []).append(h)

    discipline_by_code = {}
    for d in discipline_courses:
        discipline_by_code.setdefault(d["course_code"], []).append(d)

    # a wrapped title sometimes lost its second line in one discipline's listing but not
    # another's, so when several copies exist we keep the longest one as the real title
    best_title = {}
    for d in discipline_courses:
        code = d["course_code"]
        if code not in best_title or len(d["title"]) > len(best_title[code]):
            best_title[code] = d["title"]

    real_disciplines = set()
    for d in discipline_courses:
        if d["discipline"] not in ("Humanities Electives", "Other Electives"):
            real_disciplines.add(d["discipline"])

    return {
        "courses": courses,
        "courses_by_code": courses_by_code,
        "handouts_by_code": handouts_by_code,
        "discipline_by_code": discipline_by_code,
        "best_title": best_title,
        "degree_requirements": degree_requirements["general_institute_requirement"],
        "open_elective_rule": degree_requirements["open_elective_rule"],
        "disciplines": sorted(real_disciplines),
    }


# CDC/DEL if it's core/elective for the student's own discipline, HUEL if it's in the bulletin's
# named "Pool of Humanities courses for first degree programmes" (PDF page 333), OPEL if it's an
# elective for some other discipline, UNKNOWN if none of that data exists for this course.
# a course from the student's own discipline is never counted as HUEL even if it is in the pool -
# that exclusion is stated on the same page 333 and is what the "not own_entries" check below does
def categorise(course_code, discipline, data):
    entries = data["discipline_by_code"].get(course_code, [])
    own_entries = [e for e in entries if e["discipline"] == discipline]

    for e in own_entries:
        if e["category"] == "core":
            return {"category": "CDC", "inferred": False}
    for e in own_entries:
        if e["category"] == "elective":
            return {"category": "DEL", "inferred": False}

    in_humanities_pool = any(e["discipline"] == "Humanities Electives" for e in entries)
    if in_humanities_pool and not own_entries:
        return {"category": "HUEL", "inferred": False}

    if any(e["category"] == "elective" for e in entries):
        return {"category": "OPEL", "inferred": False}

    return {"category": "UNKNOWN", "inferred": False}


# how many units a course carries, from the bulletin's catalog entry rather than any one
# semester's timetable offering, since a completed course may not be offered this semester
def catalog_units(course_code, data):
    for e in data["discipline_by_code"].get(course_code, []):
        if e["credits"].get("U") is not None:
            return e["credits"]["U"]
    return None


# for each general institute requirement category, how much the student has completed and how
# much is left. categories with no extracted course list (Science Foundation, Technical Arts,
# etc) are reported as not computable rather than silently shown as zero progress
def remaining_requirements(profile, data):
    discipline = profile["discipline"]
    by_short_category = {"CDC": [], "DEL": [], "HUEL": [], "OPEL": [], "UNKNOWN": []}
    for code in profile["completed_courses"]:
        info = categorise(code, discipline, data)
        by_short_category[info["category"]].append(code)

    results = []
    for req in data["degree_requirements"]:
        if "options" in req:
            results.append({"category": req["category"], "computable": False, "options": req["options"]})
            continue

        short = GENERAL_CATEGORY_TO_SHORT.get(req["category"])
        base = {
            "category": req["category"],
            "min_units": req["min_units"], "max_units": req["max_units"],
            "min_courses": req["min_courses"], "max_courses": req["max_courses"],
        }
        if short is None:
            base["computable"] = False
            base["note"] = "no course list was extracted for this category yet"
            results.append(base)
            continue

        done_codes = by_short_category[short]
        done_units = 0
        for code in done_codes:
            units = catalog_units(code, data)
            if units is not None:
                done_units += units
        base["computable"] = True
        base["completed_courses"] = done_codes
        base["completed_units"] = done_units
        base["remaining_units"] = max(0, req["min_units"] - done_units)
        base["remaining_courses"] = max(0, req["min_courses"] - len(done_codes))
        results.append(base)

    return results


# courses offered this semester, minus whatever the student has done or is doing, minus the
# com_cod >= 5000 courses unless the profile says they qualify for them
def eligible_courses(profile, data):
    taken = set(profile["completed_courses"]) | set(profile["current_courses"])
    result = []
    for c in data["courses"]:
        if c["course_code"] in taken:
            continue
        if c["com_cod"] is not None and c["com_cod"] >= 5000 and not profile.get("is_2026_admission_fd_hd_phd"):
            continue
        result.append(c)
    return result


QUERY_STOPWORDS = [
    "suggest", "courses", "course", "elective", "electives", "related", "want", "need",
    "some", "any", "with", "for", "and", "the", "to", "a", "an", "me", "i",
]

# a few acronyms expanded into the phrases that actually show up in course titles and topics -
# not a general synonym system, just enough to stop "AI" and friends from matching nothing
ACRONYM_EXPANSIONS = {
    "ai": ["artificial intelligence", "machine learning", "neural", "deep learning"],
    "ml": ["machine learning", "neural", "deep learning"],
    "nlp": ["natural language"],
    "os": ["operating system"],
    "dbms": ["database"],
}


# turns a typed query into the words actually worth searching for - drops filler words, strips
# trailing punctuation, and expands a known acronym into its real phrases instead of itself
def query_terms(topic):
    terms = []
    for word in topic.lower().split():
        word = word.strip(".,!?;:'\"()")
        if not word or word in QUERY_STOPWORDS:
            continue
        for expanded in ACRONYM_EXPANSIONS.get(word, [word]):
            if expanded not in terms:
                terms.append(expanded)
    return terms


# matches a whole word or phrase, not just a substring - "ai" must not match inside "available"
def term_in_text(term, text):
    return re.search(r"\b" + re.escape(term) + r"\b", text) is not None


# a term found in the course title counts for more than one only found in the handout's topics
# text, and each term is counted at most once - title first, topics only if the title missed it
def match_courses(courses, topic, data):
    if not topic:
        return courses
    terms = query_terms(topic)
    if not terms:
        return courses

    scored = []
    for c in courses:
        title_text = (c["title"] or "").lower()
        topics_text = ""
        handouts = data["handouts_by_code"].get(c["course_code"], [])
        if handouts and handouts[0].get("topics"):
            topics_text = handouts[0]["topics"].lower()

        score = 0
        for term in terms:
            if term_in_text(term, title_text):
                score += 3
            elif term_in_text(term, topics_text):
                score += 1
        if score > 0:
            scored.append((score, c))

    scored.sort(key=by_score, reverse=True)
    matched = []
    for score, c in scored:
        matched.append(c)
    return matched


# helper for the sort above - picks out just the score half of each (score, course) pair
def by_score(pair):
    return pair[0]


# has_midsem/has_compre/has_project/has_quiz/has_lab come straight from the handout's evaluation
# table when one exists - if there is no table, the value is unknown, never assumed false
def check_property(handout, prop_name):
    if handout is None or not handout["evaluation_components"]:
        return None, False
    return handout[prop_name], True


# attendance is free text in the data, not a yes/no field, so this is always a guess and is
# only ever used to keep courses in, never to drop one just because we lack information
def looks_attendance_free(handout):
    if handout is None or not handout.get("attendance_policy"):
        return None
    text = handout["attendance_policy"].lower()
    return any(phrase in text for phrase in NO_ATTENDANCE_PHRASES)


# the full pipeline: what's required, what's eligible, what category it is, does it match the
# topic, do its properties fit - academic validity is decided before the topic is ever looked at
def recommend(profile, filters, data):
    req_status = remaining_requirements(profile, data)
    remaining_by_category = {}
    for r in req_status:
        if r.get("computable"):
            short = GENERAL_CATEGORY_TO_SHORT.get(r["category"])
            if short:
                remaining_by_category[short] = r

    eligible = eligible_courses(profile, data)

    wanted_category = filters.get("category")
    category_info = {}
    category_filtered = []
    for course in eligible:
        info = categorise(course["course_code"], profile["discipline"], data)
        category_info[course["course_code"]] = info
        if wanted_category and info["category"] != wanted_category:
            continue
        category_filtered.append(course)

    matched = match_courses(category_filtered, filters.get("topic"), data)

    results = []
    for course in matched:
        code = course["course_code"]
        info = category_info[code]
        handouts = data["handouts_by_code"].get(code, [])
        handout = handouts[0] if handouts else None

        properties = {}
        drop = False
        for prop in ("has_midsem", "has_compre", "has_project", "has_quiz", "has_lab"):
            value, verified = check_property(handout, prop)
            properties[prop] = {"value": value, "verified": verified}
            wanted = filters.get(prop)
            if wanted is not None and verified and value != wanted:
                drop = True
        if drop:
            continue

        attendance_guess = looks_attendance_free(handout)
        if filters.get("attendance_free") and attendance_guess is False:
            continue  # only drop when the text actively suggests attendance IS required
        properties["attendance_free"] = {"value": attendance_guess, "verified": False}

        req = remaining_by_category.get(info["category"])
        satisfies = info["category"] if (req and req["remaining_courses"] > 0) else None

        results.append({
            "course_code": code,
            "title": course["title"] or data["best_title"].get(code),
            "category": info["category"],
            "category_inferred": info["inferred"],
            "satisfies_requirement": satisfies,
            "units": course["credits"].get("units"),
            "properties": properties,
            "attendance_policy_text": handout["attendance_policy"] if handout else None,
            "makeup_policy_text": handout["makeup_policy"] if handout else None,
            "prerequisites_checked": False,
            "handout_available": handout is not None,
            "sources": {
                "timetable": course["source"],
                "handout": handout["source"] if handout else None,
            },
        })

    # a course we could actually verify the requested property on should outrank a guess, which
    # should outrank a course with no signal at all - without ever dropping the last two
    requested_props = []
    for prop in ("has_midsem", "has_compre", "has_project", "has_quiz", "has_lab"):
        if filters.get(prop) is not None:
            requested_props.append(prop)
    if filters.get("attendance_free"):
        requested_props.append("attendance_free")

    if requested_props:
        verified_first = []
        guessed = []
        no_signal = []
        for res in results:
            all_verified = True
            any_guess = False
            for prop in requested_props:
                entry = res["properties"][prop]
                if not entry["verified"]:
                    all_verified = False
                    if entry["value"] is True:
                        any_guess = True
            if all_verified:
                verified_first.append(res)
            elif any_guess:
                guessed.append(res)
            else:
                no_signal.append(res)
        results = verified_first + guessed + no_signal

    return results
