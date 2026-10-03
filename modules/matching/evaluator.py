# ============================================================
# MILESTONE 2 MATCHING EVALUATOR
# AI Recruitment Copilot
# ============================================================

import json
import os

from modules.matching.matching_engine import calculate_match


# ============================================================
# MATCH DECISION THRESHOLD
# ============================================================

# 75% is used as the evaluation decision threshold.
# This prevents borderline 70% scores from being classified
# as strong matches.
MATCH_THRESHOLD = 75.0


# ============================================================
# LOAD EVALUATION CASES
# ============================================================

def load_evaluation_cases():
    possible_paths = [
        "milestone2_evaluation.json",
        os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(__file__)
                )
            ),
            "milestone2_evaluation.json",
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

                return data.get(
                    "evaluation_cases",
                    [],
                )

            except Exception:
                return []

    return []


# ============================================================
# SINGLE CASE EVALUATION
# ============================================================

def evaluate_match(
    candidate,
    job,
    expected_match,
):
    result = calculate_match(
        candidate,
        job,
    )

    score = float(
        result.get(
            "hiring_score",
            0,
        )
    )

    predicted_match = (
        score >= MATCH_THRESHOLD
    )

    correct = (
        predicted_match
        == bool(expected_match)
    )

    return {
        "score": score,
        "predicted_match": predicted_match,
        "expected_match": bool(expected_match),
        "correct": correct,
        "matched_skills": result.get(
            "matched_skills",
            [],
        ),
        "missing_skills": result.get(
            "missing_skills",
            [],
        ),
    }


# ============================================================
# COMPLETE EVALUATION
# ============================================================

def calculate_evaluation_accuracy(
    candidates,
    jobs,
    evaluation_cases,
):
    results = []
    correct = 0

    candidate_map = {
        str(candidate.get("name", "")).strip().lower():
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
    }

    job_map = {
        str(job.get("job_id", "")).strip():
        job
        for job in jobs
        if isinstance(job, dict)
    }

    for case in evaluation_cases:
        candidate_name = str(
            case.get(
                "candidate",
                "",
            )
        ).strip()

        job_id = str(
            case.get(
                "job_id",
                "",
            )
        ).strip()

        expected_match = bool(
            case.get(
                "expected_match",
                False,
            )
        )

        candidate = candidate_map.get(
            candidate_name.lower()
        )

        job = job_map.get(
            job_id
        )

        if not candidate or not job:
            continue

        evaluation = evaluate_match(
            candidate,
            job,
            expected_match,
        )

        results.append(
            {
                "candidate": candidate_name,
                "job_id": job_id,
                "job_title": job.get(
                    "title",
                    "Unknown",
                ),
                "hiring_score": evaluation[
                    "score"
                ],
                "predicted_match": evaluation[
                    "predicted_match"
                ],
                "expected_match": evaluation[
                    "expected_match"
                ],
                "correct": evaluation[
                    "correct"
                ],
            }
        )

        if evaluation["correct"]:
            correct += 1

    total = len(results)

    accuracy = (
        0.0
        if total == 0
        else (correct / total) * 100
    )

    return (
        round(accuracy, 2),
        correct,
        total,
        results,
    )
