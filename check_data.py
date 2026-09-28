import json

courses_data = json.load(open("data/courses.json"))
handouts_data = json.load(open("data/handouts.json"))
discipline_courses = json.load(open("data/discipline_courses.json"))
unverified = json.load(open("data/unverified.json"))

courses = courses_data["courses"]

print("===== counts =====")
distinct_codes = set()
total_sections = 0
for c in courses:
    distinct_codes.add(c["course_code"])
    total_sections += len(c["sections"])

print("course records (one per com_cod offering):", len(courses))
print("distinct course codes:", len(distinct_codes))
print("total section rows:", total_sections)
print("handouts parsed:", len(handouts_data))

print()
print("===== timetable vs handout coverage =====")
handout_codes = set()
for filename, rec in handouts_data.items():
    handout_codes.add(rec["course_code"])

timetable_only = distinct_codes - handout_codes
handout_only = handout_codes - distinct_codes
print("timetable course codes with no matching handout:", len(timetable_only))
print("handout course codes with no matching timetable entry:", len(handout_only))

print()
print("===== has_midsem sanity check =====")
no_midsem = 0
for filename, rec in handouts_data.items():
    if not rec["has_midsem"]:
        no_midsem += 1
print("handouts with has_midsem = False:", no_midsem, "out of", len(handouts_data))

print()
print("===== bulletin discipline courses =====")
disciplines = set(c["discipline"] for c in discipline_courses)
core_count = len([c for c in discipline_courses if c["category"] == "core"])
elective_count = len([c for c in discipline_courses if c["category"] == "elective"])
print("disciplines/pools:", len(disciplines))
print("core course entries:", core_count)
print("elective course entries:", elective_count)

print()
print("===== unverified.json summary =====")
by_reason = {}
for entry in unverified:
    field = entry["field"]
    by_reason[field] = by_reason.get(field, 0) + 1
print("total unverified entries:", len(unverified))
for field in sorted(by_reason):
    print(" ", field, ":", by_reason[field])

print()
print("===== five example course records =====")
count = 0
for c in courses:
    if count >= 5:
        break
    print(json.dumps(c, indent=2))
    print()
    count += 1
