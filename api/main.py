import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from sqlalchemy.orm import Session

from database.connection import Base, SessionLocal, engine
from database.models import Application, Candidate, Job

app = FastAPI(
    title="AI Recruitment Copilot API",
    version="1.0.0",
)


DEFAULT_JOB_FILE = Path(__file__).resolve().parent.parent / "jobs" / "job_profiles.json"


def _list_value(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [str(value)]


def seed_default_jobs():
    """Create the demo jobs in a fresh cloud database without duplicating them."""
    if not DEFAULT_JOB_FILE.exists():
        return 0

    with DEFAULT_JOB_FILE.open("r", encoding="utf-8") as file:
        data = json.load(file)

    jobs = data.get("jobs", []) if isinstance(data, dict) else data
    if not isinstance(jobs, list):
        return 0

    db: Session = SessionLocal()
    created = 0
    try:
        for item in jobs:
            external_id = str(item.get("job_id") or "").strip()
            title = str(item.get("title") or "Untitled Job").strip()
            if not external_id or not title:
                continue

            existing = db.query(Job).filter(Job.job_id == external_id).first()
            if existing:
                # Keep cloud data stable, but fill any missing seed fields.
                if not existing.required_skills:
                    existing.required_skills = json.dumps(_list_value(item.get("required_skills")))
                if existing.experience_required in (None, 0):
                    existing.experience_required = float(item.get("experience_required") or 0)
                if not existing.education_required:
                    existing.education_required = item.get("education_required")
                if not existing.location:
                    existing.location = item.get("location")
                if not existing.description:
                    existing.description = item.get("description")
                if not existing.status:
                    existing.status = "Open"
                continue

            db.add(
                Job(
                    job_id=external_id,
                    title=title,
                    description=item.get("description") or "",
                    required_skills=json.dumps(_list_value(item.get("required_skills"))),
                    experience_required=float(item.get("experience_required") or 0),
                    education_required=item.get("education_required") or "",
                    location=item.get("location") or "",
                    status=item.get("status") or "Open",
                )
            )
            created += 1

        db.commit()
        return created
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@app.on_event("startup")
def initialize_database():
    # Render creates a fresh PostgreSQL database. Create tables and then seed
    # the demo jobs so candidate matching, applications, interviews and voice
    # screening can immediately find JOB001-JOB005.
    Base.metadata.create_all(bind=engine)
    seed_default_jobs()


@app.get("/")
def root():
    return {
        "message": "AI Recruitment Copilot API is running",
        "status": "ok",
    }


@app.get("/health")
def health():
    db = SessionLocal()
    try:
        db.query(Job).count()
        return {"status": "healthy", "database": "connected"}
    finally:
        db.close()


@app.get("/ats/candidates")
def get_candidates():
    db = SessionLocal()
    try:
        candidates = db.query(Candidate).order_by(Candidate.updated_at.desc()).all()
        return {
            "candidates": [
                {
                    "id": c.id,
                    "name": c.name,
                    "email": c.email,
                    "experience_years": c.experience_years or 0,
                    "resume_filename": c.resume_filename,
                }
                for c in candidates
            ],
            "total": len(candidates),
        }
    finally:
        db.close()


@app.get("/ats/jobs")
def get_jobs():
    db = SessionLocal()
    try:
        jobs = db.query(Job).order_by(Job.id.asc()).all()
        return {
            "jobs": [
                {
                    "id": job.id,
                    "job_id": job.job_id,
                    "title": job.title,
                    "description": job.description or "",
                    "required_skills": _list_value(json.loads(job.required_skills) if job.required_skills else []),
                    "experience_required": job.experience_required or 0,
                    "education_required": job.education_required or "",
                    "location": job.location or "",
                    "status": job.status or "Open",
                }
                for job in jobs
            ],
            "total": len(jobs),
        }
    finally:
        db.close()


@app.get("/ats/applications")
def get_applications():
    db = SessionLocal()
    try:
        applications = db.query(Application).order_by(Application.applied_at.desc()).all()
        rows = []
        for application in applications:
            candidate = application.candidate
            job = application.job
            rows.append(
                {
                    "id": application.id,
                    "candidate_id": application.candidate_id,
                    "candidate_name": candidate.name if candidate else "",
                    "candidate_email": candidate.email if candidate else "",
                    "job_id": job.job_id if job else application.job_id,
                    "job_title": job.title if job else "",
                    "status": application.status or "Applied",
                    "applied_at": str(application.applied_at) if application.applied_at else "",
                }
            )
        return {"applications": rows, "total": len(rows)}
    finally:
        db.close()


@app.post("/ats/applications")
def create_application(payload: dict):
    candidate_id = payload.get("candidate_id")
    job_id = payload.get("job_id")

    if not candidate_id or not job_id:
        raise HTTPException(status_code=400, detail="candidate_id and job_id are required")

    db = SessionLocal()
    try:
        candidate = db.query(Candidate).filter(Candidate.id == int(candidate_id)).first()
        job = db.query(Job).filter(Job.id == int(job_id)).first()
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")

        existing = (
            db.query(Application)
            .filter(
                Application.candidate_id == candidate.id,
                Application.job_id == job.id,
            )
            .first()
        )
        if existing:
            return {
                "message": "Application already exists",
                "application": {"id": existing.id, "status": existing.status},
            }

        application = Application(
            candidate_id=candidate.id,
            job_id=job.id,
            status=payload.get("status") or "Applied",
        )
        db.add(application)
        db.commit()
        db.refresh(application)
        return {
            "message": "Application created successfully",
            "application": {"id": application.id, "status": application.status},
        }
    finally:
        db.close()


@app.put("/ats/applications/{application_id}/status")
def update_application_status(application_id: int, payload: dict):
    status = str(payload.get("status") or "").strip()
    allowed = {"Applied", "Shortlisted", "Hold", "Rejected"}
    if status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of: {', '.join(sorted(allowed))}")

    db = SessionLocal()
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise HTTPException(status_code=404, detail="Application not found")

        application.status = status
        db.commit()
        db.refresh(application)
        return {
            "message": "Application status updated successfully",
            "application_id": application.id,
            "status": application.status,
        }
    finally:
        db.close()
