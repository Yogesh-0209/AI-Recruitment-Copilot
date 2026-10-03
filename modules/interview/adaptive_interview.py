import json
import os
import re
from typing import Dict, List, Optional

from huggingface_hub import InferenceClient
from sqlalchemy.orm import Session

from database.models import Candidate, Job, InterviewQuestion


def _parse_list(value) -> List[str]:
    if not value:
        return []

    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    text = str(value).strip()

    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass

    return [
        part.strip()
        for part in re.split(r"[,;|]", text)
        if part.strip()
    ]


def _candidate_context(candidate: Optional[Candidate]) -> Dict:
    if not candidate:
        return {
            "name": "Candidate",
            "skills": [],
            "experience": 0,
            "education": "",
            "projects": "",
            "summary": "",
            "certifications": [],
        }

    return {
        "name": candidate.name or "Candidate",
        "skills": _parse_list(candidate.skills),
        "experience": float(candidate.experience_years or 0),
        "education": candidate.education or "",
        "projects": candidate.projects or "",
        "summary": candidate.summary or "",
        "certifications": _parse_list(candidate.certifications),
    }


def ai_configured() -> bool:
    return bool(
        os.getenv("HF_TOKEN", "").strip()
        and os.getenv("HF_MODEL", "").strip()
    )


def _extract_json(text: str):
    if not text:
        return None

    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except Exception:
            pass

    return None


def _call_ai(prompt: str) -> Optional[Dict]:
    if not ai_configured():
        return None

    try:
        client = InferenceClient(
            provider="auto",
            token=os.getenv("HF_TOKEN", "").strip(),
        )

        response = client.text_generation(
            prompt,
            model=os.getenv("HF_MODEL", "").strip(),
            max_new_tokens=700,
            temperature=0.7,
            return_full_text=False,
        )

        data = _extract_json(response)

        if isinstance(data, dict) and data.get("question"):
            return data

    except Exception:
        pass

    return None


def _fallback_first_question(job: Job, candidate: Optional[Candidate]) -> Dict:
    skills = _parse_list(job.required_skills)
    candidate_skills = _parse_list(candidate.skills) if candidate else []

    focus = skills[0] if skills else (
        candidate_skills[0] if candidate_skills else "the main technical requirements"
    )

    return {
        "question": (
            f"For the {job.title} role, explain how you would use {focus} "
            "in a real-world project. Describe your approach, important "
            "technical decisions, and how you would validate the result."
        ),
        "category": "Technical",
        "difficulty": "Intermediate",
        "expected_topics": [focus],
        "source": "Fallback",
    }


def _fallback_next_question(
    job: Job,
    previous_question: str,
    previous_answer: str,
    evaluation: Dict,
    question_number: int,
) -> Dict:
    matched = evaluation.get("matched_topics", [])
    topic = matched[0] if matched else "the role requirements"

    score = float(evaluation.get("overall_score", 0))

    if score >= 80:
        question = (
            f"You demonstrated a good understanding of {topic}. "
            f"For question {question_number}, take your answer one step further: "
            f"how would you handle a difficult production or scalability challenge "
            f"involving {topic}? Explain your reasoning and trade-offs."
        )
        difficulty = "Advanced"
    else:
        question = (
            f"Let's explore {topic} further. For question {question_number}, "
            f"walk through a practical example step by step and explain how "
            "you would verify that your solution is correct."
        )
        difficulty = "Intermediate"

    return {
        "question": question,
        "category": "Adaptive Technical",
        "difficulty": difficulty,
        "expected_topics": [topic, "problem solving"],
        "source": "Fallback",
    }


def generate_first_question(
    db: Session,
    job_id: int,
    candidate_id: int,
) -> Dict:
    job = db.query(Job).filter(Job.id == job_id).first()
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not job:
        raise ValueError(f"Job with ID {job_id} was not found.")

    context = _candidate_context(candidate)
    skills = _parse_list(job.required_skills)

    prompt = f"""
You are an expert AI technical interviewer.

Generate the FIRST interview question for a live adaptive interview.

JOB:
Title: {job.title}
Description: {job.description or "Not provided"}
Required skills: {", ".join(skills) or "Not specified"}
Experience required: {job.experience_required or 0} years

CANDIDATE:
Skills: {", ".join(context["skills"]) or "Not provided"}
Experience: {context["experience"]} years
Education: {context["education"] or "Not provided"}
Projects: {context["projects"] or "Not provided"}
Summary: {context["summary"] or "Not provided"}
Certifications: {", ".join(context["certifications"]) or "Not provided"}

RULES:
- Make the question specific to this job.
- Personalize it using the candidate profile when useful.
- Do not invent candidate experience.
- Test practical understanding rather than memorization.
- The answer should allow a follow-up question.
- Return ONLY JSON.

Format:
{{
  "question": "string",
  "category": "Technical",
  "difficulty": "Intermediate",
  "expected_topics": ["topic1", "topic2"]
}}
""".strip()

    result = _call_ai(prompt)

    if result:
        return {
            "question": str(result["question"]).strip(),
            "category": str(result.get("category", "Technical")).strip(),
            "difficulty": str(result.get("difficulty", "Intermediate")).strip(),
            "expected_topics": _parse_list(result.get("expected_topics", [])),
            "source": "Hugging Face AI",
        }

    return _fallback_first_question(job, candidate)


def generate_next_question(
    db: Session,
    job_id: int,
    candidate_id: int,
    previous_question: str,
    previous_answer: str,
    evaluation: Dict,
    question_number: int,
    interview_history: Optional[List[Dict]] = None,
) -> Dict:
    job = db.query(Job).filter(Job.id == job_id).first()
    candidate = (
        db.query(Candidate)
        .filter(Candidate.id == candidate_id)
        .first()
    )

    if not job:
        raise ValueError(f"Job with ID {job_id} was not found.")

    context = _candidate_context(candidate)
    history = interview_history or []

    compact_history = []
    for item in history[-4:]:
        compact_history.append({
            "question": item.get("question", ""),
            "answer": item.get("answer", "")[:1200],
            "score": item.get("evaluation", {}).get("overall_score", 0),
        })

    prompt = f"""
You are an expert AI interviewer conducting a LIVE adaptive interview.

Generate the NEXT interview question based on the candidate's previous
answer and evaluation.

JOB:
Title: {job.title}
Description: {job.description or "Not provided"}
Required skills: {", ".join(_parse_list(job.required_skills)) or "Not specified"}

CANDIDATE:
Skills: {", ".join(context["skills"]) or "Not provided"}
Experience: {context["experience"]} years
Projects: {context["projects"] or "Not provided"}

PREVIOUS QUESTION:
{previous_question}

PREVIOUS ANSWER:
{previous_answer}

PREVIOUS EVALUATION:
{json.dumps(evaluation)}

RECENT INTERVIEW HISTORY:
{json.dumps(compact_history)}

THIS IS QUESTION NUMBER:
{question_number}

ADAPTIVE RULES:
- If the previous answer was strong, increase difficulty or ask a deeper
  practical/scenario-based follow-up.
- If the previous answer was weak, ask a clearer question that probes the
  same concept or an important prerequisite.
- Do not repeat a previous question.
- Cover another important job skill when appropriate.
- Personalize the question using the candidate profile when useful.
- Never invent candidate experience.
- Keep the question concise enough for a live interview.
- Return ONLY JSON.

Format:
{{
  "question": "string",
  "category": "Technical",
  "difficulty": "Intermediate",
  "expected_topics": ["topic1", "topic2"]
}}
""".strip()

    result = _call_ai(prompt)

    if result:
        return {
            "question": str(result["question"]).strip(),
            "category": str(result.get("category", "Adaptive Technical")).strip(),
            "difficulty": str(result.get("difficulty", "Intermediate")).strip(),
            "expected_topics": _parse_list(result.get("expected_topics", [])),
            "source": "Hugging Face AI",
        }

    return _fallback_next_question(
        job=job,
        previous_question=previous_question,
        previous_answer=previous_answer,
        evaluation=evaluation,
        question_number=question_number,
    )


def save_question(
    db: Session,
    job_id: int,
    candidate_id: int,
    question_data: Dict,
) -> int:
    record = InterviewQuestion(
        job_id=job_id,
        candidate_id=candidate_id,
        question=question_data["question"],
        category=question_data.get("category", "Technical"),
        difficulty=question_data.get("difficulty", "Intermediate"),
        expected_topics=json.dumps(
            question_data.get("expected_topics", [])
        ),
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return record.id
