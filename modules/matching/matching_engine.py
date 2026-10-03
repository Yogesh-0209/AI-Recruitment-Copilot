# ============================================================
# MATCHING ENGINE
# AI Recruitment Copilot - Milestone 2
# ============================================================

import re


# ============================================================
# TEXT NORMALIZATION
# ============================================================

def normalize_text(value):
    """Normalize text for reliable comparison."""
    if value is None:
        return ""

    text = str(value).lower().strip()
    text = text.replace("&", " and ")
    text = re.sub(r"[^a-z0-9+#.\- ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


# ============================================================
# CONVERT VALUE TO LIST
# ============================================================

def ensure_list(value):
    """Safely convert common input types into a list."""
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

    return [value]


# ============================================================
# CANDIDATE EVIDENCE
# ============================================================

def build_candidate_evidence(candidate):
    """
    Build searchable evidence from the candidate profile.

    Matching is not limited to the Skills field. Experience,
    certifications and project descriptions are also considered.
    This helps recognize explicit skills mentioned elsewhere in
    a resume without inventing unrelated technologies.
    """

    parts = []

    for key in [
        "skills",
        "experience",
        "certifications",
        "projects",
    ]:
        parts.extend(
            str(item)
            for item in ensure_list(candidate.get(key, []))
        )

    return normalize_text(" ".join(parts))


# ============================================================
# SKILL ALIASES / EVIDENCE RULES
# ============================================================

SKILL_EVIDENCE = {
    "rest api": [
        "rest api",
        "rest apis",
    ],
    "machine learning": [
        "machine learning",
        "machine-learning",
        " ml ",
        "predictive analytics",
        "churn prediction",
        "forecasting model",
    ],
    "data analysis": [
        "data analysis",
        "data analytics",
        "exploratory data analysis",
        "analyzed business datasets",
        "analytics",
        "reporting",
    ],
    "power bi": [
        "power bi",
        "tableau",
    ],
}


def skill_is_present(required_skill, candidate_skills, evidence_text):
    """
    Determine whether a required skill is supported by the
    candidate's explicit skills or resume evidence.
    """

    required_normalized = normalize_text(required_skill)

    candidate_normalized = {
        normalize_text(skill)
        for skill in ensure_list(candidate_skills)
        if normalize_text(skill)
    }

    # Direct skill match.
    if required_normalized in candidate_normalized:
        return True

    # Evidence/alias match.
    evidence_phrases = SKILL_EVIDENCE.get(
        required_normalized,
        [],
    )

    padded_text = f" {evidence_text} "

    for phrase in evidence_phrases:
        phrase_normalized = normalize_text(phrase)

        if (
            phrase_normalized
            and f" {phrase_normalized} " in padded_text
        ):
            return True

    return False


# ============================================================
# SKILL MATCHING
# ============================================================

def calculate_skill_match(
    candidate_skills,
    required_skills,
    candidate_evidence="",
):
    """
    Calculate percentage of required skills supported by the
    candidate.

    Evidence can come from:
    - explicit Skills
    - Experience
    - Certifications
    - Projects
    """

    candidate_skills = ensure_list(candidate_skills)
    required_skills = ensure_list(required_skills)

    required_clean = [
        skill
        for skill in required_skills
        if normalize_text(skill)
    ]

    if not required_clean:
        return 0.0, [], []

    if not candidate_evidence:
        candidate_evidence = normalize_text(
            " ".join(
                str(skill)
                for skill in candidate_skills
            )
        )

    matched_skills = []
    missing_skills = []

    seen = set()

    for skill in required_clean:
        normalized_skill = normalize_text(skill)

        if normalized_skill in seen:
            continue

        seen.add(normalized_skill)

        if skill_is_present(
            skill,
            candidate_skills,
            candidate_evidence,
        ):
            matched_skills.append(skill)
        else:
            missing_skills.append(skill)

    score = (
        len(matched_skills)
        / len(required_clean)
    ) * 100

    return (
        round(score, 2),
        matched_skills,
        missing_skills,
    )


# ============================================================
# EXPERIENCE MATCHING
# ============================================================

def calculate_experience_match(
    candidate_experience,
    required_experience,
):
    """
    Calculate experience compatibility.

    Candidate experience may be:
    - integer
    - float
    - numeric string
    - None
    """

    try:
        candidate_experience = float(
            candidate_experience or 0
        )
    except (TypeError, ValueError):
        candidate_experience = 0.0

    try:
        required_experience = float(
            required_experience or 0
        )
    except (TypeError, ValueError):
        required_experience = 0.0

    if required_experience <= 0:
        return 100.0

    if candidate_experience >= required_experience:
        return 100.0

    score = (
        candidate_experience
        / required_experience
    ) * 100

    return round(
        min(score, 100.0),
        2,
    )


# ============================================================
# EDUCATION HELPERS
# ============================================================

def education_level(text):
    text = normalize_text(text)

    if (
        "m.s" in text
        or "ms " in f"{text} "
        or "master of science" in text
    ):
        return "ms"

    if (
        "m.tech" in text
        or "mtech" in text
        or "master of technology" in text
    ):
        return "mtech"

    if (
        "mca" in text
        or "master of computer applications" in text
    ):
        return "mca"

    if (
        "b.tech" in text
        or "btech" in text
        or "bachelor of technology" in text
    ):
        return "btech"

    if (
        "b.sc" in text
        or "bsc " in f"{text} "
        or "bachelor of science" in text
    ):
        return "bsc"

    if (
        "bca" in text
        or "bachelor of computer applications" in text
    ):
        return "bca"

    return ""


def has_computer_science_field(text):
    text = normalize_text(text)

    return (
        "computer science" in text
        or "computer applications" in text
        or "information technology" in text
        or "information systems" in text
    )


# ============================================================
# EDUCATION MATCHING
# ============================================================

def calculate_education_match(
    candidate_education,
    required_education,
):
    """
    Education compatibility:

    100 = same/sufficiently equivalent qualification
    75  = same Computer Science field, different degree level
    50  = same technical degree family / related computing degree
    0   = insufficient evidence
    """

    candidate_text = normalize_text(
        candidate_education
    )

    required_text = normalize_text(
        required_education
    )

    if not required_text:
        return 100.0

    if not candidate_text:
        return 0.0

    # Direct textual match.
    if required_text in candidate_text:
        return 100.0

    candidate_level = education_level(candidate_text)
    required_level = education_level(required_text)

    candidate_cs = has_computer_science_field(
        candidate_text
    )
    required_cs = has_computer_science_field(
        required_text
    )

    # Same technical field, different degree level.
    if candidate_cs and required_cs:
        if (
            candidate_level == required_level
            and candidate_level
        ):
            return 100.0

        return 75.0

    # Same degree family even if specialization differs.
    if (
        candidate_level
        and required_level
        and candidate_level == required_level
    ):
        return 50.0

    return 0.0


# ============================================================
# MAIN MATCHING FUNCTION
# ============================================================

def calculate_match(
    candidate,
    job,
):
    """
    Calculate overall candidate-job matching score.

    Weights:
        Skills      = 60%
        Experience  = 25%
        Education   = 15%

    Returns:
        hiring_score
        skill_score
        experience_score
        education_score
        matched_skills
        missing_skills
    """

    if not isinstance(candidate, dict):
        raise TypeError(
            "Candidate must be a dictionary."
        )

    if not isinstance(job, dict):
        raise TypeError(
            "Job must be a dictionary."
        )

    candidate_skills = candidate.get(
        "skills",
        [],
    )

    candidate_experience = candidate.get(
        "experience",
        0,
    )

    candidate_education = candidate.get(
        "education",
        "",
    )

    required_skills = job.get(
        "required_skills",
        [],
    )

    required_experience = job.get(
        "experience_required",
        0,
    )

    required_education = job.get(
        "education_required",
        "",
    )

    candidate_evidence = build_candidate_evidence(
        candidate
    )

    (
        skill_score,
        matched_skills,
        missing_skills,
    ) = calculate_skill_match(
        candidate_skills,
        required_skills,
        candidate_evidence,
    )

    experience_score = calculate_experience_match(
        candidate_experience,
        required_experience,
    )

    education_score = calculate_education_match(
        candidate_education,
        required_education,
    )

    skill_weight = 0.60
    experience_weight = 0.25
    education_weight = 0.15

    hiring_score = (
        skill_score * skill_weight
        + experience_score * experience_weight
        + education_score * education_weight
    )

    return {
        "hiring_score": round(
            hiring_score,
            2,
        ),
        "skill_score": round(
            skill_score,
            2,
        ),
        "experience_score": round(
            experience_score,
            2,
        ),
        "education_score": round(
            education_score,
            2,
        ),
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
    }