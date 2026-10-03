import json
import os
import re
from typing import List, Dict, Optional

from sqlalchemy.orm import Session
from database.models import Job, Candidate, InterviewQuestion


# ============================================================
# Milestone 3 — AI Interview Question Generator
# ============================================================
# The generator has two modes:
#
# 1. REAL AI MODE
#    Uses Hugging Face Inference API when HF_TOKEN and HF_MODEL
#    are configured in the project's .env file.
#
# 2. SAFE FALLBACK MODE
#    Uses deterministic, job-specific questions if the AI service
#    is unavailable. This keeps the application working during a demo.
# ============================================================


def _parse_list(value) -> List[str]:
    """Convert JSON/list/comma-separated text into a clean list."""
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

    parts = re.split(r"[,;|]", text)
    return [part.strip() for part in parts if part.strip()]


def _parse_skills(value) -> List[str]:
    return _parse_list(value)


def _candidate_context(candidate: Optional[Candidate]) -> Dict:
    """Build safe candidate context for personalization."""
    if candidate is None:
        return {
            "name": "Candidate",
            "skills": [],
            "experience_years": 0,
            "education": "",
            "projects": "",
            "summary": "",
            "certifications": [],
        }

    return {
        "name": candidate.name or "Candidate",
        "skills": _parse_list(candidate.skills),
        "experience_years": float(candidate.experience_years or 0),
        "education": candidate.education or "",
        "projects": candidate.projects or "",
        "summary": candidate.summary or "",
        "certifications": _parse_list(candidate.certifications),
    }


def _difficulty_for_skill(skill: str) -> str:
    advanced_keywords = {
        "tensorflow",
        "pytorch",
        "kubernetes",
        "aws",
        "deep learning",
        "machine learning",
        "nlp",
        "docker",
        "microservices",
        "cloud",
    }

    return "Advanced" if skill.lower() in advanced_keywords else "Intermediate"


def _technical_question(skill: str, job_title: str) -> Dict:
    skill_lower = skill.lower()

    special_questions = {
        "python": (
            "Explain how you would design clean, maintainable Python code "
            "for a production application. Discuss error handling, testing, "
            "and performance considerations."
        ),
        "sql": (
            "Suppose you need to retrieve and analyze data from several "
            "related database tables. How would you design the SQL queries, "
            "and how would you optimize them for performance?"
        ),
        "machine learning": (
            "Describe the complete machine learning workflow you would follow "
            "for a real-world problem, from data preparation to model "
            "evaluation and deployment."
        ),
        "deep learning": (
            "Explain how you would choose and train a deep learning model "
            "for a real-world problem. What techniques would you use to "
            "avoid overfitting?"
        ),
        "tensorflow": (
            "How would you build, train, evaluate, and deploy a machine "
            "learning model using TensorFlow?"
        ),
        "pytorch": (
            "Explain how you would implement and train a neural network "
            "using PyTorch. What steps would you follow to evaluate it?"
        ),
        "nlp": (
            "Describe an NLP pipeline for processing unstructured text. "
            "Which preprocessing, representation, and modeling techniques "
            "would you consider?"
        ),
        "pandas": (
            "How would you use Pandas to clean, transform, and analyze a "
            "large dataset? Give examples of operations you commonly use."
        ),
        "numpy": (
            "Explain how NumPy arrays differ from standard Python lists and "
            "why NumPy is useful for numerical and machine learning workloads."
        ),
        "django": (
            "How would you structure a Django application for scalability "
            "and maintainability? Explain models, views, URLs, and APIs."
        ),
        "rest api": (
            "Explain how you would design a REST API for a production "
            "application. Discuss HTTP methods, status codes, validation, "
            "authentication, and error handling."
        ),
        "git": (
            "Describe your Git workflow when working with a team. How do "
            "you manage branches, commits, pull requests, and conflicts?"
        ),
        "power bi": (
            "How would you create a useful Power BI dashboard from raw "
            "business data? Explain data preparation, visualizations, and "
            "selection of important KPIs."
        ),
        "scikit-learn": (
            "How would you use Scikit-learn to train and evaluate a machine "
            "learning model? Explain preprocessing, model selection, "
            "validation, and evaluation metrics."
        ),
    }

    question = special_questions.get(
        skill_lower,
        (
            f"For the role of {job_title}, explain your practical experience "
            f"with {skill}. Describe how you would use {skill} to solve a "
            "real-world problem and discuss important challenges."
        ),
    )

    return {
        "question": question,
        "category": "Technical",
        "difficulty": _difficulty_for_skill(skill),
        "expected_topics": [skill],
        "source": "Fallback Template",
    }


def _scenario_question(skill: str, job_title: str) -> Dict:
    return {
        "question": (
            f"You are working as a {job_title} and encounter a production "
            f"problem involving {skill}. Explain how you would investigate "
            "the issue, identify the root cause, implement a solution, "
            "and verify that the solution works."
        ),
        "category": "Situational",
        "difficulty": "Advanced",
        "expected_topics": [
            skill,
            "problem solving",
            "debugging",
            "production practices",
        ],
        "source": "Fallback Template",
    }


def _behavioral_question(job_title: str) -> Dict:
    return {
        "question": (
            f"Tell us about a challenging project you worked on that is "
            f"relevant to the {job_title} role. What was your responsibility, "
            "what problems did you face, and what was the final outcome?"
        ),
        "category": "Behavioral",
        "difficulty": "Intermediate",
        "expected_topics": [
            "communication",
            "problem solving",
            "teamwork",
            "project experience",
        ],
        "source": "Fallback Template",
    }


def _role_fit_question(job_title: str) -> Dict:
    return {
        "question": (
            f"Why are you a good fit for the {job_title} position? Explain "
            "how your technical skills, experience, and projects match the "
            "requirements of this role."
        ),
        "category": "Role Fit",
        "difficulty": "Intermediate",
        "expected_topics": [
            "technical skills",
            "experience",
            "projects",
            "role fit",
        ],
        "source": "Fallback Template",
    }


def _build_fallback_questions(
    job: Job,
    candidate: Optional[Candidate],
    number_of_questions: int,
) -> List[Dict]:
    """Build the existing reliable non-LLM question set."""
    skills = _parse_skills(job.required_skills)

    questions = []

    for skill in skills:
        questions.append(_technical_question(skill, job.title or "this position"))

    for skill in skills:
        questions.append(_scenario_question(skill, job.title or "this position"))

    questions.append(_behavioral_question(job.title or "this position"))
    questions.append(_role_fit_question(job.title or "this position"))

    return questions[:max(1, number_of_questions)]


def _extract_json_from_text(text: str):
    """Extract a JSON object/array from an LLM response."""
    if not text:
        return None

    cleaned = text.strip()

    # Remove markdown code fences.
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    # Direct JSON first.
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Find the first JSON array.
    start = cleaned.find("[")
    end = cleaned.rfind("]")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except Exception:
            pass

    # Find the first JSON object.
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except Exception:
            pass

    return None


def _normalize_ai_questions(data, number_of_questions: int) -> List[Dict]:
    """Validate and normalize model output."""
    if isinstance(data, dict):
        data = data.get("questions", [])

    if not isinstance(data, list):
        return []

    normalized = []

    for item in data:
        if not isinstance(item, dict):
            continue

        question = str(item.get("question", "")).strip()
        if not question:
            continue

        category = str(
            item.get("category", "Technical")
        ).strip()

        difficulty = str(
            item.get("difficulty", "Intermediate")
        ).strip()

        topics = item.get("expected_topics", [])
        if not isinstance(topics, list):
            topics = _parse_list(topics)

        normalized.append(
            {
                "question": question,
                "category": category,
                "difficulty": difficulty,
                "expected_topics": [
                    str(topic).strip()
                    for topic in topics
                    if str(topic).strip()
                ],
                "source": "Hugging Face AI",
            }
        )

        if len(normalized) >= number_of_questions:
            break

    return normalized


def _generate_with_huggingface(
    job: Job,
    candidate: Optional[Candidate],
    number_of_questions: int,
) -> List[Dict]:
    """
    Generate personalized interview questions with Hugging Face.

    Required .env values:
        HF_TOKEN=your_huggingface_token
        HF_MODEL=your_text_generation_model
    """
    token = os.getenv("HF_TOKEN", "").strip()
    model = os.getenv("HF_MODEL", "").strip()

    if not token or not model:
        return []

    try:
        from huggingface_hub import InferenceClient
    except Exception:
        return []

    candidate_data = _candidate_context(candidate)
    required_skills = _parse_skills(job.required_skills)

    prompt = f"""
You are an expert technical recruiter conducting a structured interview.

Create exactly {number_of_questions} interview questions for this job.

JOB TITLE:
{job.title}

JOB DESCRIPTION:
{job.description or "Not provided"}

REQUIRED SKILLS:
{", ".join(required_skills) or "Not specified"}

EXPERIENCE REQUIRED:
{job.experience_required or 0} years

EDUCATION REQUIRED:
{job.education_required or "Not specified"}

CANDIDATE SKILLS:
{", ".join(candidate_data["skills"]) or "Not provided"}

CANDIDATE EXPERIENCE:
{candidate_data["experience_years"]} years

CANDIDATE PROJECTS:
{candidate_data["projects"] or "Not provided"}

CANDIDATE SUMMARY:
{candidate_data["summary"] or "Not provided"}

CANDIDATE CERTIFICATIONS:
{", ".join(candidate_data["certifications"]) or "Not provided"}

INTERVIEW REQUIREMENTS:
- Personalize questions using the candidate profile where useful.
- Focus strongly on the job requirements.
- Include a balanced mixture of Technical, Situational, Behavioral, and Role Fit questions.
- Avoid duplicate questions.
- Questions must be answerable by a candidate in an interview.
- Questions should test practical understanding, not only definitions.
- Use Intermediate and Advanced difficulty.
- Do not invent candidate experience. If a project or skill is not provided, ask a general role-relevant question instead.

Return ONLY valid JSON in this exact format:
[
  {{
    "question": "string",
    "category": "Technical",
    "difficulty": "Intermediate",
    "expected_topics": ["topic1", "topic2"]
  }}
]
""".strip()

    try:
        client = InferenceClient(
            provider="auto",
            token=token,
        )

        response = client.text_generation(
            prompt,
            model=model,
            max_new_tokens=1800,
            temperature=0.7,
            return_full_text=False,
        )

        data = _extract_json_from_text(response)
        return _normalize_ai_questions(data, number_of_questions)

    except Exception:
        # Never break the interview because an external AI service failed.
        return []


def generate_questions(
    db: Session,
    job_id: int,
    candidate_id: Optional[int] = None,
    number_of_questions: int = 10,
    save_to_database: bool = True,
) -> List[Dict]:
    """
    Main Milestone 3 question-generation function.

    The function first attempts real AI generation. If AI is not
    configured or fails, it automatically uses the existing fallback.
    """
    job = db.query(Job).filter(Job.id == job_id).first()

    if not job:
        raise ValueError(f"Job with ID {job_id} was not found.")

    candidate = None

    if candidate_id is not None:
        candidate = (
            db.query(Candidate)
            .filter(Candidate.id == candidate_id)
            .first()
        )

    number_of_questions = max(1, min(int(number_of_questions), 15))

    # ------------------------------------------------------------
    # 1. Try real AI generation.
    # ------------------------------------------------------------
    questions = _generate_with_huggingface(
        job=job,
        candidate=candidate,
        number_of_questions=number_of_questions,
    )

    generation_mode = "AI"

    # ------------------------------------------------------------
    # 2. Safe fallback.
    # ------------------------------------------------------------
    if len(questions) < number_of_questions:
        questions = _build_fallback_questions(
            job=job,
            candidate=candidate,
            number_of_questions=number_of_questions,
        )
        generation_mode = "Fallback"

    questions = questions[:number_of_questions]

    # ------------------------------------------------------------
    # 3. Save questions to MySQL.
    # ------------------------------------------------------------
    if save_to_database:
        for item in questions:
            question_record = InterviewQuestion(
                job_id=job.id,
                candidate_id=candidate_id,
                question=item["question"],
                category=item["category"],
                difficulty=item["difficulty"],
                expected_topics=json.dumps(
                    item.get("expected_topics", [])
                ),
            )

            db.add(question_record)

        db.commit()

    # Add a generation mode for the UI/demo.
    for item in questions:
        item["generation_mode"] = generation_mode

    return questions


def generate_questions_for_job(
    db: Session,
    job_id: int,
    candidate_id: Optional[int] = None,
    number_of_questions: int = 10,
) -> List[Dict]:
    return generate_questions(
        db=db,
        job_id=job_id,
        candidate_id=candidate_id,
        number_of_questions=number_of_questions,
        save_to_database=True,
    )


def huggingface_available() -> bool:
    """Return True when Hugging Face AI credentials are configured."""
    return bool(
        os.getenv("HF_TOKEN", "").strip()
        and os.getenv("HF_MODEL", "").strip()
    )
