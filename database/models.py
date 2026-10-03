from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from database.connection import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    role = Column(String(50), nullable=False, default="candidate")
    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship(
        "Candidate",
        back_populates="user",
        uselist=False,
    )


class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    name = Column(String(150), nullable=False)
    email = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    location = Column(String(255), nullable=True)

    summary = Column(Text, nullable=True)
    education = Column(Text, nullable=True)
    experience_years = Column(Float, default=0)

    skills = Column(Text, nullable=True)
    certifications = Column(Text, nullable=True)
    projects = Column(Text, nullable=True)

    resume_filename = Column(String(255), nullable=True)
    resume_path = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    user = relationship(
        "User",
        back_populates="candidate",
    )

    matches = relationship(
        "CandidateMatch",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    applications = relationship(
        "Application",
        back_populates="candidate",
        cascade="all, delete-orphan",
    )


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)

    recruiter_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    job_id = Column(String(100), unique=True, nullable=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    required_skills = Column(Text, nullable=True)
    experience_required = Column(Float, default=0)
    education_required = Column(Text, nullable=True)
    location = Column(String(255), nullable=True)

    status = Column(
        String(50),
        nullable=False,
        default="Open",
    )

    created_at = Column(DateTime, default=datetime.utcnow)

    matches = relationship(
        "CandidateMatch",
        back_populates="job",
        cascade="all, delete-orphan",
    )

    applications = relationship(
        "Application",
        back_populates="job",
        cascade="all, delete-orphan",
    )


class CandidateMatch(Base):
    __tablename__ = "candidate_matches"

    id = Column(Integer, primary_key=True, autoincrement=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    hiring_score = Column(Float, nullable=False)
    skill_score = Column(Float, nullable=True)
    experience_score = Column(Float, nullable=True)
    education_score = Column(Float, nullable=True)

    matched_skills = Column(Text, nullable=True)
    missing_skills = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    candidate = relationship(
        "Candidate",
        back_populates="matches",
    )

    job = relationship(
        "Job",
        back_populates="matches",
    )


class SkillGapReport(Base):
    __tablename__ = "skill_gap_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    matched_skills = Column(Text, nullable=True)
    missing_skills = Column(Text, nullable=True)
    recommendations = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Application(Base):
    __tablename__ = "applications"

    id = Column(Integer, primary_key=True, autoincrement=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    status = Column(
        String(50),
        nullable=False,
        default="Applied",
    )

    applied_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    candidate = relationship(
        "Candidate",
        back_populates="applications",
    )

    job = relationship(
        "Job",
        back_populates="applications",
    )


class InterviewQuestion(Base):
    __tablename__ = "interview_questions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=True,
    )

    question = Column(Text, nullable=False)
    category = Column(String(100), nullable=False)
    difficulty = Column(String(50), nullable=True)

    expected_topics = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class InterviewResult(Base):
    __tablename__ = "interview_results"

    id = Column(Integer, primary_key=True, autoincrement=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    question_id = Column(
        Integer,
        ForeignKey("interview_questions.id"),
        nullable=True,
    )

    answer = Column(Text, nullable=True)

    technical_score = Column(Float, nullable=True)
    communication_score = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)

    feedback = Column(Text, nullable=True)
    recommendation = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class VoiceScreening(Base):
    __tablename__ = "voice_screenings"

    id = Column(Integer, primary_key=True, autoincrement=True)

    candidate_id = Column(
        Integer,
        ForeignKey("candidates.id"),
        nullable=False,
    )

    job_id = Column(
        Integer,
        ForeignKey("jobs.id"),
        nullable=False,
    )

    audio_path = Column(String(500), nullable=True)
    transcript = Column(Text, nullable=True)

    clarity_score = Column(Float, nullable=True)
    confidence_score = Column(Float, nullable=True)
    relevance_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)

    recommendation = Column(String(100), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Integer, primary_key=True, autoincrement=True)

    user_id = Column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
    )

    rating = Column(Integer, nullable=True)
    comment = Column(Text, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)