# ============================================================
# SKILL GAP ANALYSIS
# ============================================================


def generate_skill_gap_report(
    candidate,
    job,
    match_result,
):
    """
    Generate a skill-gap report for a candidate
    applying to a particular job.
    """

    missing_skills = match_result.get(
        "missing_skills",
        [],
    )

    matched_skills = match_result.get(
        "matched_skills",
        [],
    )

    recommendations = []

    for skill in missing_skills:

        recommendations.append(
            f"Consider training or gaining practical "
            f"experience in {skill}."
        )

    report = {
        "candidate": candidate.get(
            "name",
            "Unknown Candidate",
        ),
        "job_title": job.get(
            "title",
            "Unknown Job",
        ),
        "hiring_score": match_result.get(
            "hiring_score",
            0,
        ),
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "recommendations": recommendations,
    }

    return report