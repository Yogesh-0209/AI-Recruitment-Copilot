import streamlit as st
import json
import os
import tempfile
import re

# ============================================================
# PROJECT IMPORTS
# ============================================================

from modules.resume_parser.file_loader import extract_text

from modules.resume_parser.extractor import (
    extract_name,
    extract_email,
    extract_phone,
    extract_skills
)

from modules.resume_parser.section_parser import extract_sections


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="AI Recruitment Copilot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown("""
<style>

.main-title {
    font-size: 38px;
    font-weight: 700;
    margin-bottom: 5px;
}

.subtitle {
    color: #8b949e;
    font-size: 17px;
    margin-bottom: 30px;
}

.section-title {
    font-size: 24px;
    font-weight: 650;
    margin-top: 25px;
}

.profile-card {
    padding: 20px;
    border-radius: 12px;
    background-color: #161b22;
    border: 1px solid #30363d;
    margin-bottom: 20px;
}

.skill {
    display: inline-block;
    padding: 6px 12px;
    margin: 4px;
    border-radius: 15px;
    background-color: #1f6feb;
    color: white;
    font-size: 14px;
}

</style>
""", unsafe_allow_html=True)


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title("🤖 Recruitment Copilot")

    st.divider()

    st.subheader("Navigation")

    st.write("📊 Dashboard")
    st.write("📄 Resume Upload")
    st.write("👥 Candidates")
    st.write("💼 Job Postings")
    st.write("📈 Analytics")
    st.write("⚙️ Settings")

    st.divider()

    st.caption("AI-Driven Smart Hiring Platform")
    st.caption("Resume Parsing & Candidate Profiling")


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">Resume Parsing & Candidate Profiling</div>',
    unsafe_allow_html=True
)

st.markdown(
    '<div class="subtitle">'
    'Upload and process resumes to create structured candidate profiles'
    '</div>',
    unsafe_allow_html=True
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def ensure_list(value):
    """
    Converts different possible values into a proper list.

    This prevents the character-by-character problem in Streamlit.
    """

    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, str):

        value = value.strip()

        if not value:
            return []

        # If comma-separated
        if "," in value:
            return [
                item.strip()
                for item in value.split(",")
                if item.strip()
            ]

        return [value]

    return [str(value)]


def clean_list(value):
    """
    Removes empty values and duplicates while preserving order.
    """

    items = ensure_list(value)

    result = []
    seen = set()

    for item in items:

        item = str(item).strip()

        if not item:
            continue

        key = re.sub(r"\s+", " ", item.lower())

        if key not in seen:
            result.append(item)
            seen.add(key)

    return result


def normalize_text(value):
    """
    Normalize text before comparison.
    """

    if value is None:
        return ""

    value = str(value).lower().strip()

    value = re.sub(r"\s+", " ", value)

    value = re.sub(r"[^\w\s@.+#-]", "", value)

    return value


def field_match(actual, expected):
    """
    Compare one field.

    For lists:
    - order does not matter
    - expected values are checked against extracted values

    For strings:
    - normalized exact comparison
    """

    if isinstance(expected, list):

        expected_items = {
            normalize_text(x)
            for x in expected
            if normalize_text(x)
        }

        actual_items = {
            normalize_text(x)
            for x in ensure_list(actual)
            if normalize_text(x)
        }

        if not expected_items:
            return True

        if not actual_items:
            return False

        matched = expected_items.intersection(actual_items)

        # Recall of expected information
        score = len(matched) / len(expected_items)

        return score >= 0.95

    return normalize_text(actual) == normalize_text(expected)


def calculate_accuracy(actual, expected):
    """
    Calculate field-level extraction accuracy.

    Eight fields are evaluated:
    name, email, phone, education, skills,
    experience, certifications, projects
    """

    fields = [
        "name",
        "email",
        "phone",
        "education",
        "skills",
        "experience",
        "certifications",
        "projects"
    ]

    correct = 0
    results = {}

    for field in fields:

        expected_value = expected.get(field)
        actual_value = actual.get(field)

        matched = field_match(actual_value, expected_value)

        results[field] = matched

        if matched:
            correct += 1

    accuracy = (correct / len(fields)) * 100

    return accuracy, correct, len(fields), results


def load_ground_truth():
    """
    Load expected_profiles.json.
    """

    possible_paths = [
        "expected_profiles.json",
        os.path.join(
            os.path.dirname(__file__),
            "expected_profiles.json"
        )
    ]

    for path in possible_paths:

        if os.path.exists(path):

            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8"
                ) as file:

                    return json.load(file)

            except Exception as error:

                st.warning(
                    f"Could not read expected_profiles.json: {error}"
                )

                return {}

    return {}


def find_ground_truth(filename, ground_truth):
    """
    Find expected profile for uploaded resume.
    """

    if not ground_truth:
        return None

    # Direct filename match
    if filename in ground_truth:
        return ground_truth[filename]

    # Try without path
    base_name = os.path.basename(filename)

    if base_name in ground_truth:
        return ground_truth[base_name]

    # Try case-insensitive comparison
    filename_lower = base_name.lower()

    for key, value in ground_truth.items():

        if os.path.basename(str(key)).lower() == filename_lower:
            return value

    return None


def build_candidate_profile(text):
    """
    Complete resume extraction pipeline.
    """

    # --------------------------------------------------------
    # Basic candidate information
    # --------------------------------------------------------

    name = extract_name(text)
    email = extract_email(text)
    phone = extract_phone(text)
    skills = extract_skills(text)

    # --------------------------------------------------------
    # Resume sections
    # --------------------------------------------------------

    sections = extract_sections(text)

    education = clean_list(
        sections.get("education", [])
    )

    experience = clean_list(
        sections.get("experience", [])
    )

    certifications = clean_list(
        sections.get("certifications", [])
    )

    projects = clean_list(
        sections.get("projects", [])
    )

    skills = clean_list(skills)

    # --------------------------------------------------------
    # Final structured candidate profile
    # --------------------------------------------------------

    profile = {
        "name": name,
        "email": email,
        "phone": phone,
        "education": education,
        "skills": skills,
        "experience": experience,
        "certifications": certifications,
        "projects": projects
    }

    return profile


# ============================================================
# RESUME UPLOAD
# ============================================================

st.markdown(
    '<div class="section-title">📄 Upload Resume</div>',
    unsafe_allow_html=True
)

uploaded_file = st.file_uploader(
    "Upload a candidate resume",
    type=["pdf", "docx"],
    help="Supported formats: PDF and DOCX"
)


# ============================================================
# PROCESS RESUME
# ============================================================

if uploaded_file is not None:

    file_name = uploaded_file.name

    file_extension = os.path.splitext(file_name)[1].lower()

    # --------------------------------------------------------
    # File information
    # --------------------------------------------------------

    st.success(
        f"Resume uploaded successfully: {file_name}"
    )

    col1, col2, col3 = st.columns(3)

    with col1:

        st.markdown("### File Name")
        st.write(file_name)

    with col2:

        st.markdown("### Format")

        if file_extension == ".pdf":
            st.write("PDF")
        else:
            st.write("DOCX")

    with col3:

        st.markdown("### Size")

        size_kb = uploaded_file.size / 1024

        st.write(f"{size_kb:.1f} KB")


    # --------------------------------------------------------
    # Save uploaded file temporarily
    # --------------------------------------------------------

    temp_path = None

    try:

        with tempfile.NamedTemporaryFile(
            delete=False,
            suffix=file_extension
        ) as temp_file:

            temp_file.write(
                uploaded_file.getbuffer()
            )

            temp_path = temp_file.name


        # ----------------------------------------------------
        # Extract raw resume text
        # ----------------------------------------------------

        with st.spinner("Parsing resume..."):

            text = extract_text(temp_path)


        if not text or not text.strip():

            st.error(
                "No text could be extracted from this resume."
            )

            st.stop()


        # ----------------------------------------------------
        # Build structured candidate profile
        # ----------------------------------------------------

        with st.spinner("Extracting candidate information..."):

            candidate_profile = build_candidate_profile(text)


        # ====================================================
        # CANDIDATE INFORMATION
        # ====================================================

        st.divider()

        st.markdown(
            '<div class="section-title">'
            '👤 Candidate Information'
            '</div>',
            unsafe_allow_html=True
        )

        col1, col2, col3 = st.columns(3)

        with col1:

            st.markdown("**Name**")

            st.write(
                candidate_profile["name"]
                or "Not detected"
            )

        with col2:

            st.markdown("**Email**")

            st.write(
                candidate_profile["email"]
                or "Not detected"
            )

        with col3:

            st.markdown("**Phone**")

            st.write(
                candidate_profile["phone"]
                or "Not detected"
            )


        # ====================================================
        # STRUCTURED PROFILE
        # ====================================================

        st.divider()

        st.markdown(
            '<div class="section-title">'
            '📋 Structured Candidate Profile'
            '</div>',
            unsafe_allow_html=True
        )


        # ----------------------------------------------------
        # Education
        # ----------------------------------------------------

        st.markdown("### 🎓 Education")

        education = candidate_profile["education"]

        if education:

            for item in education:
                st.write(f"• {item}")

        else:

            st.info("Education information not detected.")


        # ----------------------------------------------------
        # Experience
        # ----------------------------------------------------

        st.markdown("### 💼 Experience")

        experience = candidate_profile["experience"]

        if experience:

            for item in experience:
                st.write(f"• {item}")

        else:

            st.info("Experience information not detected.")


        # ----------------------------------------------------
        # Certifications
        # ----------------------------------------------------

        st.markdown("### 📜 Certifications")

        certifications = candidate_profile["certifications"]

        if certifications:

            for item in certifications:
                st.write(f"• {item}")

        else:

            st.info("Certification information not detected.")


        # ----------------------------------------------------
        # Projects
        # ----------------------------------------------------

        st.markdown("### 🚀 Projects")

        projects = candidate_profile["projects"]

        if projects:

            for item in projects:
                st.write(f"• {item}")

        else:

            st.info("Project information not detected.")


        # ----------------------------------------------------
        # Skills
        # ----------------------------------------------------

        st.markdown("### 🧠 Skills")

        skills = candidate_profile["skills"]

        if skills:

            skill_html = ""

            for skill in skills:

                skill_html += (
                    f'<span class="skill">{skill}</span>'
                )

            st.markdown(
                skill_html,
                unsafe_allow_html=True
            )

        else:

            st.info("Skills not detected.")


        # ====================================================
        # ACCURACY VALIDATION
        # ====================================================

        st.divider()

        st.markdown(
            '<div class="section-title">'
            '📊 Resume Extraction Validation'
            '</div>',
            unsafe_allow_html=True
        )

        ground_truth = load_ground_truth()

        expected_profile = find_ground_truth(
            file_name,
            ground_truth
        )


        if expected_profile is None:

            st.warning(
                f"Accuracy validation is not available for "
                f"`{file_name}`."
            )

            st.info(
                "This resume does not have a corresponding "
                "ground-truth entry in expected_profiles.json."
            )

            st.write(
                "Add the expected information for this resume "
                "to calculate extraction accuracy."
            )

        else:

            accuracy, correct, total, results = calculate_accuracy(
                candidate_profile,
                expected_profile
            )


            # ------------------------------------------------
            # Accuracy metrics
            # ------------------------------------------------

            col1, col2, col3 = st.columns(3)

            with col1:

                st.metric(
                    "Fields Tested",
                    total
                )

            with col2:

                st.metric(
                    "Fields Correct",
                    correct
                )

            with col3:

                st.metric(
                    "Extraction Accuracy",
                    f"{accuracy:.2f}%"
                )


            # ------------------------------------------------
            # Progress bar
            # ------------------------------------------------

            st.progress(
                min(accuracy / 100, 1.0)
            )


            # ------------------------------------------------
            # Target status
            # ------------------------------------------------

            if accuracy >= 95:

                st.success(
                    "🎉 Accuracy target achieved!"
                )

                st.write(
                    "Required target: ≥ 95%"
                )

            else:

                st.warning(
                    "⚠️ Accuracy target not yet achieved."
                )

                st.write(
                    f"Current extraction accuracy: "
                    f"**{accuracy:.2f}%**"
                )

                st.write(
                    "Required target: **≥ 95%**"
                )


            # ------------------------------------------------
            # Field-by-field validation
            # ------------------------------------------------

            with st.expander(
                "🔍 View Field Validation Details"
            ):

                for field, matched in results.items():

                    if matched:

                        st.success(
                            f"✓ {field.title()}: Correct"
                        )

                    else:

                        st.error(
                            f"✗ {field.title()}: Needs improvement"
                        )


        # ====================================================
        # RAW EXTRACTED TEXT
        # ====================================================

        with st.expander(
            "📄 View Extracted Resume Text"
        ):

            st.text_area(
                "Raw Text",
                text,
                height=300
            )


        # ====================================================
        # JSON PROFILE
        # ====================================================

        with st.expander(
            "🧾 View Structured JSON Profile"
        ):

            st.json(candidate_profile)


    except Exception as error:

        st.error(
            "An error occurred while processing the resume."
        )

        st.exception(error)


    finally:

        # Delete temporary file
        if temp_path and os.path.exists(temp_path):

            try:
                os.remove(temp_path)
            except Exception:
                pass


else:

    st.info(
        "👆 Upload a PDF or DOCX resume to begin parsing."
    )