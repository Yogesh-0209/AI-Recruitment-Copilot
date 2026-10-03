import json
from pathlib import Path

from database.connection import SessionLocal
from database.models import Candidate, Job


PROJECT_ROOT = Path(__file__).resolve().parent.parent

CANDIDATES_DIR = PROJECT_ROOT / "data" / "candidates"
JOBS_FILE = PROJECT_ROOT / "jobs" / "job_profiles.json"


def json_text(value):
    """Convert Python lists/dictionaries into JSON text."""
    if value is None:
        return None

    return json.dumps(
        value,
        ensure_ascii=False,
    )


def load_candidates(db):
    """Import candidate JSON files into MySQL."""

    imported = 0
    skipped = 0

    for file_path in sorted(CANDIDATES_DIR.glob("*.json")):

        with open(
            file_path,
            "r",
            encoding="utf-8",
        ) as file:
            candidate_data = json.load(file)

        email = candidate_data.get("email")

        existing = (
            db.query(Candidate)
            .filter(Candidate.email == email)
            .first()
        )

        if existing:
            skipped += 1
            continue

        candidate = Candidate(
            name=candidate_data.get("name", ""),
            email=email,
            phone=candidate_data.get("phone"),
            location=candidate_data.get("location"),
            summary=candidate_data.get("summary"),
            education=json_text(
                candidate_data.get("education", [])
            ),
            experience_years=candidate_data.get(
                "experience_years",
                0,
            ),
            skills=json_text(
                candidate_data.get("skills", [])
            ),
            certifications=json_text(
                candidate_data.get(
                    "certifications",
                    [],
                )
            ),
            projects=json_text(
                candidate_data.get(
                    "projects",
                    [],
                )
            ),
            resume_filename=file_path.name,
            resume_path=None,
        )

        db.add(candidate)
        imported += 1

    return imported, skipped


def load_jobs(db):
    """Import job profiles into MySQL."""

    with open(
        JOBS_FILE,
        "r",
        encoding="utf-8",
    ) as file:
        job_data = json.load(file)

    imported = 0
    skipped = 0

    for item in job_data.get("jobs", []):

        job_id = item.get("job_id")

        existing = (
            db.query(Job)
            .filter(Job.job_id == job_id)
            .first()
        )

        if existing:
            skipped += 1
            continue

        job = Job(
            job_id=job_id,
            title=item.get("title", ""),
            description=item.get("description"),
            required_skills=json_text(
                item.get(
                    "required_skills",
                    [],
                )
            ),
            experience_required=item.get(
                "experience_required",
                0,
            ),
            education_required=item.get(
                "education_required",
                "",
            ),
            status="Open",
        )

        db.add(job)
        imported += 1

    return imported, skipped


def seed_database():
    db = SessionLocal()

    try:
        candidate_imported, candidate_skipped = (
            load_candidates(db)
        )

        job_imported, job_skipped = load_jobs(db)

        db.commit()

        print()
        print("========================================")
        print(" DATABASE SEED COMPLETED")
        print("========================================")
        print(
            f"Candidates imported : {candidate_imported}"
        )
        print(
            f"Candidates skipped  : {candidate_skipped}"
        )
        print(
            f"Jobs imported       : {job_imported}"
        )
        print(
            f"Jobs skipped        : {job_skipped}"
        )
        print("========================================")
        print()

    except Exception:
        db.rollback()
        raise

    finally:
        db.close()


if __name__ == "__main__":
    seed_database()