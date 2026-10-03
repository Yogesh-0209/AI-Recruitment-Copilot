import re
from typing import Dict, List, Optional

from database.models import InterviewResult


# ---------------------------------------------------------
# Text utilities
# ---------------------------------------------------------

def _normalise_text(text: str) -> str:
    if not text:
        return ""

    return re.sub(
        r"[^a-zA-Z0-9+#.\s]",
        " ",
        text.lower()
    )


def _keyword_matches(
    answer: str,
    topics: List[str]
) -> List[str]:

    answer_text = _normalise_text(answer)

    matched = []

    for topic in topics:
        topic_text = _normalise_text(
            str(topic)
        ).strip()

        if topic_text and topic_text in answer_text:
            matched.append(topic)

    return matched


# ---------------------------------------------------------
# Communication score
# ---------------------------------------------------------

def _communication_score(answer: str) -> float:

    if not answer or not answer.strip():
        return 0.0

    words = answer.strip().split()
    word_count = len(words)

    if word_count < 5:
        return 25.0

    score = 50.0

    if word_count >= 30:
        score += 15

    if word_count >= 60:
        score += 10

    structure_words = [
        "because",
        "therefore",
        "first",
        "second",
        "finally",
        "for example",
        "however",
        "approach",
        "result",
    ]

    text = answer.lower()

    structure_count = sum(
        1
        for word in structure_words
        if word in text
    )

    score += min(
        structure_count * 5,
        20
    )

    return min(score, 100.0)


# ---------------------------------------------------------
# Technical score
# ---------------------------------------------------------

def _technical_score(
    answer: str,
    expected_topics: List[str]
) -> float:

    if not answer or not answer.strip():
        return 0.0

    if not expected_topics:

        word_count = len(answer.split())

        if word_count >= 80:
            return 80.0

        if word_count >= 40:
            return 65.0

        if word_count >= 15:
            return 50.0

        return 30.0

    matched = _keyword_matches(
        answer,
        expected_topics
    )

    coverage = (
        len(matched) /
        len(expected_topics)
    )

    score = coverage * 80.0

    word_count = len(answer.split())

    if word_count >= 40:
        score += 10

    if word_count >= 80:
        score += 10

    return min(score, 100.0)


# ---------------------------------------------------------
# Relevance score
# ---------------------------------------------------------

def _relevance_score(
    answer: str,
    expected_topics: List[str]
) -> float:

    if not answer or not answer.strip():
        return 0.0

    if not expected_topics:
        return 60.0

    matched = _keyword_matches(
        answer,
        expected_topics
    )

    if not matched:
        return 30.0

    coverage = (
        len(matched) /
        len(expected_topics)
    )

    return min(
        40.0 + coverage * 60.0,
        100.0
    )


# ---------------------------------------------------------
# Feedback
# ---------------------------------------------------------

def _generate_feedback(
    technical_score: float,
    communication_score: float,
    relevance_score: float,
    matched_topics: List[str],
    expected_topics: List[str],
) -> str:

    feedback = []

    if technical_score >= 75:
        feedback.append(
            "The answer demonstrates good technical understanding."
        )
    elif technical_score >= 50:
        feedback.append(
            "The answer demonstrates a moderate level of technical understanding."
        )
    else:
        feedback.append(
            "The answer needs stronger technical detail."
        )

    if communication_score >= 75:
        feedback.append(
            "The response is clear and well explained."
        )
    elif communication_score >= 50:
        feedback.append(
            "The response is understandable but could be structured more clearly."
        )
    else:
        feedback.append(
            "The response is too brief and needs clearer explanation."
        )

    if relevance_score >= 75:
        feedback.append(
            "The answer is strongly relevant to the question."
        )
    elif relevance_score >= 50:
        feedback.append(
            "The answer is partially relevant to the expected topics."
        )
    else:
        feedback.append(
            "The answer does not sufficiently address the expected topics."
        )

    if matched_topics:
        feedback.append(
            "Topics identified: "
            + ", ".join(matched_topics)
            + "."
        )

    missing_topics = [
        topic
        for topic in expected_topics
        if topic not in matched_topics
    ]

    if missing_topics:
        feedback.append(
            "Consider discussing: "
            + ", ".join(missing_topics)
            + "."
        )

    return " ".join(feedback)


# ---------------------------------------------------------
# Recommendation
# ---------------------------------------------------------

def _recommendation(
    overall_score: float
) -> str:

    if overall_score >= 80:
        return "Strongly Recommended"

    if overall_score >= 65:
        return "Recommended"

    if overall_score >= 50:
        return "Needs Further Review"

    return "Not Recommended"


# ---------------------------------------------------------
# Evaluate answer
# ---------------------------------------------------------

def evaluate_answer(
    answer: str,
    expected_topics: Optional[List[str]] = None,
) -> Dict:

    if expected_topics is None:
        expected_topics = []

    technical = _technical_score(
        answer,
        expected_topics
    )

    communication = _communication_score(
        answer
    )

    relevance = _relevance_score(
        answer,
        expected_topics
    )

    overall = (
        technical * 0.50
        + communication * 0.20
        + relevance * 0.30
    )

    overall = round(
        overall,
        2
    )

    matched_topics = _keyword_matches(
        answer,
        expected_topics
    )

    feedback = _generate_feedback(
        technical,
        communication,
        relevance,
        matched_topics,
        expected_topics,
    )

    recommendation = _recommendation(
        overall
    )

    return {
        "technical_score": round(
            technical,
            2
        ),
        "communication_score": round(
            communication,
            2
        ),
        "relevance_score": round(
            relevance,
            2
        ),
        "overall_score": overall,
        "feedback": feedback,
        "recommendation": recommendation,
        "matched_topics": matched_topics,
    }


# ---------------------------------------------------------
# Save evaluation to MySQL
# ---------------------------------------------------------

def save_evaluation(
    db,
    candidate_id: int,
    job_id: int,
    answer: str,
    evaluation: Dict,
    question_id: Optional[int] = None,
) -> InterviewResult:

    result = InterviewResult(
        candidate_id=candidate_id,
        job_id=job_id,
        question_id=question_id,
        answer=answer,
        technical_score=evaluation["technical_score"],
        communication_score=evaluation["communication_score"],
        relevance_score=evaluation["relevance_score"],
        overall_score=evaluation["overall_score"],
        feedback=evaluation["feedback"],
        recommendation=evaluation["recommendation"],
    )

    db.add(result)
    db.commit()
    db.refresh(result)

    return result


# ---------------------------------------------------------
# Evaluate AND save
# ---------------------------------------------------------

def evaluate_and_save(
    db,
    candidate_id: int,
    job_id: int,
    answer: str,
    expected_topics: Optional[List[str]] = None,
    question_id: Optional[int] = None,
) -> Dict:

    evaluation = evaluate_answer(
        answer=answer,
        expected_topics=expected_topics,
    )

    result = save_evaluation(
        db=db,
        candidate_id=candidate_id,
        job_id=job_id,
        answer=answer,
        evaluation=evaluation,
        question_id=question_id,
    )

    evaluation["result_id"] = result.id

    return evaluation


# ---------------------------------------------------------
# Test
# ---------------------------------------------------------

if __name__ == "__main__":

    sample_answer = """
    Python is a high-level programming language used for machine
    learning and web development. I would use functions, classes,
    exception handling and unit testing to create maintainable
    production code. For example, Python can be combined with
    Scikit-learn for machine learning and Pandas for data processing.
    """

    result = evaluate_answer(
        sample_answer,
        [
            "Python",
            "machine learning",
            "Scikit-learn",
        ],
    )

    print("Interview Evaluation")
    print("--------------------")

    for key, value in result.items():
        print(f"{key}: {value}")