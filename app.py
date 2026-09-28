import json
import os
import streamlit as st
import recommend as rec

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None

st.set_page_config(page_title="BITS Course Recommender", layout="wide")


# load the JSON data once per session instead of on every rerun
@st.cache_resource
def get_data():
    return rec.load_data()


data = get_data()

PROPERTY_LABELS = {
    "has_midsem": "midsem",
    "has_compre": "compre",
    "has_project": "project component",
    "has_quiz": "quiz",
    "has_lab": "lab component",
    "attendance_free": "no attendance requirement",
}


# picks a current Gemini model instead of trusting a name that might have been retired
def pick_model(client):
    try:
        for m in client.models.list():
            name = m.name.replace("models/", "")
            if "flash" in name and "generateContent" in (m.supported_actions or []):
                return name
    except Exception:
        pass
    return "gemini-2.5-flash"


PROMPT_TEMPLATE = (
    "Turn this course-selection question into a JSON object with only the keys that apply: "
    "category (one of CDC, DEL, HUEL, OPEL), topic (a short string), has_midsem, has_compre, "
    "has_project, has_quiz, has_lab, attendance_free (these six are all true or false). "
    "Leave out any key the question does not mention. Question: "
)


# turns a typed question into a filter dict using Gemini. returns None on any problem at all -
# missing key, network error, bad JSON - so the caller can fall back to the plain widgets
def ask_gemini(question):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or genai is None:
        return None
    try:
        client = genai.Client(api_key=api_key)
        model = pick_model(client)
        response = client.models.generate_content(
            model=model,
            contents=PROMPT_TEMPLATE + question,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        return json.loads(response.text)
    except Exception:
        return None


def all_known_course_codes():
    codes = set(data["courses_by_code"].keys()) | set(data["discipline_by_code"].keys())
    return sorted(codes)


st.title("BITS Course Recommender")
st.caption("Recommendations are computed live from the parsed timetable, handouts, and bulletin - nothing here is hardcoded.")

with st.sidebar:
    st.header("Your Profile")
    with st.form("profile_form"):
        campus = st.text_input("Campus", value=st.session_state.get("campus", "Pilani"))
        admission_year = st.number_input("Admission year", min_value=2018, max_value=2026, value=st.session_state.get("admission_year", 2023))
        degree = st.selectbox("Degree", ["B.E.", "B.Pharm.", "M.Sc.", "Higher Degree"], index=0)
        dual_degree = st.checkbox("Dual degree", value=st.session_state.get("dual_degree", False))
        discipline = st.selectbox("Discipline (major)", data["disciplines"])
        current_semester = st.number_input("Current semester", min_value=1, max_value=12, value=st.session_state.get("current_semester", 3))
        minor = st.text_input("Minor (if any)", value=st.session_state.get("minor", ""))
        st.caption("Minor programme rules were not extracted from the bulletin, so minor requirements are not checked.")
        interests = st.text_input("Interests", value=st.session_state.get("interests", ""))
        completed_courses = st.multiselect("Completed courses", all_known_course_codes(), default=st.session_state.get("completed_courses", []))
        current_courses = st.multiselect("Currently taking", all_known_course_codes(), default=st.session_state.get("current_courses", []))
        is_2026_fdhdphd = st.checkbox("2026 admission into FD/HD/PhD (unlocks com cod >= 5000 courses)", value=st.session_state.get("is_2026_fdhdphd", False))
        saved = st.form_submit_button("Save profile")

    if saved:
        st.session_state["campus"] = campus
        st.session_state["admission_year"] = admission_year
        st.session_state["degree"] = degree
        st.session_state["dual_degree"] = dual_degree
        st.session_state["discipline"] = discipline
        st.session_state["current_semester"] = current_semester
        st.session_state["minor"] = minor
        st.session_state["interests"] = interests
        st.session_state["completed_courses"] = completed_courses
        st.session_state["current_courses"] = current_courses
        st.session_state["is_2026_fdhdphd"] = is_2026_fdhdphd
        st.session_state["profile_saved"] = True

if not st.session_state.get("profile_saved"):
    st.info("Fill in your profile in the sidebar and click Save profile to get started.")
    st.stop()

profile = {
    "discipline": st.session_state["discipline"],
    "completed_courses": st.session_state["completed_courses"],
    "current_courses": st.session_state["current_courses"],
    "is_2026_admission_fd_hd_phd": st.session_state["is_2026_fdhdphd"],
}

st.subheader("Remaining requirements")
st.caption("Prerequisites are not present in the supplied data, so eligibility below does not check them.")

req_rows = rec.remaining_requirements(profile, data)
for row in req_rows:
    if "options" in row:
        st.write("**" + row["category"] + "**: either/or requirement, shown as printed in the bulletin, not tracked as progress")
        continue
    if not row.get("computable"):
        st.write("**" + row["category"] + "**: " + str(row["min_units"]) + "-" + str(row["max_units"] if row["max_units"] is not None else "?") + " units - could not be verified (no course list was extracted for this category)")
        continue
    st.write(
        "**" + row["category"] + "**: " + str(row["completed_units"]) + "/" + str(row["min_units"]) + " units done, "
        + str(row["remaining_units"]) + " units and " + str(row["remaining_courses"]) + " courses still needed"
    )

st.divider()
st.subheader("Ask for a recommendation")

question = st.text_input("Ask a question", placeholder="e.g. suggest DELs related to AI with no midsem")

st.write("Or set filters directly:")
col1, col2 = st.columns(2)
with col1:
    widget_category = st.selectbox("Category", ["(any)", "CDC", "DEL", "HUEL", "OPEL"])
    widget_topic = st.text_input("Topic keywords", value="")
with col2:
    widget_no_midsem = st.checkbox("No midsem")
    widget_project = st.checkbox("Has a project component")
    widget_quiz = st.checkbox("Has a quiz")
    widget_no_attendance = st.checkbox("No attendance requirement")

search = st.button("Find courses")

if search:
    filters = None
    if question.strip():
        filters = ask_gemini(question)

    if filters is None:
        filters = {}
        if widget_category != "(any)":
            filters["category"] = widget_category
        if widget_topic.strip():
            filters["topic"] = widget_topic.strip()
        if widget_no_midsem:
            filters["has_midsem"] = False
        if widget_project:
            filters["has_project"] = True
        if widget_quiz:
            filters["has_quiz"] = True
        if widget_no_attendance:
            filters["attendance_free"] = True

    results = rec.recommend(profile, filters, data)
    st.write(str(len(results)) + " result(s)")

    for r in results:
        title = str(r["course_code"]) + " - " + str(r["title"])
        if not r["handout_available"]:
            title += "  [NO HANDOUT DATA]"
        with st.expander(title):
            category_line = "Category: " + r["category"]
            if r["category_inferred"]:
                category_line += " (inferred from department, not a verified list - the bulletin does not name exact course codes for this category)"
            st.write(category_line)
            if r["satisfies_requirement"]:
                st.write("Satisfies your remaining requirement for: " + r["satisfies_requirement"])
            st.write("Units: " + str(r["units"]))

            # "verified" means the handout's own table says so - anything else is a guess or a
            # blank, and must be labelled plainly so it never reads the same as a real answer
            for prop_name, label in PROPERTY_LABELS.items():
                entry = r["properties"].get(prop_name)
                if entry is None:
                    continue
                if entry["verified"]:
                    st.write(label + ": " + str(entry["value"]) + "  [verified from handout]")
                elif entry["value"] is True:
                    st.write(label + ": possibly  [based on policy text, not verified]")
                else:
                    st.write(label + ": not verified")

            if r["attendance_policy_text"]:
                st.caption("Attendance policy text: " + r["attendance_policy_text"])
            if r["makeup_policy_text"]:
                st.caption("Makeup policy text: " + r["makeup_policy_text"])
            if not r["handout_available"]:
                st.warning("No handout was found for this course, so none of its properties could be verified.")

            st.caption("Prerequisites: not checked - the supplied data does not contain prerequisite information.")

            source_bits = []
            if r["sources"]["timetable"]:
                source_bits.append("timetable p." + str(r["sources"]["timetable"]["page"]))
            if r["sources"]["handout"]:
                source_bits.append(r["sources"]["handout"]["file"] + " p." + str(r["sources"]["handout"]["page"]))
            if source_bits:
                st.caption("Source: " + ", ".join(source_bits))
