from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from database.connection import SessionLocal
from database.models import Candidate, Job, Application


# ============================================================
# FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="AI Recruitment Copilot API",
    description=(
        "REST API backend for the AI Recruitment Copilot. "
        "Provides ATS, candidate, job and application services."
    ),
    version="1.0.0",
)


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class CandidateResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    experience_years: Optional[float] = None
    skills: Optional[str] = None
    resume_filename: Optional[str] = None


class ApplicationCreate(BaseModel):
    candidate_id: int
    job_id: int


class ApplicationStatusUpdate(BaseModel):
    status: str


# ============================================================
# BASIC HEALTH ENDPOINTS
# ============================================================

@app.get("/")
def root():
    return {
        "message": "AI Recruitment Copilot API is running",
        "status": "success",
        "version": "1.0.0",
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "AI Recruitment Copilot API",
        "database": "MySQL",
    }


# ============================================================
# ATS - CANDIDATES
# ============================================================

@app.get("/ats/candidates")
def list_candidates():
    """
    Return candidates stored in the MySQL database.
    """

    db = SessionLocal()

    try:
        candidates = (
            db.query(Candidate)
            .order_by(Candidate.updated_at.desc())
            .all()
        )

        result = []

        for candidate in candidates:
            result.append(
                {
                    "id": candidate.id,
                    "name": candidate.name,
                    "email": candidate.email,
                    "phone": candidate.phone,
                    "location": candidate.location,
                    "experience_years": candidate.experience_years,
                    "skills": candidate.skills,
                    "resume_filename": candidate.resume_filename,
                }
            )

        return {
            "total": len(result),
            "candidates": result,
        }

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {exc}",
        )

    finally:
        db.close()


# ============================================================
# ATS - JOBS
# ============================================================

@app.get("/ats/jobs")
def list_jobs():
    """
    Return jobs stored in the MySQL database.
    """

    db = SessionLocal()

    try:
        jobs = (
            db.query(Job)
            .order_by(Job.created_at.desc())
            .all()
        )

        result = []

        for job in jobs:
            result.append(
                {
                    "id": job.id,
                    "job_id": job.job_id,
                    "title": job.title,
                    "description": job.description,
                    "required_skills": job.required_skills,
                    "experience_required": job.experience_required,
                    "education_required": job.education_required,
                    "location": job.location,
                    "status": job.status,
                }
            )

        return {
            "total": len(result),
            "jobs": result,
        }

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {exc}",
        )

    finally:
        db.close()


# ============================================================
# ATS - APPLICATIONS
# ============================================================

@app.get("/ats/applications")
def list_applications():
    """
    Return applications from the existing MySQL database.
    """

    db = SessionLocal()

    try:
        applications = (
            db.query(Application)
            .order_by(Application.applied_at.desc())
            .all()
        )

        result = []

        for application in applications:
            result.append(
                {
                    "id": application.id,
                    "candidate_id": application.candidate_id,
                    "candidate_name": (
                        application.candidate.name
                        if application.candidate
                        else None
                    ),
                    "candidate_email": (
                        application.candidate.email
                        if application.candidate
                        else None
                    ),
                    "job_id": application.job_id,
                    "job_title": (
                        application.job.title
                        if application.job
                        else None
                    ),
                    "status": application.status,
                    "applied_at": (
                        application.applied_at.isoformat()
                        if application.applied_at
                        else None
                    ),
                }
            )

        return {
            "total": len(result),
            "applications": result,
        }

    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Database error: {exc}",
        )

    finally:
        db.close()


# ============================================================
# ATS - CREATE APPLICATION
# ============================================================

@app.post("/ats/applications")
def create_application(application_data: ApplicationCreate):
    """
    Create a new job application in MySQL.
    """

    db = SessionLocal()

    try:
        candidate = (
            db.query(Candidate)
            .filter(Candidate.id == application_data.candidate_id)
            .first()
        )

        if not candidate:
            raise HTTPException(
                status_code=404,
                detail="Candidate not found.",
            )

        job = (
            db.query(Job)
            .filter(Job.id == application_data.job_id)
            .first()
        )

        if not job:
            raise HTTPException(
                status_code=404,
                detail="Job not found.",
            )

        existing = (
            db.query(Application)
            .filter(
                Application.candidate_id
                == application_data.candidate_id,
                Application.job_id
                == application_data.job_id,
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail="Candidate has already applied for this job.",
            )

        new_application = Application(
            candidate_id=application_data.candidate_id,
            job_id=application_data.job_id,
            status="Applied",
        )

        db.add(new_application)
        db.commit()
        db.refresh(new_application)

        return {
            "message": "Application created successfully.",
            "application": {
                "id": new_application.id,
                "candidate_id": new_application.candidate_id,
                "candidate_name": candidate.name,
                "job_id": new_application.job_id,
                "job_title": job.title,
                "status": new_application.status,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Database error: {exc}",
        )

    finally:
        db.close()


# ============================================================
# ATS - UPDATE APPLICATION STATUS
# ============================================================

@app.put("/ats/applications/{application_id}/status")
def update_application_status(
    application_id: int,
    status_data: ApplicationStatusUpdate,
):
    """
    Update an application's recruitment status.

    Examples:
    Applied
    Shortlisted
    Hold
    Rejected
    """

    allowed_statuses = {
        "Applied",
        "Shortlisted",
        "Hold",
        "Rejected",
    }

    status = status_data.status.strip()

    if status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid status. Use one of: "
                "Applied, Shortlisted, Hold, Rejected."
            ),
        )

    db = SessionLocal()

    try:
        application = (
            db.query(Application)
            .filter(Application.id == application_id)
            .first()
        )

        if not application:
            raise HTTPException(
                status_code=404,
                detail="Application not found.",
            )

        application.status = status

        db.commit()
        db.refresh(application)

        return {
            "message": "Application status updated successfully.",
            "application": {
                "id": application.id,
                "candidate_id": application.candidate_id,
                "job_id": application.job_id,
                "status": application.status,
            },
        }

    except HTTPException:
        db.rollback()
        raise

    except SQLAlchemyError as exc:
        db.rollback()

        raise HTTPException(
            status_code=500,
            detail=f"Database error: {exc}",
        )

    finally:
        db.close()