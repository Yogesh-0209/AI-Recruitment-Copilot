from database.connection import Base, engine

# Import all models so SQLAlchemy knows about every table.
from database.models import (
    User,
    Candidate,
    Job,
    CandidateMatch,
    SkillGapReport,
    Application,
    InterviewQuestion,
    InterviewResult,
    VoiceScreening,
    Feedback,
)


def initialize_database():
    Base.metadata.create_all(bind=engine)

    print("Database tables created successfully.")


if __name__ == "__main__":
    initialize_database()