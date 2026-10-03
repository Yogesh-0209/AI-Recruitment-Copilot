"""Context-aware recruitment assistant for the AI Recruitment Copilot."""

import re


def _listify(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [x.strip() for x in re.split(r"[,|;]", text) if x.strip()]


def build_context(profile=None, job=None, role="candidate"):
    profile = profile or {}
    job = job or {}
    return {
        "role": role,
        "candidate_name": profile.get("name") or "Candidate",
        "skills": _listify(profile.get("skills")),
        "experience": profile.get("experience_years") or profile.get("experience") or 0,
        "job_title": job.get("title") or "the selected role",
        "required_skills": _listify(job.get("required_skills")),
    }


def get_response(message, context):
    """Return a useful local response without requiring an API key."""
    text = (message or "").strip().lower()
    role = context.get("role", "candidate")
    skills = context.get("skills", [])
    required = context.get("required_skills", [])
    job_title = context.get("job_title", "the selected role")
    candidate_name = context.get("candidate_name", "Candidate")

    if not text:
        return "Ask me about your resume, job match, applications, interviews, voice screening, or the recruitment workflow."

    if any(word in text for word in ["hello", "hi", "hey", "namaste"]):
        return f"Hello {candidate_name}! 👋 I’m your Recruitment Assistant. I can help with resumes, job matching, applications, interviews, and the hiring workflow."

    if "what can you do" in text or "help" in text:
        if role == "recruiter":
            return "I can help you understand candidate profiles, applications, matching scores, interview/voice results, ranking, and recruitment reports."
        return "I can help you understand your resume profile, selected job, matching score, application status, voice screening, and AI interview."

    if "skill" in text and ("missing" in text or "gap" in text):
        if skills and required:
            have = {s.lower() for s in skills}
            missing = [s for s in required if s.lower() not in have]
            if missing:
                return "For the selected role, the main skills not found in the parsed profile are: " + ", ".join(missing) + "."
            return "Good news — the required skills listed for the selected role are all present in the parsed profile."
        return "Upload a resume and select a job first, then I can explain the skill gap."

    if "match" in text or "fit" in text or "score" in text:
        if job_title != "the selected role":
            return f"Your current selected role is **{job_title}**. The Job Matching section shows the detailed skill, experience, education, and overall compatibility scores."
        return "Select a job after uploading your resume and I can explain the matching results."

    if "application" in text or "apply" in text:
        return "Go to **Job Applications** after selecting a job. You can submit one application per job and track its status from the same section."

    if "interview" in text:
        return "The AI Interview asks questions based on the selected job and your previous answers. Each response is evaluated and the next question can adapt to your performance."

    if "voice" in text or "audio" in text:
        return "Voice Screening lets you record a short response, transcribe it, and receive clarity, confidence, relevance, and overall screening scores."

    if role == "recruiter" and any(word in text for word in ["candidate", "applicant", "ranking"]):
        return "Use Candidates for profiles, Applications for submitted applications, AI Ranking & Decisions for combined scoring and decisions, and Final Reports for analytics."

    if "resume" in text or "profile" in text:
        if skills:
            return f"I can see a parsed profile for {candidate_name} with skills including {', '.join(skills[:8])}. Review the Resume & Profile section for the full extracted information."
        return "Upload a PDF or DOCX resume to create your candidate profile."

    return "I can help with resume parsing, job matching, skill gaps, applications, interviews, voice screening, ranking, and reports. Try asking: 'What skills am I missing?' or 'How does the matching work?'"
