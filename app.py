import os
import re
import json
import tempfile
import requests
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import (
    extract_name,
    extract_email,
    extract_phone,
    extract_skills,
)
from modules.resume_parser.section_parser import extract_sections

from modules.authentication.auth import (
    signup_user,
    login_user,
    get_security_question,
    verify_security_answer,
    reset_password,
)

from modules.authentication.security import (
    generate_captcha,
    verify_captcha,
)

from modules.matching.matching_engine import (
    calculate_match,
)

from modules.matching.skill_gap import (
    generate_skill_gap_report,
)

from modules.matching.evaluator import (
    load_evaluation_cases,
    calculate_evaluation_accuracy,
)

from database.connection import SessionLocal
from database.models import Candidate, Job, Application, InterviewQuestion, InterviewResult, VoiceScreening

from modules.interview.question_generator import (
    generate_questions_for_job,
)

from modules.interview.evaluator import (
    evaluate_and_save,
)

from modules.interview.adaptive_interview import (
    ai_configured,
    generate_first_question,
    generate_next_question,
    save_question,
)
from modules.portal_router import (
    get_current_role,
    is_candidate,
    is_recruiter,
    show_portal_header,
)
from modules.voice_screening import (
    save_voice_screening,
    transcribe_audio,
)
from chatbot import build_context, get_response


# ============================================================
# FASTAPI CONNECTION
# ============================================================

FASTAPI_BASE_URL = "http://127.0.0.1:8000"


def call_fastapi(endpoint, method="GET", payload=None):
    """Call the local FastAPI backend safely."""
    url = f"{FASTAPI_BASE_URL}{endpoint}"

    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=5)
        elif method.upper() == "POST":
            response = requests.post(url, json=payload, timeout=5)
        elif method.upper() == "PUT":
            response = requests.put(url, json=payload, timeout=5)
        else:
            return None

        response.raise_for_status()
        return response.json()

    except requests.RequestException:
        return None


# ============================================================
# INTERVIEW COPILOT DATABASE HELPERS
# ============================================================

def get_or_create_db_candidate(profile, filename=None):
    """Create or update the current parsed candidate in MySQL."""
    db = SessionLocal()
    try:
        name = (profile.get("name") or "Unknown Candidate").strip()
        email = (profile.get("email") or "").strip().lower() or None

        candidate = None
        current_user = st.session_state.get("current_user") or {}
        current_user_id = current_user.get("id")

        if current_user_id:
            candidate = (
                db.query(Candidate)
                .filter(Candidate.user_id == int(current_user_id))
                .first()
            )

        if candidate is None and email:
            candidate = (
                db.query(Candidate)
                .filter(Candidate.email == email)
                .first()
            )
        if candidate is None:
            candidate = (
                db.query(Candidate)
                .filter(Candidate.name == name)
                .first()
            )

        experience_years = extract_experience_years(
            profile.get("experience", [])
        )

        if candidate is None:
            candidate = Candidate(
                name=name,
                email=email,
            )
            db.add(candidate)

        if current_user_id:
            candidate.user_id = int(current_user_id)

        candidate.name = name
        candidate.email = email
        candidate.phone = profile.get("phone")
        candidate.education = education_to_text(
            profile.get("education", [])
        )
        candidate.experience_years = experience_years
        candidate.skills = json.dumps(
            clean_list(profile.get("skills", []))
        )
        candidate.certifications = json.dumps(
            clean_list(profile.get("certifications", []))
        )
        candidate.projects = json.dumps(
            clean_list(profile.get("projects", []))
        )
        candidate.summary = "Resume uploaded through AI Recruitment Copilot"
        candidate.resume_filename = filename

        db.commit()
        db.refresh(candidate)
        return candidate.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db_job(external_job_id):
    """Map JOB001/JOB002/... from JSON to the MySQL Job record."""
    db = SessionLocal()
    try:
        return (
            db.query(Job)
            .filter(Job.job_id == str(external_job_id))
            .first()
        )
    finally:
        db.close()


def _db_list(value):
    """Convert DB JSON/list/string values into a clean list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except Exception:
        pass
    return [item.strip() for item in text.split(",") if item.strip()]


def _db_candidate_for_matching(candidate):
    return {
        "name": candidate.name or "Unknown Candidate",
        "skills": _db_list(candidate.skills),
        "experience": float(candidate.experience_years or 0),
        "education": candidate.education or "",
    }


def _db_job_for_matching(job):
    return {
        "job_id": job.job_id or job.id,
        "title": job.title or "Untitled Job",
        "description": job.description or "",
        "required_skills": _db_list(job.required_skills),
        "experience_required": float(job.experience_required or 0),
        "education_required": job.education_required or "",
        "location": job.location or "",
    }


def _average_interview_score(db, candidate_id, job_id):
    results = (
        db.query(InterviewResult)
        .filter(
            InterviewResult.candidate_id == candidate_id,
            InterviewResult.job_id == job_id,
        )
        .all()
    )
    scores = [float(r.overall_score) for r in results if r.overall_score is not None]
    return (sum(scores) / len(scores)) if scores else None


def _latest_voice_score(db, candidate_id, job_id):
    screening = (
        db.query(VoiceScreening)
        .filter(
            VoiceScreening.candidate_id == candidate_id,
            VoiceScreening.job_id == job_id,
        )
        .order_by(VoiceScreening.created_at.desc())
        .first()
    )
    return float(screening.overall_score) if screening and screening.overall_score is not None else None


def _final_recruitment_score(match_score, interview_score, voice_score):
    """Milestone 4D score: 50% match + 30% interview + 20% voice."""
    return round(
        (float(match_score or 0) * 0.50)
        + (float(interview_score or 0) * 0.30)
        + (float(voice_score or 0) * 0.20),
        2,
    )

def _build_recruitment_ranking(db):
    """Build the final candidate ranking used by Milestones 4D and 4E."""
    applications = db.query(Application).order_by(Application.applied_at.desc()).all()
    ranking_rows = []

    for application in applications:
        candidate = application.candidate
        job = application.job
        if not candidate or not job:
            continue

        try:
            match_result = calculate_match(
                _db_candidate_for_matching(candidate),
                _db_job_for_matching(job),
            )
            match_score = float(match_result.get("hiring_score", 0) or 0)
        except Exception:
            match_score = 0.0

        interview_score = _average_interview_score(db, candidate.id, job.id)
        voice_score = _latest_voice_score(db, candidate.id, job.id)
        final_score = _final_recruitment_score(
            match_score, interview_score, voice_score
        )

        ranking_rows.append({
            "Application ID": application.id,
            "Candidate": candidate.name or f"Candidate #{candidate.id}",
            "Email": candidate.email or "",
            "Job": job.title or f"Job #{job.id}",
            "Matching (%)": round(match_score, 2),
            "Interview (%)": (
                round(interview_score, 2) if interview_score is not None else None
            ),
            "Voice (%)": (
                round(voice_score, 2) if voice_score is not None else None
            ),
            "Final Score (%)": final_score,
            "Decision": application.status or "Applied",
            "Applied On": str(application.applied_at),
        })

    ranking_rows.sort(key=lambda row: row["Final Score (%)"], reverse=True)
    for rank, row in enumerate(ranking_rows, start=1):
        row["Rank"] = rank

    return ranking_rows


def load_saved_interview_questions(job_id, candidate_id):
    db = SessionLocal()
    try:
        return (
            db.query(InterviewQuestion)
            .filter(
                InterviewQuestion.job_id == job_id,
                InterviewQuestion.candidate_id == candidate_id,
            )
            .order_by(InterviewQuestion.id.asc())
            .all()
        )
    finally:
        db.close()


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="AI Recruitment Copilot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
<style>

:root {
    --copilot-ink: #0f172a;
    --copilot-muted: #64748b;
    --copilot-border: #e2e8f0;
    --copilot-card: #ffffff;
    --copilot-bg: #f8fafc;
    --copilot-accent: #2563eb;
    --copilot-accent-2: #4f46e5;
}

/* ============================================================
   GLOBAL LIGHT THEME
   ============================================================ */

html,
body,
.stApp {
    background: #f8fafc !important;
    color: #0f172a !important;
}

[data-testid="stAppViewContainer"] {
    background: #f8fafc !important;
}

[data-testid="stHeader"] {
    background: #ffffff !important;
    border-bottom: 1px solid #e2e8f0;
}

[data-testid="stToolbar"] {
    background: transparent !important;
}

.block-container {
    max-width: 1250px;
    padding-top: 2rem;
    padding-bottom: 3rem;
}

/* ============================================================
   SIDEBAR
   ============================================================ */

[data-testid="stSidebar"] {
    background: #ffffff !important;
    border-right: 1px solid #e2e8f0 !important;
}

[data-testid="stSidebar"] > div:first-child {
    background: #ffffff !important;
}

[data-testid="stSidebar"] * {
    color: #0f172a;
}

/* ============================================================
   HERO
   ============================================================ */

.hero-box {
    background: linear-gradient(
        135deg,
        #eff6ff 0%,
        #ffffff 52%,
        #eef2ff 100%
    );
    border: 1px solid #dbeafe;
    border-radius: 24px;
    padding: 34px 38px;
    margin-bottom: 24px;
    box-shadow: 0 18px 45px rgba(15, 23, 42, 0.08);
}

.hero-title {
    color: #0f172a !important;
    font-size: 42px;
    line-height: 1.12;
    font-weight: 850;
    margin-bottom: 10px;
}

.hero-subtitle {
    color: #475569 !important;
    font-size: 18px;
    line-height: 1.6;
}

/* ============================================================
   LANDING NAVIGATION
   ============================================================ */

.landing-nav {
    display: flex;
    justify-content: center;
    gap: 10px;
    margin: 4px 0 22px 0;
    flex-wrap: wrap;
}

.landing-nav a {
    color: #475569 !important;
    text-decoration: none !important;
    background: #ffffff;
    border: 1px solid #e2e8f0;
    padding: 8px 15px;
    border-radius: 999px;
    font-weight: 700;
    font-size: 14px;
    transition: all 0.2s ease;
}

.landing-nav a:hover {
    color: #1d4ed8 !important;
    border-color: #93c5fd;
    background: #eff6ff;
}

/* ============================================================
   LANDING PAGE
   ============================================================ */

.landing-hero {
    padding: 30px 10px 18px 10px;
    text-align: center;
}

.landing-kicker {
    display: inline-block;
    padding: 7px 13px;
    border-radius: 999px;
    background: #eff6ff;
    color: #1d4ed8 !important;
    border: 1px solid #bfdbfe;
    font-weight: 800;
    font-size: 13px;
    letter-spacing: .02em;
}

.landing-title {
    color: #0f172a !important;
    font-size: clamp(34px, 5vw, 58px);
    line-height: 1.05;
    font-weight: 900;
    margin: 18px auto 12px auto;
    max-width: 900px;
}

.landing-copy {
    color: #64748b !important;
    font-size: 18px;
    line-height: 1.7;
    max-width: 820px;
    margin: 0 auto;
}

/* ============================================================
   INFO CARDS
   ============================================================ */

.info-card {
    background: #ffffff;
    color: #0f172a !important;
    border: 1px solid #e2e8f0;
    border-radius: 18px;
    padding: 22px;
    min-height: 155px;
    box-shadow: 0 10px 28px rgba(15, 23, 42, 0.06);
}

.info-card h3,
.info-card p,
.info-card strong,
.info-card span {
    color: #0f172a !important;
}

.info-card h3 {
    margin-top: 0;
    font-size: 20px;
    font-weight: 800;
}

.info-card p {
    color: #475569 !important;
    line-height: 1.6;
    font-size: 14px;
}

/* ============================================================
   SECTIONS
   ============================================================ */

.landing-section {
    padding: 26px 0;
}

.section-title {
    color: #0f172a !important;
    font-size: 30px;
    font-weight: 850;
    margin-bottom: 8px;
}

.section-copy {
    color: #64748b !important;
    font-size: 16px;
    line-height: 1.7;
}

/* ============================================================
   PROCESS / STEP CARDS
   ============================================================ */

.step-card {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 18px;
    padding: 20px;
    min-height: 155px;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
}

.step-number {
    color: #2563eb !important;
    font-weight: 900;
    font-size: 13px;
    letter-spacing: .08em;
}

.step-card h3 {
    color: #0f172a !important;
}

.step-card p {
    color: #475569 !important;
    line-height: 1.55;
}

/* ============================================================
   PORTAL BANNER
   ============================================================ */

.portal-banner {
    background: linear-gradient(
        135deg,
        #eff6ff 0%,
        #eef2ff 100%
    );
    border: 1px solid #bfdbfe;
    border-radius: 18px;
    padding: 20px 22px;
    margin-bottom: 18px;
}

.portal-banner h2 {
    color: #0f172a !important;
}

.portal-banner p {
    color: #475569 !important;
    margin-bottom: 0;
}

/* ============================================================
   INFORMATION LABELS
   ============================================================ */

.info-label {
    color: #64748b !important;
    font-size: 14px;
    font-weight: 700;
    margin-bottom: 8px;
}

.info-value {
    color: #111827 !important;
    font-size: 17px;
    font-weight: 700;
    word-break: break-word;
}

/* ============================================================
   SKILLS
   ============================================================ */

.skill-box {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 15px;
}

.skill-pill {
    display: inline-block;
    background-color: #eff6ff;
    color: #1e40af !important;
    border: 1px solid #bfdbfe;
    border-radius: 20px;
    padding: 6px 12px;
    margin: 4px;
    font-size: 14px;
    font-weight: 700;
}

/* ============================================================
   MATCHING CARDS
   ============================================================ */

.match-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 16px;
    padding: 20px;
    margin: 8px 0;
    box-shadow: 0 8px 22px rgba(15, 23, 42, 0.05);
}

/* ============================================================
   SUCCESS / WARNING
   ============================================================ */

.success-box {
    background-color: #ecfdf5;
    border: 1px solid #86efac;
    border-radius: 12px;
    padding: 14px;
    color: #166534 !important;
    font-weight: 700;
    margin: 10px 0;
}

.warning-box {
    background-color: #fffbeb;
    border: 1px solid #fcd34d;
    border-radius: 12px;
    padding: 14px;
    color: #92400e !important;
    font-weight: 700;
    margin: 10px 0;
}

/* ============================================================
   CAPTCHA
   ============================================================ */

.captcha-box {
    background-color: #ffffff;
    border: 2px dashed #94a3b8;
    border-radius: 12px;
    padding: 12px;
    text-align: center;
    margin-bottom: 10px;
}

.captcha-code {
    font-size: 24px;
    font-weight: 800;
    letter-spacing: 6px;
    color: #111827 !important;
}

/* ============================================================
   SIDE NAVIGATION
   ============================================================ */

.side-nav-btn {
    display: block;
    text-decoration: none !important;
    background: #ffffff;
    color: #334155 !important;
    padding: 10px 12px;
    margin: 6px 0;
    border-radius: 10px;
    font-weight: 650;
    font-size: 14px;
    border: 1px solid #e2e8f0;
    transition: all 0.2s ease;
}

.side-nav-btn:hover {
    background: #eff6ff;
    color: #1d4ed8 !important;
    border-color: #93c5fd;
}

/* ============================================================
   CHATBOT
   ============================================================ */

.chat-card {
    background: linear-gradient(
        135deg,
        #eff6ff 0%,
        #eef2ff 100%
    );
    border: 1px solid #c7d2fe;
    border-radius: 20px;
    padding: 22px;
    margin-top: 26px;
    box-shadow: 0 8px 24px rgba(37, 99, 235, 0.06);
}

.chat-card h2 {
    color: #0f172a !important;
}

.chat-card p {
    color: #475569 !important;
}

/* ============================================================
   STREAMLIT WIDGET LABELS
   ============================================================ */

.stTextInput label,
.stTextArea label,
.stSelectbox label,
.stMultiSelect label,
.stNumberInput label,
.stFileUploader label,
.stRadio label,
.stCheckbox label,
.stSlider label,
.stDateInput label,
.stTimeInput label {
    color: #334155 !important;
    font-weight: 600 !important;
}

/* ============================================================
   STREAMLIT INPUTS
   ============================================================ */

.stTextInput input,
.stTextArea textarea,
.stNumberInput input {
    background-color: #ffffff !important;
    color: #0f172a !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 10px !important;
}

.stTextInput input:focus,
.stTextArea textarea:focus,
.stNumberInput input:focus {
    border-color: #60a5fa !important;
    box-shadow: 0 0 0 2px rgba(37, 99, 235, 0.10) !important;
}

/* ============================================================
   SELECT BOX
   ============================================================ */

div[data-baseweb="select"] > div {
    background-color: #ffffff !important;
    border-color: #cbd5e1 !important;
    color: #0f172a !important;
}

/* ============================================================
   BUTTONS
   ============================================================ */

.stButton > button {
    border-radius: 10px !important;
    font-weight: 700 !important;
    border: 1px solid #cbd5e1 !important;
    background: #ffffff !important;
    color: #1e293b !important;
    transition: all 0.2s ease;
}

.stButton > button:hover {
    border-color: #60a5fa !important;
    color: #1d4ed8 !important;
    background: #eff6ff !important;
}

/* ============================================================
   DOWNLOAD BUTTON
   ============================================================ */

.stDownloadButton > button {
    border-radius: 10px !important;
    font-weight: 700 !important;
    background: #2563eb !important;
    color: #ffffff !important;
    border: 1px solid #2563eb !important;
}

.stDownloadButton > button:hover {
    background: #1d4ed8 !important;
    border-color: #1d4ed8 !important;
}

/* ============================================================
   DATAFRAMES / TABLES
   ============================================================ */

[data-testid="stDataFrame"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
}

/* ============================================================
   EXPANDERS
   ============================================================ */

[data-testid="stExpander"] {
    background: #ffffff !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
}

/* ============================================================
   METRICS
   ============================================================ */

[data-testid="stMetric"] {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    padding: 14px;
}

[data-testid="stMetricLabel"] {
    color: #64748b !important;
}

[data-testid="stMetricValue"] {
    color: #0f172a !important;
}

/* ============================================================
   TABS
   ============================================================ */

.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background: #ffffff;
    border-bottom: 1px solid #e2e8f0;
}

.stTabs [data-baseweb="tab"] {
    color: #64748b !important;
    font-weight: 700 !important;
}

.stTabs [aria-selected="true"] {
    color: #2563eb !important;
}

/* ============================================================
   FOOTER
   ============================================================ */

.footer {
    text-align: center;
    color: #64748b !important;
    padding: 35px 0 15px 0;
    font-size: 13px;
}
/* ============================================================
   INPUT PLACEHOLDER READABILITY
   ============================================================ */

.stTextInput input::placeholder,
.stTextArea textarea::placeholder,
.stNumberInput input::placeholder {
    color: #94a3b8 !important;
    opacity: 1 !important;
}

.stTextInput input,
.stTextArea textarea,
.stNumberInput input {
    color: #0f172a !important;
}
/* ============================================================
   FORCE NATIVE STREAMLIT COMPONENTS TO LIGHT THEME
   ============================================================ */

[data-testid="stDataFrame"],
[data-testid="stDataFrame"] > div,
[data-testid="stDataFrame"] iframe {
    background: #ffffff !important;
    color: #0f172a !important;
}

/* Native Streamlit chat and fixed bottom area */
[data-testid="stBottom"],
[data-testid="stBottom"] > div,
[data-testid="stBottomBlockContainer"] {
    background: #f8fafc !important;
    background-color: #f8fafc !important;
}

[data-testid="stChatInput"] {
    background: #ffffff !important;
    background-color: #ffffff !important;
    border: 1px solid #cbd5e1 !important;
    border-radius: 12px !important;
    box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06) !important;
}

[data-testid="stChatInput"] > div {
    background: #ffffff !important;
    background-color: #ffffff !important;
    border-radius: 12px !important;
}

[data-testid="stChatInput"] textarea {
    background: #ffffff !important;
    background-color: #ffffff !important;
    color: #0f172a !important;
    -webkit-text-fill-color: #0f172a !important;
}

[data-testid="stChatInput"] textarea::placeholder {
    color: #64748b !important;
    opacity: 1 !important;
}

[data-testid="stChatInput"] button {
    background: #2563eb !important;
    color: #ffffff !important;
    border-radius: 8px !important;
}

[data-testid="stChatMessage"] {
    background: #ffffff !important;
    background-color: #ffffff !important;
    color: #0f172a !important;
    border: 1px solid #e2e8f0 !important;
    border-radius: 12px !important;
}

[data-testid="stChatMessage"] *,
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] * {
    color: #0f172a !important;
}

[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] {
    color: #0f172a !important;
}

[data-testid="stAlert"] {
    color: #0f172a !important;
}

</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# SESSION STATE
# ============================================================

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if "current_user" not in st.session_state:
    st.session_state.current_user = None

if "auth_page" not in st.session_state:
    st.session_state.auth_page = "welcome"

if "login_captcha" not in st.session_state:
    st.session_state.login_captcha = generate_captcha()

if "signup_captcha" not in st.session_state:
    st.session_state.signup_captcha = generate_captcha()

if "recovery_captcha" not in st.session_state:
    st.session_state.recovery_captcha = generate_captcha()

if "recovery_verified" not in st.session_state:
    st.session_state.recovery_verified = False

if "recovery_email" not in st.session_state:
    st.session_state.recovery_email = ""

if "candidate_profile" not in st.session_state:
    st.session_state.candidate_profile = None

if "candidate_filename" not in st.session_state:
    st.session_state.candidate_filename = None

if "candidate_profiles" not in st.session_state:
    st.session_state.candidate_profiles = []

if "selected_job_data" not in st.session_state:
    st.session_state.selected_job_data = None

if "interview_key" not in st.session_state:
    st.session_state.interview_key = None

if "interview_questions" not in st.session_state:
    st.session_state.interview_questions = []

if "interview_results" not in st.session_state:
    st.session_state.interview_results = []

if "adaptive_interview_active" not in st.session_state:
    st.session_state.adaptive_interview_active = False

if "adaptive_interview_finished" not in st.session_state:
    st.session_state.adaptive_interview_finished = False

if "adaptive_question_number" not in st.session_state:
    st.session_state.adaptive_question_number = 0

if "adaptive_target_count" not in st.session_state:
    st.session_state.adaptive_target_count = 10

if "adaptive_current_question" not in st.session_state:
    st.session_state.adaptive_current_question = None

if "adaptive_history" not in st.session_state:
    st.session_state.adaptive_history = []

if "adaptive_results" not in st.session_state:
    st.session_state.adaptive_results = []


# ============================================================
# GENERAL HELPER FUNCTIONS
# ============================================================

def ensure_list(value):

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

        if "," in value:

            return [
                item.strip()
                for item in value.split(",")
                if item.strip()
            ]

        return [value]

    return [str(value)]


def clean_list(value):

    items = ensure_list(value)

    result = []
    seen = set()

    for item in items:

        item = str(item).strip()

        if not item:
            continue

        key = re.sub(
            r"\s+",
            " ",
            item.lower()
        )

        if key not in seen:

            result.append(item)
            seen.add(key)

    return result


def normalize_text(value):

    if value is None:
        return ""

    value = str(value).lower().strip()

    value = re.sub(
        r"\s+",
        " ",
        value
    )

    value = re.sub(
        r"[^\w\s@.+#-]",
        "",
        value
    )

    return value


# ============================================================
# MILESTONE 1 ACCURACY
# ============================================================

def field_match(actual, expected):

    if isinstance(expected, list):

        expected_items = {
            normalize_text(item)
            for item in expected
            if normalize_text(item)
        }

        actual_items = {
            normalize_text(item)
            for item in ensure_list(actual)
            if normalize_text(item)
        }

        if not expected_items:
            return True

        if not actual_items:
            return False

        matched = expected_items.intersection(
            actual_items
        )

        score = (
            len(matched)
            /
            len(expected_items)
        )

        return score >= 0.95

    return (
        normalize_text(actual)
        ==
        normalize_text(expected)
    )


def calculate_accuracy(actual, expected):

    fields = [
        "name",
        "email",
        "phone",
        "education",
        "skills",
        "experience",
        "certifications",
        "projects",
    ]

    correct = 0
    results = {}

    for field in fields:

        expected_value = expected.get(field)
        actual_value = actual.get(field)

        matched = field_match(
            actual_value,
            expected_value
        )

        results[field] = matched

        if matched:
            correct += 1

    total = len(fields)

    accuracy = (
        correct / total
    ) * 100

    return (
        accuracy,
        correct,
        total,
        results,
    )


def load_ground_truth():

    possible_paths = [
        "expected_profiles.json",
        os.path.join(
            os.path.dirname(__file__),
            "expected_profiles.json",
        ),
    ]

    for path in possible_paths:

        if os.path.exists(path):

            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8",
                ) as file:

                    return json.load(file)

            except Exception as error:

                st.warning(
                    f"Could not read expected_profiles.json: "
                    f"{error}"
                )

                return {}

    return {}


def find_ground_truth(
    filename,
    ground_truth,
):

    if not ground_truth:
        return None

    if filename in ground_truth:
        return ground_truth[filename]

    base_name = os.path.basename(filename)

    if base_name in ground_truth:
        return ground_truth[base_name]

    filename_lower = base_name.lower()

    for key, value in ground_truth.items():

        if (
            os.path.basename(
                str(key)
            ).lower()
            ==
            filename_lower
        ):

            return value

    return None


# ============================================================
# CANDIDATE PROFILE
# ============================================================

def build_candidate_profile(text):

    name = extract_name(text)

    email = extract_email(text)

    phone = extract_phone(text)

    skills = extract_skills(text)

    sections = extract_sections(text)

    education = clean_list(
        sections.get(
            "education",
            [],
        )
    )

    experience = clean_list(
        sections.get(
            "experience",
            [],
        )
    )

    certifications = clean_list(
        sections.get(
            "certifications",
            [],
        )
    )

    projects = clean_list(
        sections.get(
            "projects",
            [],
        )
    )

    skills = clean_list(skills)

    return {
        "name": name,
        "email": email,
        "phone": phone,
        "education": education,
        "skills": skills,
        "experience": experience,
        "certifications": certifications,
        "projects": projects,
    }


# ============================================================
# EXPERIENCE EXTRACTION
# ============================================================

def extract_experience_years(experience_data):

    if not experience_data:
        return 0.0

    text = " ".join(
        ensure_list(experience_data)
    )

    direct_match = re.search(
        r"(\d+(?:\.\d+)?)\s*\+?\s*years?",
        text.lower(),
    )

    if direct_match:

        return float(
            direct_match.group(1)
        )

    current_year = datetime.now().year

    total_months = 0

    pattern = (
        r"(\d{4})\s*[-–]\s*"
        r"(Present|\d{4})"
    )

    matches = re.findall(
        pattern,
        text,
        flags=re.IGNORECASE,
    )

    for start, end in matches:

        start_year = int(start)

        if end.lower() == "present":

            end_year = current_year

        else:

            end_year = int(end)

        if end_year >= start_year:

            total_months += (
                end_year - start_year
            ) * 12

    if total_months > 0:

        return round(
            total_months / 12,
            1,
        )

    return 0.0


def education_to_text(education):

    return " ".join(
        clean_list(education)
    )


# ============================================================
# JOB FUNCTIONS
# ============================================================

def load_jobs():

    possible_paths = [
        os.path.join(
            "jobs",
            "job_profiles.json",
        ),
        os.path.join(
            os.path.dirname(__file__),
            "jobs",
            "job_profiles.json",
        ),
    ]

    for path in possible_paths:

        if os.path.exists(path):

            try:

                with open(
                    path,
                    "r",
                    encoding="utf-8",
                ) as file:

                    data = json.load(file)

                if isinstance(data, dict):

                    return data.get(
                        "jobs",
                        [],
                    )

                return data

            except Exception as error:

                st.error(
                    f"Could not load job_profiles.json: "
                    f"{error}"
                )

                return []

    return []


# ============================================================
# WELCOME / LANDING PAGE
# ============================================================

def show_welcome_page():
    st.markdown(
        '<div class="landing-nav">'
        '<a href="#home">Home</a>'
        '<a href="#about">About</a>'
        '<a href="#features">Features</a>'
        '<a href="#how-it-works">How It Works</a>'
        '<a href="#contact">Get Started</a>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div id="home"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="landing-hero">'
        '<div class="landing-kicker">🤖 AI-POWERED RECRUITMENT PLATFORM</div>'
        '<div class="landing-title">Smarter Recruitment. Better Hiring Decisions.</div>'
        '<div class="landing-copy">'
        'A modern recruitment workspace that turns resumes into structured profiles, '
        'connects candidates with relevant roles, and supports recruiters with interviews, '
        'voice screening, ranking and actionable reports.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    login_col, signup_col = st.columns(2)
    with login_col:
        if st.button("🔐 Login to Portal", type="primary", use_container_width=True, key="welcome_login"):
            st.session_state.auth_page = "login"
            st.session_state.login_captcha = generate_captcha()
            st.rerun()
    with signup_col:
        if st.button("✨ Create Free Account", use_container_width=True, key="welcome_signup"):
            st.session_state.auth_page = "signup"
            st.session_state.signup_captcha = generate_captcha()
            st.rerun()

    st.markdown('<div id="about"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="landing-section">'
        '<div class="section-title">About the Platform</div>'
        '<div class="section-copy">'
        'AI Recruitment Copilot brings the candidate and recruiter workflow into one portal. '
        'Candidates can build a profile from a PDF/DOCX resume, explore job compatibility, '
        'apply, complete screening activities and practice an adaptive interview. Recruiters '
        'can review applicants, compare scores, record decisions and export recruitment reports.'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown('<div id="features"></div>', unsafe_allow_html=True)
    st.markdown('<div class="section-title">Everything You Need in One Workspace</div>', unsafe_allow_html=True)
    f1, f2, f3 = st.columns(3)
    with f1:
        st.markdown('<div class="info-card"><h3>📄 Resume & Profile</h3><p>Extract candidate name, contact details, skills, education, experience, certifications and projects from PDF/DOCX resumes.</p></div>', unsafe_allow_html=True)
    with f2:
        st.markdown('<div class="info-card"><h3>🧠 AI Job Matching</h3><p>Compare candidate profiles with job requirements and surface compatibility and skill-gap insights.</p></div>', unsafe_allow_html=True)
    with f3:
        st.markdown('<div class="info-card"><h3>🏆 Smart Hiring</h3><p>Combine applications, interviews, voice screening, ranking and recruitment reports in a single workflow.</p></div>', unsafe_allow_html=True)

    st.markdown('<div id="how-it-works"></div>', unsafe_allow_html=True)
    st.markdown('<div class="landing-section"><div class="section-title">How It Works</div><div class="section-copy">A simple workflow from resume to hiring decision.</div></div>', unsafe_allow_html=True)
    s1, s2, s3, s4 = st.columns(4)
    steps = [
        ("01", "Upload", "Upload a PDF or DOCX resume and create a structured candidate profile."),
        ("02", "Match", "Select a role and review compatibility, matched skills and skill gaps."),
        ("03", "Screen", "Apply, complete voice screening and take the adaptive AI interview."),
        ("04", "Decide", "Recruiters review combined scores, make decisions and generate reports."),
    ]
    for col, (num, title, body) in zip((s1, s2, s3, s4), steps):
        with col:
            st.markdown(f'<div class="step-card"><div class="step-number">STEP {num}</div><h3>{title}</h3><p>{body}</p></div>', unsafe_allow_html=True)

    st.markdown('<div id="contact"></div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="landing-section" style="text-align:center;">'
        '<div class="section-title">Ready to get started?</div>'
        '<div class="section-copy">Create an account and enter the candidate or recruiter portal.</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div style="text-align:center; color:#94a3b8; margin-top:12px;">'
        '🔒 Secure account access &nbsp; • &nbsp; 👤 Candidate Portal &nbsp; • &nbsp; 🧑‍💼 Recruiter Portal'
        '</div>',
        unsafe_allow_html=True,
    )


# ============================================================
# LOGIN PAGE
# ============================================================

def show_login_page():

    st.markdown(
        '<div class="hero-box">'
        '<div class="hero-title">'
        '🤖 AI Recruitment Copilot'
        '</div>'
        '<div class="hero-subtitle">'
        'Secure Recruitment Management Portal'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.subheader("🔐 Login")

    email = st.text_input(
        "Email",
        placeholder="Enter your email",
        key="login_email",
    )

    password = st.text_input(
        "Password",
        type="password",
        placeholder="Enter your password",
        key="login_password",
    )

    st.markdown(
        '<div class="captcha-box">'
        '<div>CAPTCHA Verification</div>'
        f'<div class="captcha-code">'
        f'{st.session_state.login_captcha}'
        f'</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    captcha_input = st.text_input(
        "Enter CAPTCHA",
        placeholder="Enter the code shown above",
        key="login_captcha_input",
    )

    col1, col2 = st.columns(2)

    with col1:

        login_clicked = st.button(
            "🔐 Login",
            use_container_width=True,
            type="primary",
        )

    with col2:

        signup_clicked = st.button(
            "📝 Sign Up",
            use_container_width=True,
        )

    if login_clicked:

        if not email or not password:

            st.error(
                "Please enter both email and password."
            )

        elif not verify_captcha(
            st.session_state.login_captcha,
            captcha_input,
        ):

            st.error(
                "❌ Incorrect CAPTCHA."
            )

            st.session_state.login_captcha = (
                generate_captcha()
            )

        else:

            success, user = login_user(
                email,
                password,
            )

            if success:

                st.session_state.authenticated = True

                st.session_state.current_user = user

                st.success(
                    "✅ Login successful!"
                )

                st.rerun()

            else:

                st.error(
                    "❌ Invalid email or password."
                )

                st.session_state.login_captcha = (
                    generate_captcha()
                )

    if signup_clicked:

        st.session_state.auth_page = "signup"

        st.rerun()

    st.markdown("---")

    if st.button(
        "🔑 Forgot Password?",
        use_container_width=True,
    ):

        st.session_state.auth_page = "forgot"

        st.session_state.recovery_verified = False

        st.rerun()


# ============================================================
# SIGNUP PAGE
# ============================================================

def show_signup_page():

    st.markdown(
        '<div class="hero-box">'
        '<div class="hero-title">'
        '📝 Create Account'
        '</div>'
        '<div class="hero-subtitle">'
        'Create your Recruitment Copilot account'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    st.subheader("📝 Sign Up")

    name = st.text_input(
        "Full Name",
        placeholder="Enter your full name",
        key="signup_name",
    )

    email = st.text_input(
        "Email",
        placeholder="Enter your email",
        key="signup_email",
    )

    password = st.text_input(
        "Password",
        type="password",
        placeholder="Create a password",
        key="signup_password",
    )

    confirm_password = st.text_input(
        "Confirm Password",
        type="password",
        placeholder="Re-enter your password",
        key="signup_confirm_password",
    )

    role = st.selectbox(
        "Account Type",
        [
            "Candidate",
            "Recruiter",
        ],
        key="signup_role",
    )

    security_question = st.selectbox(
        "Security Question",
        [
            "What is your favorite programming language?",
            "What was the name of your first school?",
            "What is your favorite technology?",
            "What city were you born in?",
        ],
        key="signup_security_question",
    )

    security_answer = st.text_input(
        "Security Answer",
        placeholder="Enter your answer",
        key="signup_security_answer",
    )

    st.markdown(
        '<div class="captcha-box">'
        '<div>CAPTCHA Verification</div>'
        f'<div class="captcha-code">'
        f'{st.session_state.signup_captcha}'
        f'</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    captcha_input = st.text_input(
        "Enter CAPTCHA",
        placeholder="Enter the code shown above",
        key="signup_captcha_input",
    )

    col1, col2 = st.columns(2)

    with col1:

        create_account = st.button(
            "✅ Create Account",
            use_container_width=True,
            type="primary",
        )

    with col2:

        back_login = st.button(
            "⬅️ Back to Login",
            use_container_width=True,
        )

    if create_account:

        if not name or not email or not password:

            st.error(
                "Please fill in all required fields."
            )

        elif password != confirm_password:

            st.error(
                "❌ Passwords do not match."
            )

        elif len(password) < 6:

            st.error(
                "❌ Password must contain at least 6 characters."
            )

        elif not security_answer:

            st.error(
                "❌ Please provide a security answer."
            )

        elif not verify_captcha(
            st.session_state.signup_captcha,
            captcha_input,
        ):

            st.error(
                "❌ Incorrect CAPTCHA."
            )

            st.session_state.signup_captcha = (
                generate_captcha()
            )

        else:

            success, message = signup_user(
                name,
                email,
                password,
                security_question,
                security_answer,
                role.lower(),
            )

            if success:

                st.success(
                    "🎉 Account created successfully!"
                )

                st.info(
                    "You can now return to the login page."
                )

                st.session_state.auth_page = "login"

                st.session_state.login_captcha = (
                    generate_captcha()
                )

            else:

                st.error(
                    f"❌ {message}"
                )

    if back_login:

        st.session_state.auth_page = "login"

        st.rerun()


# ============================================================
# FORGOT PASSWORD
# ============================================================

def show_forgot_password_page():

    st.title("🔑 Password Recovery")

    st.write(
        "Verify your identity using your security question."
    )

    email = st.text_input(
        "Registered Email",
        value=st.session_state.recovery_email,
        placeholder="Enter your registered email",
    )

    if not email:

        if st.button(
            "⬅️ Back to Login"
        ):

            st.session_state.auth_page = "login"

            st.rerun()

        return

    email = email.strip().lower()

    security_question = get_security_question(email)
    if not security_question:
        st.error(
            "❌ No account was found with this email, or password recovery is not configured for this account."
        )

        if st.button(
            "⬅️ Back to Login",
            use_container_width=True,
        ):
            st.session_state.auth_page = "login"
            st.rerun()
        return

    st.info(f"Security Question: {security_question}")

    answer = st.text_input(
        "Security Answer",
        type="password",
        placeholder="Enter your security answer",
    )

    st.markdown(
        '<div class="captcha-box">'
        '<div>CAPTCHA Verification</div>'
        f'<div class="captcha-code">'
        f'{st.session_state.recovery_captcha}'
        f'</div>'
        '</div>',
        unsafe_allow_html=True,
    )

    captcha_input = st.text_input(
        "Enter CAPTCHA",
        placeholder="Enter the code shown above",
    )

    if not st.session_state.recovery_verified:

        verify_button = st.button(
            "🔍 Verify Identity",
            type="primary",
            use_container_width=True,
        )

        if verify_button:

            captcha_valid = verify_captcha(
                st.session_state.recovery_captcha,
                captcha_input,
            )

            answer_valid = verify_security_answer(
                email,
                answer,
            )

            if not captcha_valid:
                st.error("❌ Incorrect CAPTCHA.")
                st.session_state.recovery_captcha = generate_captcha()
            elif not answer_valid:
                st.error("❌ Incorrect security answer.")
            else:
                st.session_state.recovery_verified = True
                st.session_state.recovery_email = email
                st.success("✅ Identity verified successfully.")
                st.rerun()

    else:

        st.success("🔓 Identity verified successfully.")

        new_password = st.text_input(
            "New Password",
            type="password",
        )

        confirm_new_password = st.text_input(
            "Confirm New Password",
            type="password",
        )

        reset_button = st.button(
            "🔄 Reset Password",
            type="primary",
            use_container_width=True,
        )

        if reset_button:

            if len(new_password) < 6:
                st.error("Password must contain at least 6 characters.")
            elif new_password != confirm_new_password:
                st.error("Passwords do not match.")
            else:
                success, message = reset_password(
                    st.session_state.recovery_email,
                    new_password,
                )
                if success:
                    st.success("🎉 Password reset successfully!")
                    st.session_state.recovery_verified = False
                    st.session_state.recovery_email = ""
                    st.session_state.auth_page = "login"
                    st.session_state.login_captcha = generate_captcha()
                    st.rerun()
                else:
                    st.error(f"❌ {message}")

    st.markdown("---")

    if st.button(
        "⬅️ Back to Login",
        use_container_width=True,
    ):

        st.session_state.auth_page = "login"

        st.session_state.recovery_verified = False

        st.rerun()


# ============================================================
# AUTHENTICATION ROUTER
# ============================================================

if not st.session_state.authenticated:

    if st.session_state.auth_page == "welcome":

        show_welcome_page()

    elif st.session_state.auth_page == "signup":

        show_signup_page()

    elif st.session_state.auth_page == "forgot":

        show_forgot_password_page()

    else:

        show_login_page()

    st.stop()


# ============================================================
# ROLE-BASED PORTAL ROUTING
# ============================================================

current_role = get_current_role()

if current_role not in {"candidate", "recruiter"}:
    current_role = "candidate"


# ============================================================
# SIDEBAR
# ============================================================

with st.sidebar:

    st.title(
        "🤖 AI Recruitment Copilot"
    )

    st.markdown("---")

    current_user = st.session_state.current_user

    if current_user:

        st.write(
            f"👤 **{current_user['name']}**"
        )

        st.caption(
            current_user["email"]
        )

        if current_role == "recruiter":
            st.info("🧑‍💼 Recruiter Account")
        else:
            st.info("👤 Candidate Account")

    st.markdown("---")

    st.subheader("🧭 Quick Access")

    if current_role == "recruiter":
        st.caption("Open a recruiter workspace section")
        recruiter_buttons = [
            ("👥 Candidates", "👥 Candidates"),
            ("💼 Jobs", "💼 Jobs"),
            ("📋 Applications", "📋 Applications"),
            ("🎙️ Voice Screening", "🎙️ Voice Screening"),
            ("🏆 AI Ranking & Decisions", "🏆 AI Ranking & Decisions"),
            ("📊 Final Reports", "📊 Final Reports"),
        ]
        for button_label, section_name in recruiter_buttons:
            if st.button(button_label, use_container_width=True, key=f"side_{section_name}"):
                st.session_state.recruiter_section = section_name
                st.rerun()
    else:
        st.caption("Jump to a candidate workspace section")
        st.markdown(
            '<a class="side-nav-btn" href="#candidate-resume">📄 Resume & Profile</a>'
            '<a class="side-nav-btn" href="#candidate-matching">🤖 Job Matching</a>'
            '<a class="side-nav-btn" href="#candidate-applications">📋 Applications</a>'
            '<a class="side-nav-btn" href="#candidate-voice">🎙️ Voice Screening</a>'
            '<a class="side-nav-btn" href="#candidate-interview">🎤 AI Interview</a>'
            '<a class="side-nav-btn" href="#assistant">💬 Recruitment Assistant</a>',
            unsafe_allow_html=True,
        )

    st.markdown("---")

    st.subheader(
        "Supported Formats"
    )

    st.write("📄 PDF")
    st.write("📝 DOCX")

    st.markdown("---")

    st.subheader(
        "Extracted Information"
    )

    st.write("👤 Candidate Name")
    st.write("📧 Email")
    st.write("📱 Phone")
    st.write("🎓 Education")
    st.write("🛠️ Skills")
    st.write("💼 Experience")
    st.write("🏆 Certifications")
    st.write("🚀 Projects")

    st.markdown("---")

    if st.button(
        "🚪 Logout",
        use_container_width=True,
    ):

        st.session_state.authenticated = False

        st.session_state.current_user = None

        st.session_state.candidate_profile = None

        st.session_state.candidate_profiles = []

        st.session_state.candidate_filename = None

        st.session_state.auth_page = "login"

        st.session_state.login_captcha = (
            generate_captcha()
        )

        st.rerun()


# ============================================================
# MAIN HEADER
# ============================================================

st.markdown(
    '<div class="hero-box">'
    '<div class="hero-title">'
    '🤖 AI Recruitment Copilot'
    '</div>'
    '<div class="hero-subtitle">'
    'AI-powered resume parsing, candidate profiling, '
    'candidate-job matching and skill-gap analysis.'
    '</div>'
    '</div>',
    unsafe_allow_html=True,
)


# ============================================================
# ROLE-SPECIFIC MAIN PORTAL
# ============================================================

if is_recruiter():

    show_portal_header()

    st.divider()
    st.markdown('<div id="recruiter-dashboard"></div>', unsafe_allow_html=True)
    st.header("📊 Recruiter Dashboard")
    st.info(
        "Recruiter mode is active. Candidate resume upload and the "
        "candidate interview workflow are hidden from this account."
    )

    from database.models import Application

    db = SessionLocal()
    try:
        candidate_count = db.query(Candidate).count()
        job_count = db.query(Job).count()
        application_count = db.query(Application).count()
    finally:
        db.close()

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("👥 Candidates", candidate_count)
    with c2:
        st.metric("💼 Jobs", job_count)
    with c3:
        st.metric("📋 Applications", application_count)

    st.divider()

    recruiter_tab_options = [
        "👥 Candidates",
        "💼 Jobs",
        "📋 Applications",
        "🎙️ Voice Screening",
        "🏆 AI Ranking & Decisions",
        "📊 Final Reports",
    ]
    if "recruiter_section" not in st.session_state:
        st.session_state.recruiter_section = recruiter_tab_options[0]

    recruiter_section = st.radio(
        "Recruiter Modules",
        recruiter_tab_options,
        horizontal=True,
        key="recruiter_section",
    )


    if recruiter_section == "👥 Candidates":
        db = SessionLocal()
        try:
            candidates = db.query(Candidate).order_by(Candidate.updated_at.desc()).all()
            if candidates:
                rows = []
                for c in candidates:
                    rows.append({"ID": c.id, "Name": c.name, "Email": c.email or "", "Experience (Years)": c.experience_years or 0, "Resume": c.resume_filename or "Not uploaded"})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No candidates are available yet.")
        finally:
            db.close()

    if recruiter_section == "💼 Jobs":
        st.subheader("💼 Job Management")

        api_data = call_fastapi("/ats/jobs")

        if api_data is None:
            st.error(
                "⚠️ FastAPI backend is not reachable. "
                "Please make sure the FastAPI terminal is running."
            )
        else:
            jobs = api_data.get("jobs", [])

            if jobs:
                rows = []

                for job in jobs:
                    rows.append({
                        "Job ID": job.get("job_id") or job.get("id"),
                        "Title": job.get("title") or "",
                        "Required Experience": job.get("experience_required") or 0,
                        "Location": job.get("location") or "",
                        "Status": job.get("status") or "Open",
                    })

                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("No jobs are available.")

    if recruiter_section == "📋 Applications":
        st.subheader("📋 Applications")

        api_data = call_fastapi("/ats/applications")

        if api_data is None:
            st.error(
                "⚠️ FastAPI backend is not reachable. "
                "Please make sure the FastAPI terminal is running."
            )
        else:
            applications = api_data.get("applications", [])

            if applications:
                rows = []

                for application in applications:
                    rows.append({
                        "Application ID": application.get("id"),
                        "Candidate": application.get("candidate_name") or "",
                        "Email": application.get("candidate_email") or "",
                        "Job": application.get("job_title") or "",
                        "Status": application.get("status") or "Applied",
                        "Applied On": application.get("applied_at") or "",
                    })

                st.dataframe(
                    pd.DataFrame(rows),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "No applications yet. They will appear here after candidates apply."
                )

    if recruiter_section == "🎙️ Voice Screening":
        db = SessionLocal()
        try:
            screenings = db.query(VoiceScreening).order_by(VoiceScreening.created_at.desc()).all()
            if screenings:
                rows = []
                for screening in screenings:
                    candidate = db.query(Candidate).filter(Candidate.id == screening.candidate_id).first()
                    job = db.query(Job).filter(Job.id == screening.job_id).first()
                    rows.append({"ID": screening.id, "Candidate": candidate.name if candidate else f"Candidate #{screening.candidate_id}", "Job": job.title if job else f"Job #{screening.job_id}", "Clarity (%)": screening.clarity_score, "Confidence (%)": screening.confidence_score, "Relevance (%)": screening.relevance_score, "Overall (%)": screening.overall_score, "Recommendation": screening.recommendation})
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.info("No voice screenings yet. Candidate voice-screening results will appear here.")
        finally:
            db.close()

    if recruiter_section == "🏆 AI Ranking & Decisions":
        st.subheader("🏆 AI Candidate Ranking & Recruiter Decisions")
        st.write("Applicants are ranked using candidate-job matching, adaptive AI interview performance, and voice-screening performance.")
        st.caption("Final Score = 50% Matching + 30% AI Interview + 20% Voice Screening")

        db = SessionLocal()
        try:
            applications = db.query(Application).order_by(Application.applied_at.desc()).all()
            ranking_rows = []

            for application in applications:
                candidate = application.candidate
                job = application.job
                if not candidate or not job:
                    continue

                try:
                    match_result = calculate_match(_db_candidate_for_matching(candidate), _db_job_for_matching(job))
                    match_score = float(match_result.get("hiring_score", 0) or 0)
                except Exception:
                    match_score = 0.0

                interview_score = _average_interview_score(db, candidate.id, job.id)
                voice_score = _latest_voice_score(db, candidate.id, job.id)
                final_score = _final_recruitment_score(match_score, interview_score, voice_score)

                ranking_rows.append({
                    "Application ID": application.id,
                    "Candidate": candidate.name or f"Candidate #{candidate.id}",
                    "Job": job.title or f"Job #{job.id}",
                    "Matching (%)": round(match_score, 2),
                    "Interview (%)": round(interview_score, 2) if interview_score is not None else None,
                    "Voice (%)": round(voice_score, 2) if voice_score is not None else None,
                    "Final Score (%)": final_score,
                    "Decision": application.status or "Applied",
                })

            ranking_rows.sort(key=lambda row: row["Final Score (%)"], reverse=True)

            if not ranking_rows:
                st.info("No applications are available for AI ranking yet.")
            else:
                for rank, row in enumerate(ranking_rows, start=1):
                    row["Rank"] = rank

                ranking_df = pd.DataFrame(ranking_rows)[["Rank", "Application ID", "Candidate", "Job", "Matching (%)", "Interview (%)", "Voice (%)", "Final Score (%)", "Decision"]]
                st.dataframe(ranking_df, use_container_width=True, hide_index=True)

                st.divider()
                st.subheader("⚖️ Recruiter Decision Controls")
                st.caption("Shortlist, Hold, or Reject an application. The decision is saved in MySQL.")

                for rank, row in enumerate(ranking_rows, start=1):
                    app_id = row["Application ID"]
                    with st.container(border=True):
                        head1, head2, head3 = st.columns([3, 2, 2])
                        with head1:
                            st.markdown(f"### #{rank} — {row['Candidate']}")
                            st.write(f"**Job:** {row['Job']} • **Application ID:** {app_id}")
                        with head2:
                            st.metric("Final Score", f"{row['Final Score (%)']:.2f}%")
                        with head3:
                            st.metric("Current Decision", row["Decision"])

                        score1, score2, score3 = st.columns(3)
                        with score1:
                            st.write(f"**Matching:** {row['Matching (%)']:.2f}%")
                        with score2:
                            value = f"{row['Interview (%)']:.2f}%" if row["Interview (%)"] is not None else "Not completed"
                            st.write(f"**AI Interview:** {value}")
                        with score3:
                            value = f"{row['Voice (%)']:.2f}%" if row["Voice (%)"] is not None else "Not completed"
                            st.write(f"**Voice Screening:** {value}")

                        action1, action2, action3 = st.columns(3)
                        with action1:
                            if st.button(
                                "✅ Shortlist",
                                key=f"shortlist_{app_id}",
                                use_container_width=True,
                            ):
                                api_result = call_fastapi(
                                    f"/ats/applications/{app_id}/status",
                                    method="PUT",
                                    payload={"status": "Shortlisted"},
                                )
                                if api_result is None:
                                    st.error(
                                        "⚠️ FastAPI backend is not reachable. "
                                        "Please make sure the FastAPI terminal is running."
                                    )
                                else:
                                    st.success("Candidate shortlisted successfully.")
                                    st.rerun()

                        with action2:
                            if st.button(
                                "⏸️ Hold",
                                key=f"hold_{app_id}",
                                use_container_width=True,
                            ):
                                api_result = call_fastapi(
                                    f"/ats/applications/{app_id}/status",
                                    method="PUT",
                                    payload={"status": "Hold"},
                                )
                                if api_result is None:
                                    st.error(
                                        "⚠️ FastAPI backend is not reachable. "
                                        "Please make sure the FastAPI terminal is running."
                                    )
                                else:
                                    st.success("Candidate placed on hold.")
                                    st.rerun()

                        with action3:
                            if st.button(
                                "❌ Reject",
                                key=f"reject_{app_id}",
                                use_container_width=True,
                            ):
                                api_result = call_fastapi(
                                    f"/ats/applications/{app_id}/status",
                                    method="PUT",
                                    payload={"status": "Rejected"},
                                )
                                if api_result is None:
                                    st.error(
                                        "⚠️ FastAPI backend is not reachable. "
                                        "Please make sure the FastAPI terminal is running."
                                    )
                                else:
                                    st.success("Candidate rejected.")
                                    st.rerun()
        finally:
            db.close()

    # ============================================================
    # MILESTONE 4E — FINAL RECRUITMENT DASHBOARD & REPORTS
    # ============================================================

    if recruiter_section == "📊 Final Reports":
        st.subheader("📊 Final Recruitment Dashboard & Reports")
        st.write(
            "A complete recruiter summary of applications, decisions, candidate ranking, "
            "interview performance, and voice-screening performance."
        )

        db = SessionLocal()
        try:
            applications = db.query(Application).all()
            candidates = db.query(Candidate).all()
            jobs = db.query(Job).all()
            ranking_rows = _build_recruitment_ranking(db)

            total_applications = len(applications)
            shortlisted = sum(
                1 for a in applications if (a.status or "Applied") == "Shortlisted"
            )
            on_hold = sum(
                1 for a in applications if (a.status or "Applied") == "Hold"
            )
            rejected = sum(
                1 for a in applications if (a.status or "Applied") == "Rejected"
            )
            pending = total_applications - shortlisted - on_hold - rejected

            metric1, metric2, metric3, metric4, metric5 = st.columns(5)
            with metric1:
                st.metric("👥 Candidates", len(candidates))
            with metric2:
                st.metric("💼 Jobs", len(jobs))
            with metric3:
                st.metric("📋 Applications", total_applications)
            with metric4:
                st.metric("✅ Shortlisted", shortlisted)
            with metric5:
                st.metric("⏳ Pending", max(pending, 0))

            st.divider()

            if not ranking_rows:
                st.info(
                    "No applications are available yet. Candidate recruitment reports "
                    "will appear after a candidate applies for a job."
                )
            else:
                st.subheader("🏆 Final Candidate Ranking")
                report_df = pd.DataFrame(ranking_rows)[
                    [
                        "Rank",
                        "Candidate",
                        "Email",
                        "Job",
                        "Matching (%)",
                        "Interview (%)",
                        "Voice (%)",
                        "Final Score (%)",
                        "Decision",
                        "Applied On",
                    ]
                ]
                st.dataframe(
                    report_df,
                    use_container_width=True,
                    hide_index=True,
                )

                st.divider()
                st.subheader("📈 Recruitment Analytics")

                chart_col1, chart_col2 = st.columns(2)

                with chart_col1:
                    st.markdown("**Application Decisions**")
                    decision_df = pd.DataFrame(
                        {
                            "Status": [
                                "Applied",
                                "Shortlisted",
                                "Hold",
                                "Rejected",
                            ],
                            "Count": [
                                pending,
                                shortlisted,
                                on_hold,
                                rejected,
                            ],
                        }
                    ).set_index("Status")
                    st.bar_chart(decision_df)

                with chart_col2:
                    st.markdown("**Top Candidate Scores**")
                    score_chart = pd.DataFrame(
                        [
                            {
                                "Candidate": row["Candidate"],
                                "Final Score": row["Final Score (%)"],
                            }
                            for row in ranking_rows[:10]
                        ]
                    ).set_index("Candidate")
                    st.bar_chart(score_chart)

                st.divider()
                st.subheader("📌 Recruitment Summary")

                avg_final = sum(
                    row["Final Score (%)"] for row in ranking_rows
                ) / len(ranking_rows)
                avg_matching = sum(
                    row["Matching (%)"] for row in ranking_rows
                ) / len(ranking_rows)

                summary1, summary2, summary3, summary4 = st.columns(4)
                with summary1:
                    st.metric("Average Final Score", f"{avg_final:.2f}%")
                with summary2:
                    st.metric("Average Matching Score", f"{avg_matching:.2f}%")
                with summary3:
                    st.metric("On Hold", on_hold)
                with summary4:
                    st.metric("Rejected", rejected)

                st.divider()
                st.subheader("📥 Download Recruitment Report")
                csv_data = report_df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="⬇️ Download Final Recruitment Report (CSV)",
                    data=csv_data,
                    file_name="final_recruitment_report.csv",
                    mime="text/csv",
                    use_container_width=True,
                )

                st.caption(
                    "Report includes candidate ranking, matching score, AI interview score, "
                    "voice score, final recruitment score, application decision, and date."
                )
        finally:
            db.close()


else:

    show_portal_header()

    # ============================================================
    # UPLOAD RESUME
    # ============================================================

    st.markdown('<div id="candidate-resume"></div>', unsafe_allow_html=True)
    st.subheader(
        "📤 Upload Resume"
    )

    uploaded_file = st.file_uploader(
        "Choose a PDF or DOCX resume",
        type=[
            "pdf",
            "docx",
        ],
        help="Upload a candidate resume in PDF or DOCX format.",
    )


    # ============================================================
    # PROCESS RESUME
    # ============================================================

    if uploaded_file is not None:

        st.success(
            f"Uploaded successfully: "
            f"{uploaded_file.name}"
        )

        file_extension = os.path.splitext(
            uploaded_file.name
        )[1].lower()

        temp_path = None

        try:

            # ====================================================
            # SAVE TEMPORARY FILE
            # ====================================================

            with tempfile.NamedTemporaryFile(
                delete=False,
                suffix=file_extension,
            ) as temp_file:

                temp_file.write(
                    uploaded_file.getbuffer()
                )

                temp_path = temp_file.name

            # ====================================================
            # EXTRACT TEXT
            # ====================================================

            with st.spinner(
                "🔍 Extracting text from resume..."
            ):

                text = extract_text(
                    temp_path
                )

            if not text or not text.strip():

                st.error(
                    "❌ Could not extract text from the resume."
                )

                st.stop()

            st.success(
                "✅ Resume text extracted successfully."
            )

            # ====================================================
            # BUILD CANDIDATE PROFILE
            # ====================================================

            with st.spinner(
                "🤖 Building candidate profile..."
            ):

                profile = build_candidate_profile(
                    text
                )

            st.session_state.candidate_profile = profile

            st.session_state.candidate_filename = (
                uploaded_file.name
            )

            # ====================================================
            # STORE CANDIDATE
            # ====================================================

            candidate_record = profile.copy()

            candidate_record["filename"] = (
                uploaded_file.name
            )

            candidate_record["experience_years"] = (
                extract_experience_years(
                    profile.get(
                        "experience",
                        [],
                    )
                )
            )

            existing_candidates = [
                candidate
                for candidate in (
                    st.session_state.candidate_profiles
                )
                if candidate.get("filename")
                != uploaded_file.name
            ]

            existing_candidates.append(
                candidate_record
            )

            st.session_state.candidate_profiles = (
                existing_candidates
            )

            # ====================================================
            # CANDIDATE INFORMATION
            # ====================================================

            st.subheader(
                "👤 Candidate Information"
            )

            col1, col2, col3 = st.columns(3)

            with col1:

                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">'
                    'Candidate Name'
                    '</div>'
                    '<div class="info-value">'
                    f'{profile.get("name") or "Not detected"}'
                    '</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            with col2:

                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">'
                    'Email'
                    '</div>'
                    '<div class="info-value">'
                    f'{profile.get("email") or "Not detected"}'
                    '</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            with col3:

                st.markdown(
                    '<div class="info-card">'
                    '<div class="info-label">'
                    'Phone'
                    '</div>'
                    '<div class="info-value">'
                    f'{profile.get("phone") or "Not detected"}'
                    '</div>'
                    '</div>',
                    unsafe_allow_html=True,
                )

            # ====================================================
            # STRUCTURED PROFILE
            # ====================================================

            st.subheader(
                "📋 Structured Candidate Profile"
            )

            with st.expander(
                "🎓 Education",
                expanded=True,
            ):

                education = clean_list(
                    profile.get(
                        "education",
                        [],
                    )
                )

                if education:

                    for item in education:

                        st.write(
                            f"• {item}"
                        )

                else:

                    st.info(
                        "No education information detected."
                    )

            with st.expander(
                "🛠️ Skills",
                expanded=True,
            ):

                skills = clean_list(
                    profile.get(
                        "skills",
                        [],
                    )
                )

                if skills:

                    skill_html = (
                        '<div class="skill-box">'
                    )

                    for skill in skills:

                        skill_html += (
                            '<span class="skill-pill">'
                            f'{skill}'
                            '</span>'
                        )

                    skill_html += "</div>"

                    st.markdown(
                        skill_html,
                        unsafe_allow_html=True,
                    )

                else:

                    st.info(
                        "No skills detected."
                    )

            with st.expander(
                "💼 Experience",
                expanded=True,
            ):

                experience = clean_list(
                    profile.get(
                        "experience",
                        [],
                    )
                )

                if experience:

                    for item in experience:

                        st.write(
                            f"• {item}"
                        )

                else:

                    st.info(
                        "No experience information detected."
                    )

            with st.expander(
                "🏆 Certifications",
                expanded=True,
            ):

                certifications = clean_list(
                    profile.get(
                        "certifications",
                        [],
                    )
                )

                if certifications:

                    for item in certifications:

                        st.write(
                            f"• {item}"
                        )

                else:

                    st.info(
                        "No certifications detected."
                    )

            with st.expander(
                "🚀 Projects",
                expanded=True,
            ):

                projects = clean_list(
                    profile.get(
                        "projects",
                        [],
                    )
                )

                if projects:

                    for item in projects:

                        st.write(
                            f"• {item}"
                        )

                else:

                    st.info(
                        "No project information detected."
                    )

            # ====================================================
            # MILESTONE 1 ACCURACY
            # ====================================================

            st.divider()

            st.header(
                "📊 Resume Extraction Validation"
            )

            ground_truth = load_ground_truth()

            expected_profile = find_ground_truth(
                uploaded_file.name,
                ground_truth,
            )

            if expected_profile is None:

                st.warning(
                    "⚠️ Accuracy validation is not available "
                    "because no matching ground truth profile "
                    "was found in expected_profiles.json."
                )

            else:

                (
                    accuracy,
                    correct,
                    total,
                    results,
                ) = calculate_accuracy(
                    profile,
                    expected_profile,
                )

                col1, col2, col3 = st.columns(3)

                with col1:

                    st.metric(
                        "Fields Tested",
                        total,
                    )

                with col2:

                    st.metric(
                        "Fields Correct",
                        f"{correct}/{total}",
                    )

                with col3:

                    st.metric(
                        "Extraction Accuracy",
                        f"{accuracy:.2f}%",
                    )

                st.markdown(
                    "### 📈 Overall Extraction Accuracy"
                )

                st.progress(
                    min(
                        accuracy / 100,
                        1.0,
                    )
                )

                st.write(
                    f"Current Accuracy: "
                    f"**{accuracy:.2f}%**"
                )

                st.write(
                    "Extraction Target: **95%**"
                )

                if accuracy >= 95:

                    st.markdown(
                        '<div class="success-box">'
                        '🎯 Extraction target achieved! '
                        f'Extraction Accuracy: '
                        f'{accuracy:.2f}%'
                        '</div>',
                        unsafe_allow_html=True,
                    )

                else:

                    st.warning(
                        f"Current extraction accuracy is "
                        f"{accuracy:.2f}%. "
                        f"Target: 95%."
                    )

                # =================================================
                # FIELD-WISE ACCURACY
                # =================================================

                st.markdown(
                    "### 📊 Field-wise Extraction Analysis"
                )

                field_names = {
                    "name": "Name",
                    "email": "Email",
                    "phone": "Phone",
                    "education": "Education",
                    "skills": "Skills",
                    "experience": "Experience",
                    "certifications": "Certifications",
                    "projects": "Projects",
                }

                field_data = []

                for field, matched in results.items():

                    display_name = field_names.get(
                        field,
                        field.title(),
                    )

                    score = (
                        100
                        if matched
                        else 0
                    )

                    field_data.append(
                        {
                            "Field": display_name,
                            "Accuracy": score,
                        }
                    )

                field_df = pd.DataFrame(
                    field_data
                )

                st.bar_chart(
                    field_df.set_index(
                        "Field"
                    )
                )

                for field, matched in results.items():

                    display_name = field_names.get(
                        field,
                        field.title(),
                    )

                    score = (
                        100
                        if matched
                        else 0
                    )

                    c1, c2, c3 = st.columns(
                        [2, 5, 1]
                    )

                    with c1:

                        st.write(
                            (
                                f"✅ **{display_name}**"
                                if matched
                                else
                                f"❌ **{display_name}**"
                            )
                        )

                    with c2:

                        st.progress(
                            score / 100
                        )

                    with c3:

                        st.write(
                            f"**{score}%**"
                        )

            # ====================================================
            # MILESTONE 2
            # ====================================================

            st.divider()

            st.markdown('<div id="candidate-matching"></div>', unsafe_allow_html=True)
            st.header(
                "🤖 AI Job Matching & Skill Analysis"
            )

            st.write(
                "Match the extracted candidate profile "
                "against job requirements and generate "
                "a hiring compatibility score."
            )

            jobs = load_jobs()

            if not jobs:

                st.warning(
                    "⚠️ No jobs found. Make sure "
                    "jobs/job_profiles.json exists."
                )

            else:

                # =================================================
                # JOB SELECTION
                # =================================================

                job_titles = [
                    job.get(
                        "title",
                        "Untitled Job",
                    )
                    for job in jobs
                ]

                selected_job_title = st.selectbox(
                    "💼 Select Job",
                    job_titles,
                    key="selected_job_title",
                )

                selected_job = next(
                    (
                        job
                        for job in jobs
                        if job.get("title")
                        == selected_job_title
                    ),
                    None,
                )

                st.session_state.selected_job_data = selected_job

                if selected_job:

                    # =============================================
                    # JOB DETAILS
                    # =============================================

                    st.subheader(
                        "💼 Selected Job"
                    )

                    job_col1, job_col2 = st.columns(2)

                    with job_col1:

                        st.write(
                            f"**Job ID:** "
                            f"{selected_job.get('job_id', 'N/A')}"
                        )

                        st.write(
                            f"**Job Title:** "
                            f"{selected_job.get('title', 'N/A')}"
                        )

                        st.write(
                            f"**Experience Required:** "
                            f"{selected_job.get('experience_required', 0)} years"
                        )

                    with job_col2:

                        st.write(
                            f"**Education Required:** "
                            f"{selected_job.get('education_required', 'N/A')}"
                        )

                        st.write(
                            "**Required Skills:**"
                        )

                        st.write(
                            ", ".join(
                                selected_job.get(
                                    "required_skills",
                                    [],
                                )
                            )
                        )

                    if selected_job.get(
                        "description"
                    ):

                        with st.expander(
                            "📄 View Job Description"
                        ):

                            st.write(
                                selected_job[
                                    "description"
                                ]
                            )

                    # =============================================
                    # PREPARE CANDIDATE
                    # =============================================

                    candidate_experience = (
                        extract_experience_years(
                            profile.get(
                                "experience",
                                [],
                            )
                        )
                    )

                    candidate_education = (
                        education_to_text(
                            profile.get(
                                "education",
                                [],
                            )
                        )
                    )

                    matching_candidate = {
                        "name": profile.get(
                            "name",
                            "Unknown Candidate",
                        ),
                        "skills": profile.get(
                            "skills",
                            [],
                        ),
                        "experience": candidate_experience,
                        "education": candidate_education,
                    }

                    st.info(
                        f"📌 Detected candidate experience: "
                        f"**{candidate_experience} years**"
                    )

                    # =============================================
                    # MATCHING
                    # =============================================

                    match_result = calculate_match(
                        matching_candidate,
                        selected_job,
                    )

                    # =============================================
                    # SKILL GAP
                    # =============================================

                    gap_report = generate_skill_gap_report(
                        matching_candidate,
                        selected_job,
                        match_result,
                    )

                    # =============================================
                    # HIRING SCORE
                    # =============================================

                    st.subheader(
                        "🎯 Hiring Compatibility Score"
                    )

                    score_col1, score_col2, score_col3 = (
                        st.columns(3)
                    )

                    with score_col1:

                        st.metric(
                            "Overall Hiring Score",
                            f"{match_result['hiring_score']:.2f}%",
                        )

                    with score_col2:

                        st.metric(
                            "Skill Compatibility",
                            f"{match_result['skill_score']:.2f}%",
                        )

                    with score_col3:

                        st.metric(
                            "Experience Match",
                            f"{match_result['experience_score']:.2f}%",
                        )

                    st.progress(
                        min(
                            match_result[
                                "hiring_score"
                            ] / 100,
                            1.0,
                        )
                    )

                    hiring_score = match_result[
                        "hiring_score"
                    ]

                    if hiring_score >= 85:

                        st.markdown(
                            '<div class="success-box">'
                            '🌟 Strong Candidate Match — '
                            f'{hiring_score:.2f}% compatibility'
                            '</div>',
                            unsafe_allow_html=True,
                        )

                    elif hiring_score >= 70:

                        st.info(
                            f"👍 Good Candidate Match — "
                            f"{hiring_score:.2f}% compatibility"
                        )

                    elif hiring_score >= 50:

                        st.warning(
                            f"⚠️ Moderate Candidate Match — "
                            f"{hiring_score:.2f}% compatibility"
                        )

                    else:

                        st.error(
                            f"❌ Low Candidate Match — "
                            f"{hiring_score:.2f}% compatibility"
                        )

                    # =============================================
                    # SCORE BREAKDOWN
                    # =============================================

                    st.subheader(
                        "📊 Matching Score Breakdown"
                    )

                    score_breakdown = pd.DataFrame(
                        {
                            "Component": [
                                "Skills",
                                "Experience",
                                "Education",
                            ],
                            "Score": [
                                match_result[
                                    "skill_score"
                                ],
                                match_result[
                                    "experience_score"
                                ],
                                match_result[
                                    "education_score"
                                ],
                            ],
                        }
                    )

                    st.bar_chart(
                        score_breakdown.set_index(
                            "Component"
                        )
                    )

                    st.caption(
                        "Weights: Skills 60% • "
                        "Experience 25% • "
                        "Education 15%"
                    )

                    st.metric(
                        "🎓 Education Compatibility",
                        f"{match_result['education_score']:.2f}%",
                    )

                    # =============================================
                    # MATCHED SKILLS
                    # =============================================

                    st.subheader(
                        "✅ Matched Skills"
                    )

                    matched_skills = (
                        match_result.get(
                            "matched_skills",
                            [],
                        )
                    )

                    if matched_skills:

                        matched_html = (
                            '<div class="skill-box">'
                        )

                        for skill in matched_skills:

                            matched_html += (
                                '<span class="skill-pill">'
                                f'✓ {skill}'
                                '</span>'
                            )

                        matched_html += (
                            "</div>"
                        )

                        st.markdown(
                            matched_html,
                            unsafe_allow_html=True,
                        )

                    else:

                        st.warning(
                            "No required skills were matched."
                        )

                    # =============================================
                    # MISSING SKILLS
                    # =============================================

                    st.subheader(
                        "❌ Skill Gaps"
                    )

                    missing_skills = (
                        match_result.get(
                            "missing_skills",
                            [],
                        )
                    )

                    if missing_skills:

                        for skill in missing_skills:

                            st.write(
                                f"🔴 **{skill}**"
                            )

                    else:

                        st.success(
                            "🎉 No skill gaps detected!"
                        )

                    # =============================================
                    # SKILL GAP REPORT
                    # =============================================

                    st.subheader(
                        "📚 Skill-Gap Analysis Report"
                    )

                    report_col1, report_col2 = (
                        st.columns(2)
                    )

                    with report_col1:

                        st.metric(
                            "Matched Skills",
                            len(
                                matched_skills
                            ),
                        )

                    with report_col2:

                        st.metric(
                            "Missing Skills",
                            len(
                                missing_skills
                            ),
                        )

                    recommendations = (
                        gap_report.get(
                            "recommendations",
                            [],
                        )
                    )

                    if recommendations:

                        st.markdown(
                            "### 🎓 Recommendations"
                        )

                        for recommendation in (
                            recommendations
                        ):

                            st.write(
                                f"📌 {recommendation}"
                            )

                    else:

                        st.success(
                            "No additional skill training "
                            "recommendations are required."
                        )

                    # =============================================
                    # MILESTONE 2 STATUS
                    # =============================================

                    st.subheader(
                        "🏆 Matching Quality"
                    )

                    st.write(
                        "Target: **Matching Accuracy ≥85%**"
                    )

                    st.write(
                        "Skill-Gap Report: "
                        "**Generated Successfully ✅**"
                    )

                    with st.expander(
                        "🧾 View Complete Matching Report"
                    ):

                        st.json(
                            gap_report
                        )

            # ====================================================
            # MULTI-CANDIDATE RANKING
            # ====================================================

            st.divider()

            st.header(
                "🏆 Candidate Ranking"
            )

            st.write(
                "Compare all resumes processed during "
                "this session against the selected job."
            )

            all_candidates = (
                st.session_state.candidate_profiles
            )

            if not jobs:

                st.info(
                    "Job data is required for candidate ranking."
                )

            elif not all_candidates:

                st.info(
                    "Upload resumes to create a candidate ranking."
                )

            else:

                ranking_data = []

                for candidate in all_candidates:

                    candidate_experience = candidate.get(
                        "experience_years",
                        extract_experience_years(
                            candidate.get(
                                "experience",
                                [],
                            )
                        ),
                    )

                    candidate_education = (
                        education_to_text(
                            candidate.get(
                                "education",
                                [],
                            )
                        )
                    )

                    ranking_candidate = {
                        "name": candidate.get(
                            "name",
                            "Unknown Candidate",
                        ),
                        "skills": candidate.get(
                            "skills",
                            [],
                        ),
                        "experience": candidate_experience,
                        "education": candidate_education,
                    }

                    ranking_result = calculate_match(
                        ranking_candidate,
                        selected_job,
                    )

                    ranking_data.append(
                        {
                            "Candidate": candidate.get(
                                "name",
                                "Unknown",
                            ),
                            "Hiring Score (%)": ranking_result[
                                "hiring_score"
                            ],
                            "Skill Match (%)": ranking_result[
                                "skill_score"
                            ],
                            "Experience Match (%)": ranking_result[
                                "experience_score"
                            ],
                            "Education Match (%)": ranking_result[
                                "education_score"
                            ],
                        }
                    )

                ranking_df = pd.DataFrame(
                    ranking_data
                )

                ranking_df = ranking_df.sort_values(
                    by="Hiring Score (%)",
                    ascending=False,
                ).reset_index(
                    drop=True
                )

                ranking_df.insert(
                    0,
                    "Rank",
                    range(
                        1,
                        len(ranking_df) + 1,
                    ),
                )

                st.dataframe(
                    ranking_df,
                    use_container_width=True,
                    hide_index=True,
                )

                if not ranking_df.empty:

                    top_candidate = ranking_df.iloc[0]

                    st.success(
                        f"🏆 Top Candidate: "
                        f"**{top_candidate['Candidate']}** "
                        f"with a hiring score of "
                        f"**{top_candidate['Hiring Score (%)']:.2f}%**"
                    )

                    st.subheader(
                        "📊 Candidate Hiring Score Comparison"
                    )

                    chart_df = ranking_df[
                        [
                            "Candidate",
                            "Hiring Score (%)",
                        ]
                    ].set_index(
                        "Candidate"
                    )

                    st.bar_chart(
                        chart_df,
                        use_container_width=True,
                    )

                ranking_csv = ranking_df.to_csv(
                    index=False
                )

                st.download_button(
                    "⬇️ Download Candidate Ranking",
                    data=ranking_csv,
                    file_name="candidate_ranking.csv",
                    mime="text/csv",
                )

            # ====================================================
            # MILESTONE 2 EVALUATION
            # ====================================================

            st.divider()

            st.header(
                "📈 Matching Accuracy Evaluation"
            )

            st.write(
                "Evaluate candidate-job matching against "
                "the predefined matching evaluation dataset."
            )

            evaluation_cases = (
                load_evaluation_cases()
            )

            if not evaluation_cases:

                st.warning(
                    "⚠️ No matching evaluation cases found. "
                    "Check milestone2_evaluation.json."
                )

            elif not all_candidates:

                st.info(
                    "Upload the candidate resumes required "
                    "by the evaluation dataset."
                )

            else:

                evaluation_candidates = []

                for candidate in all_candidates:

                    evaluation_candidates.append(
                        {
                            "name": candidate.get(
                                "name",
                                "Unknown",
                            ),
                            "skills": candidate.get(
                                "skills",
                                [],
                            ),
                            "experience": candidate.get(
                                "experience_years",
                                extract_experience_years(
                                    candidate.get(
                                        "experience",
                                        [],
                                    )
                                ),
                            ),
                            "education": education_to_text(
                                candidate.get(
                                    "education",
                                    [],
                                )
                            ),
                        }
                    )

                (
                    evaluation_accuracy,
                    evaluation_correct,
                    evaluation_total,
                    evaluation_results,
                ) = calculate_evaluation_accuracy(
                    evaluation_candidates,
                    jobs,
                    evaluation_cases,
                )

                col1, col2, col3 = st.columns(3)

                with col1:

                    st.metric(
                        "Test Cases Evaluated",
                        evaluation_total,
                    )

                with col2:

                    st.metric(
                        "Correct Predictions",
                        (
                            f"{evaluation_correct}/"
                            f"{evaluation_total}"
                        ),
                    )

                with col3:

                    st.metric(
                        "Matching Accuracy",
                        f"{evaluation_accuracy:.2f}%",
                    )

                st.progress(
                    min(
                        evaluation_accuracy / 100,
                        1.0,
                    )
                )

                st.write(
                    "Matching Target: **≥85%**"
                )

                if evaluation_accuracy >= 85:

                    st.markdown(
                        '<div class="success-box">'
                        '🎯 Matching target achieved! '
                        f'Accuracy: '
                        f'{evaluation_accuracy:.2f}%'
                        '</div>',
                        unsafe_allow_html=True,
                    )

                else:

                    st.warning(
                        f"Current matching accuracy: "
                        f"{evaluation_accuracy:.2f}%. "
                        f"Target: 85%."
                    )

                if evaluation_results:

                    st.subheader(
                        "🔎 Evaluation Results"
                    )

                    evaluation_df = pd.DataFrame(
                        evaluation_results
                    )

                    evaluation_df["Status"] = (
                        evaluation_df[
                            "correct"
                        ].apply(
                            lambda value:
                            "✅ Correct"
                            if value
                            else "❌ Incorrect"
                        )
                    )

                    evaluation_df = evaluation_df[
                        [
                            "candidate",
                            "job_title",
                            "hiring_score",
                            "predicted_match",
                            "expected_match",
                            "Status",
                        ]
                    ]

                    evaluation_df.columns = [
                        "Candidate",
                        "Job",
                        "Hiring Score (%)",
                        "Predicted Match",
                        "Expected Match",
                        "Status",
                    ]

                    st.dataframe(
                        evaluation_df,
                        use_container_width=True,
                        hide_index=True,
                    )

                    evaluation_csv = (
                        evaluation_df.to_csv(
                            index=False
                        )
                    )

                    st.download_button(
                        "⬇️ Download Matching Evaluation",
                        data=evaluation_csv,
                        file_name=(
                            "milestone2_matching_evaluation.csv"
                        ),
                        mime="text/csv",
                    )

        except Exception as error:

            st.error(
                "❌ An error occurred while processing "
                "the resume."
            )

            st.exception(error)

        finally:

            if (
                temp_path
                and os.path.exists(temp_path)
            ):

                try:

                    os.remove(temp_path)

                except Exception:

                    pass


    # ============================================================
    
    # ============================================================
    # MILESTONE 4B — CANDIDATE JOB APPLICATION SYSTEM
    # ============================================================

    st.divider()
    st.markdown('<div id="candidate-applications"></div>', unsafe_allow_html=True)
    st.header("📋 Job Applications")
    st.write(
        "Apply for the selected job and store the application in MySQL. "
        "Candidates can apply once per job and track their application status."
    )

    application_profile = st.session_state.get("candidate_profile")
    application_job = st.session_state.get("selected_job_data")

    if not application_profile:
        st.info("📄 Upload a resume first to create your candidate profile.")
    elif not application_job:
        st.info("💼 Select a job above before applying.")
    else:
        application_job_id = application_job.get("job_id")

        db = SessionLocal()
        try:
            db_job = get_db_job(application_job_id)

            if db_job is None:
                st.error(
                    f"❌ Job {application_job_id or 'N/A'} was not found in MySQL."
                )
            else:
                db_candidate_id = get_or_create_db_candidate(
                    application_profile,
                    st.session_state.get("candidate_filename"),
                )

                existing_application = (
                    db.query(Application)
                    .filter(
                        Application.candidate_id == db_candidate_id,
                        Application.job_id == db_job.id,
                    )
                    .first()
                )

                st.subheader(f"💼 Apply for: {db_job.title}")

                job_col1, job_col2 = st.columns(2)

                with job_col1:
                    st.write(f"**Job ID:** {db_job.job_id or db_job.id}")
                    st.write(
                        f"**Experience Required:** "
                        f"{db_job.experience_required or 0} years"
                    )

                with job_col2:
                    st.write(f"**Location:** {db_job.location or 'Not specified'}")
                    st.write(f"**Status:** {db_job.status or 'Open'}")

                if existing_application:
                    st.success(
                        f"✅ You already applied for **{db_job.title}**."
                    )
                    st.info(
                        f"Application status: **{existing_application.status}**"
                    )
                    st.caption(
                        f"Applied on: {existing_application.applied_at}"
                    )
                elif str(db_job.status or "Open").strip().lower() != "open":
                    st.warning(
                        f"⚠️ This job is currently **{db_job.status}** and is "
                        "not accepting applications."
                    )
                else:
                    st.success(
                        "Your parsed resume profile is ready. "
                        "Submit the application to save it in MySQL."
                    )

                    if st.button(
                        "🚀 Apply for This Job",
                        type="primary",
                        use_container_width=True,
                        key="apply_selected_job",
                    ):
                        application = Application(
                            candidate_id=db_candidate_id,
                            job_id=db_job.id,
                            status="Applied",
                        )

                        db.add(application)
                        db.commit()
                        db.refresh(application)

                        st.success(
                            f"🎉 Application submitted successfully for "
                            f"**{db_job.title}**!"
                        )
                        st.rerun()

                # Candidate's complete application history.
                st.subheader("📌 My Applications")

                applications = (
                    db.query(Application)
                    .filter(Application.candidate_id == db_candidate_id)
                    .order_by(Application.applied_at.desc())
                    .all()
                )

                if applications:
                    application_rows = []

                    for application in applications:
                        job = application.job

                        application_rows.append(
                            {
                                "Application ID": application.id,
                                "Job": (
                                    job.title
                                    if job
                                    else f"Job #{application.job_id}"
                                ),
                                "Job ID": (
                                    job.job_id
                                    if job and job.job_id
                                    else application.job_id
                                ),
                                "Status": application.status,
                                "Applied On": str(application.applied_at),
                            }
                        )

                    st.dataframe(
                        pd.DataFrame(application_rows),
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.caption(
                        "No applications yet. Select a job above and apply."
                    )
        except Exception as exc:
            db.rollback()
            st.error(f"❌ Unable to process the application: {exc}")
        finally:
            db.close()




    # ============================================================
    # MILESTONE 4C — VOICE SCREENING
    # ============================================================

    st.divider()
    st.markdown('<div id="candidate-voice"></div>', unsafe_allow_html=True)
    st.header("🎙️ Voice Screening")
    st.write(
        "Record a short spoken response, transcribe it, evaluate clarity, "
        "confidence and job relevance, and save the screening result in MySQL."
    )

    voice_profile = st.session_state.get("candidate_profile")
    voice_job = st.session_state.get("selected_job_data")

    if not voice_profile:
        st.info("📄 Upload a resume first to create your candidate profile.")
    elif not voice_job:
        st.info("💼 Select a job above before starting voice screening.")
    else:
        voice_job_id = voice_job.get("job_id")

        db = SessionLocal()
        try:
            voice_db_job = get_db_job(voice_job_id)

            if voice_db_job is None:
                st.error(
                    f"❌ Job {voice_job_id or 'N/A'} was not found in MySQL."
                )
            else:
                voice_candidate_id = get_or_create_db_candidate(
                    voice_profile,
                    st.session_state.get("candidate_filename"),
                )

                voice_candidate = (
                    db.query(Candidate)
                    .filter(Candidate.id == voice_candidate_id)
                    .first()
                )

                st.subheader(f"🎤 Voice Screening for: {voice_db_job.title}")

                st.write(
                    "Answer this prompt in **30–90 seconds**. Speak clearly "
                    "about your experience, skills and suitability for the role."
                )

                voice_prompt = (
                    f"Tell us why you are a good fit for the "
                    f"{voice_db_job.title} role and describe one relevant "
                    "project or professional experience."
                )

                st.info(f"🗣️ **Prompt:** {voice_prompt}")

                audio_value = st.audio_input(
                    "🎙️ Record your answer",
                    key="voice_screening_audio",
                )

                if audio_value is not None:
                    st.audio(audio_value)

                    if st.button(
                        "🤖 Transcribe & Evaluate Voice",
                        type="primary",
                        use_container_width=True,
                        key="process_voice_screening",
                    ):
                        temp_dir = Path("data") / "voice_screenings"
                        temp_dir.mkdir(parents=True, exist_ok=True)

                        audio_path = (
                            temp_dir
                            / f"candidate_{voice_candidate_id}_job_{voice_db_job.id}.wav"
                        )

                        with open(audio_path, "wb") as audio_file:
                            audio_file.write(audio_value.getbuffer())

                        try:
                            with st.spinner(
                                "🎧 Transcribing your voice response..."
                            ):
                                transcript = transcribe_audio(str(audio_path))

                            with st.spinner(
                                "📊 Evaluating voice screening..."
                            ):
                                screening = save_voice_screening(
                                    db=db,
                                    candidate_id=voice_candidate_id,
                                    job_id=voice_db_job.id,
                                    audio_path=str(audio_path),
                                    transcript=transcript,
                                    job=voice_db_job,
                                    candidate=voice_candidate,
                                )

                            st.success(
                                "✅ Voice screening completed and saved to MySQL."
                            )

                            st.subheader("📝 Transcript")
                            st.write(screening.transcript)

                            score1, score2, score3, score4 = st.columns(4)

                            with score1:
                                st.metric(
                                    "Clarity",
                                    f"{screening.clarity_score:.1f}%",
                                )

                            with score2:
                                st.metric(
                                    "Confidence",
                                    f"{screening.confidence_score:.1f}%",
                                )

                            with score3:
                                st.metric(
                                    "Relevance",
                                    f"{screening.relevance_score:.1f}%",
                                )

                            with score4:
                                st.metric(
                                    "Overall",
                                    f"{screening.overall_score:.1f}%",
                                )

                            if screening.recommendation == "Strong":
                                st.success(
                                    "🎯 Recommendation: **Strong**"
                                )
                            elif screening.recommendation == "Moderate":
                                st.warning(
                                    "🟡 Recommendation: **Moderate**"
                                )
                            else:
                                st.info(
                                    "🔵 Recommendation: **Needs Improvement**"
                                )

                        except Exception as error:
                            st.error(
                                "❌ Voice processing could not be completed."
                            )
                            st.exception(error)

        finally:
            db.close()

    # MILESTONE 3 — ADAPTIVE AI INTERVIEW COPILOT
    # ============================================================

    st.divider()
    st.markdown('<div id="candidate-interview"></div>', unsafe_allow_html=True)
    st.header("🎤 Adaptive AI Interview")
    st.write(
        "Conduct a live interview where each next question is generated "
        "from the candidate's previous answer, evaluation, resume profile, "
        "and selected job requirements."
    )

    interview_profile = st.session_state.get("candidate_profile")
    interview_job = st.session_state.get("selected_job_data")

    if not interview_profile:
        st.info("📄 Upload a candidate resume first to start the interview.")
    elif not interview_job:
        st.info("💼 Select a job above before starting the interview.")
    else:
        try:
            db_job = get_db_job(interview_job.get("job_id"))

            if db_job is None:
                st.error(
                    f"❌ Job {interview_job.get('job_id', 'N/A')} was not found in MySQL. "
                    "Run the database job seeding/setup step first."
                )
            else:
                db_candidate_id = get_or_create_db_candidate(
                    interview_profile,
                    st.session_state.get("candidate_filename"),
                )

                interview_key = f"{db_candidate_id}_{db_job.id}"

                if st.session_state.get("interview_key") != interview_key:
                    st.session_state.interview_key = interview_key
                    st.session_state.interview_questions = []
                    st.session_state.interview_results = []
                    st.session_state.adaptive_interview_active = False
                    st.session_state.adaptive_interview_finished = False
                    st.session_state.adaptive_question_number = 0
                    st.session_state.adaptive_target_count = 10
                    st.session_state.adaptive_current_question = None
                    st.session_state.adaptive_history = []
                    st.session_state.adaptive_results = []

                st.success(
                    f"Candidate connected to interview system. "
                    f"Candidate ID: {db_candidate_id} • MySQL Job ID: {db_job.id}"
                )

                if ai_configured():
                    st.info(
                        "🧠 Live AI mode is enabled. Each next question can adapt "
                        "to the candidate's previous answer."
                    )
                else:
                    st.warning(
                        "⚠️ Hugging Face AI is not configured. The interview will "
                        "still work using adaptive fallback logic. Add HF_TOKEN "
                        "and HF_MODEL to .env for live LLM-generated questions."
                    )

                st.subheader("⚙️ Interview Setup")

                setup_col1, setup_col2 = st.columns([3, 1])

                with setup_col1:
                    adaptive_question_count = st.slider(
                        "Maximum Interview Questions",
                        min_value=5,
                        max_value=15,
                        value=10,
                        step=1,
                        key="adaptive_question_count",
                    )

                with setup_col2:
                    st.write("")
                    start_interview_clicked = st.button(
                        "▶️ Start / Restart Interview",
                        type="primary",
                        use_container_width=True,
                    )

                if start_interview_clicked:
                    st.session_state.adaptive_interview_active = False
                    st.session_state.adaptive_interview_finished = False
                    st.session_state.adaptive_question_number = 0
                    st.session_state.adaptive_target_count = adaptive_question_count
                    st.session_state.adaptive_current_question = None
                    st.session_state.adaptive_history = []
                    st.session_state.adaptive_results = []

                    with st.spinner(
                        "🧠 AI is generating the first personalized question..."
                    ):
                        db = SessionLocal()
                        try:
                            first_question = generate_first_question(
                                db=db,
                                job_id=db_job.id,
                                candidate_id=db_candidate_id,
                            )
                            question_id = save_question(
                                db=db,
                                job_id=db_job.id,
                                candidate_id=db_candidate_id,
                                question_data=first_question,
                            )
                        finally:
                            db.close()

                    first_question["question_id"] = question_id
                    st.session_state.adaptive_current_question = first_question
                    st.session_state.adaptive_question_number = 1
                    st.session_state.adaptive_interview_active = True
                    st.session_state.adaptive_interview_finished = False
                    st.rerun()

                current_question = st.session_state.get(
                    "adaptive_current_question"
                )

                if (
                    st.session_state.get("adaptive_interview_active")
                    and current_question
                ):
                    current_number = st.session_state.adaptive_question_number
                    target_count = st.session_state.adaptive_target_count

                    st.divider()

                    progress = min(
                        current_number / max(target_count, 1),
                        1.0,
                    )

                    st.progress(
                        progress,
                        text=(
                            f"Interview Progress: Question "
                            f"{current_number} of {target_count}"
                        ),
                    )

                    st.subheader(f"🎯 Live Question {current_number}")

                    st.caption(
                        f"{current_question.get('category', 'Interview')} • "
                        f"{current_question.get('difficulty', 'Intermediate')} • "
                        f"Generated by: {current_question.get('source', 'AI')}"
                    )

                    st.markdown(f"### {current_question['question']}")

                    answer = st.text_area(
                        "Candidate Answer",
                        key=(
                            f"adaptive_answer_"
                            f"{interview_key}_"
                            f"{current_number}"
                        ),
                        height=220,
                        placeholder=(
                            "Type your answer here. "
                            "The next question will adapt to this answer."
                        ),
                    )

                    submit_answer_clicked = st.button(
                        "➡️ Submit Answer & Generate Next Question",
                        type="primary",
                        use_container_width=True,
                    )

                    if submit_answer_clicked:
                        answer = answer.strip()

                        if not answer:
                            st.warning(
                                "Please enter an answer before continuing."
                            )
                        else:
                            with st.spinner(
                                "📊 Evaluating your answer and generating "
                                "the next adaptive question..."
                            ):
                                db = SessionLocal()
                                try:
                                    evaluation = evaluate_and_save(
                                        db=db,
                                        candidate_id=db_candidate_id,
                                        job_id=db_job.id,
                                        answer=answer,
                                        expected_topics=current_question.get(
                                            "expected_topics",
                                            [],
                                        ),
                                        question_id=current_question.get(
                                            "question_id"
                                        ),
                                    )

                                    history_entry = {
                                        "question": current_question["question"],
                                        "answer": answer,
                                        "evaluation": evaluation,
                                    }

                                    st.session_state.adaptive_history.append(
                                        history_entry
                                    )
                                    st.session_state.adaptive_results.append(
                                        evaluation
                                    )

                                    if current_number >= target_count:
                                        st.session_state.adaptive_interview_active = False
                                        st.session_state.adaptive_interview_finished = True
                                        st.session_state.adaptive_current_question = None
                                    else:
                                        next_number = current_number + 1

                                        next_question = generate_next_question(
                                            db=db,
                                            job_id=db_job.id,
                                            candidate_id=db_candidate_id,
                                            previous_question=current_question[
                                                "question"
                                            ],
                                            previous_answer=answer,
                                            evaluation=evaluation,
                                            question_number=next_number,
                                            interview_history=st.session_state.adaptive_history,
                                        )

                                        next_question_id = save_question(
                                            db=db,
                                            job_id=db_job.id,
                                            candidate_id=db_candidate_id,
                                            question_data=next_question,
                                        )

                                        next_question["question_id"] = next_question_id

                                        st.session_state.adaptive_current_question = (
                                            next_question
                                        )
                                        st.session_state.adaptive_question_number = (
                                            next_number
                                        )
                                finally:
                                    db.close()

                            st.rerun()

                if st.session_state.get("adaptive_interview_finished"):
                    results = st.session_state.get("adaptive_results", [])

                    st.divider()
                    st.subheader("🏆 Final Interview Results")

                    if results:
                        overall_scores = [
                            float(result.get("overall_score", 0))
                            for result in results
                        ]
                        avg_score = sum(overall_scores) / len(overall_scores)

                        if avg_score >= 80:
                            final_recommendation = "Strongly Recommended"
                        elif avg_score >= 65:
                            final_recommendation = "Recommended"
                        elif avg_score >= 50:
                            final_recommendation = "Needs Review"
                        else:
                            final_recommendation = "Not Recommended"

                        metric1, metric2, metric3 = st.columns(3)

                        with metric1:
                            st.metric(
                                "Questions Completed",
                                len(results),
                            )

                        with metric2:
                            st.metric(
                                "Average Interview Score",
                                f"{avg_score:.1f}%",
                            )

                        with metric3:
                            st.metric(
                                "Final Recommendation",
                                final_recommendation,
                            )

                        st.success(
                            f"✅ Live adaptive interview completed. "
                            f"{len(results)} answers evaluated and saved to MySQL."
                        )

                        result_rows = []

                        for index, result in enumerate(results, start=1):
                            result_rows.append(
                                {
                                    "Question": index,
                                    "Technical (%)": result.get(
                                        "technical_score",
                                        0,
                                    ),
                                    "Communication (%)": result.get(
                                        "communication_score",
                                        0,
                                    ),
                                    "Relevance (%)": result.get(
                                        "relevance_score",
                                        0,
                                    ),
                                    "Overall (%)": result.get(
                                        "overall_score",
                                        0,
                                    ),
                                    "Recommendation": result.get(
                                        "recommendation",
                                        "Review",
                                    ),
                                }
                            )

                        results_df = pd.DataFrame(result_rows)

                        st.dataframe(
                            results_df,
                            use_container_width=True,
                            hide_index=True,
                        )

                        st.subheader("📝 Question-by-Question Feedback")

                        for index, entry in enumerate(
                            st.session_state.adaptive_history,
                            start=1,
                        ):
                            evaluation = entry.get("evaluation", {})

                            with st.expander(
                                f"Question {index} • "
                                f"Score: {evaluation.get('overall_score', 0)}%"
                            ):
                                st.write(
                                    "**Question:** "
                                    + entry.get("question", "")
                                )
                                st.write(
                                    "**Candidate Answer:** "
                                    + entry.get("answer", "")
                                )
                                st.write(
                                    "**AI Evaluation:** "
                                    + evaluation.get(
                                        "feedback",
                                        "No feedback available.",
                                    )
                                )

                                matched_topics = evaluation.get(
                                    "matched_topics",
                                    [],
                                )

                                if matched_topics:
                                    st.write(
                                        "**Matched Topics:** "
                                        + ", ".join(matched_topics)
                                    )

                if (
                    not st.session_state.get("adaptive_interview_active")
                    and not st.session_state.get("adaptive_interview_finished")
                ):
                    st.info(
                        "💡 Click **Start / Restart Interview**. "
                        "Only the first question is generated initially. "
                        "After each answer, the system evaluates it and generates "
                        "the next question dynamically."
                    )

        except Exception as interview_error:
            st.error("❌ Adaptive Interview Copilot encountered an error.")
            st.exception(interview_error)



def show_recruitment_chatbot():
    """Render the shared Recruitment Assistant for both portals."""
    profile = st.session_state.get("candidate_profile") or {}
    job = st.session_state.get("selected_job_data") or {}
    role = get_current_role()
    context = build_context(profile, job, role)

    st.markdown('<div id="assistant"></div>', unsafe_allow_html=True)
    chat_head_col, chat_action_col = st.columns([5, 1])
    with chat_head_col:
        st.markdown(
            '<div class="chat-card"><h2>💬 Recruitment Assistant</h2>'
            '<p>Ask questions about resumes, matching, applications, interviews, voice screening or recruiter workflow.</p></div>',
            unsafe_allow_html=True,
        )
    with chat_action_col:
        if st.button("Clear", key="clear_recruitment_chat", use_container_width=True):
            st.session_state.chatbot_messages = [
                {
                    "role": "assistant",
                    "content": "Chat cleared. 👋 What would you like to know?",
                }
            ]
            st.rerun()

    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = [
            {
                "role": "assistant",
                "content": "Hi! 👋 I’m your Recruitment Assistant. How can I help you today?",
            }
        ]

    for message in st.session_state.chatbot_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask the Recruitment Assistant…", key="recruitment_chat_input")
    if prompt:
        st.session_state.chatbot_messages.append({"role": "user", "content": prompt})
        response = get_response(prompt, context)
        st.session_state.chatbot_messages.append({"role": "assistant", "content": response})
        st.rerun()

show_recruitment_chatbot()

# ============================================================
# FOOTER
# ============================================================

st.markdown(
    '<div class="footer">'
    'AI Recruitment Copilot • AI-powered recruitment workflow • ' 
    'Candidate Portal • Recruiter Portal'
    '</div>',
    unsafe_allow_html=True,
)
