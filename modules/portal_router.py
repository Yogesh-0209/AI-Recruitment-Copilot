import streamlit as st


def get_current_role():
    """Return the authenticated user's normalized role."""
    user = st.session_state.get("current_user") or {}
    return str(user.get("role", "candidate")).strip().lower()


def is_candidate():
    return get_current_role() == "candidate"


def is_recruiter():
    return get_current_role() == "recruiter"


def show_portal_header():
    """Display a small role-aware header."""
    user = st.session_state.get("current_user") or {}
    role = get_current_role()

    if role == "recruiter":
        st.title("🧑‍💼 Recruiter Portal")
        st.caption(
            f"Welcome, {user.get('name', 'Recruiter')}. "
            "Manage jobs, candidates, applications, and recruitment decisions."
        )
    else:
        st.title("👤 Candidate Portal")
        st.caption(
            f"Welcome, {user.get('name', 'Candidate')}. "
            "Manage your resume, job matches, applications, and AI interview."
        )
