import os
import wave
from pathlib import Path

from database.models import VoiceScreening


def _score_from_transcript(transcript: str, job, candidate):
    """Lightweight deterministic screening scores used after transcription."""
    text = (transcript or "").strip().lower()

    if not text:
        return 0.0, 0.0, 0.0, 0.0, "Needs Improvement"

    required = job.required_skills or ""
    if isinstance(required, str):
        required_text = required.lower()
    else:
        required_text = " ".join(map(str, required)).lower()

    skill_tokens = [
        token.strip(" []'\"")
        for token in required_text.replace(",", " ").split()
        if len(token.strip(" []'\"")) > 2
    ]

    matched = sum(1 for skill in skill_tokens if skill and skill in text)
    relevance = min(100.0, 45.0 + (matched / max(len(skill_tokens), 1)) * 55.0)

    words = text.split()
    length_score = min(100.0, len(words) * 2.0)
    clarity = min(100.0, 55.0 + length_score * 0.45)

    confidence = min(100.0, 50.0 + min(len(words), 80) * 0.6)

    overall = round(
        clarity * 0.30
        + confidence * 0.25
        + relevance * 0.45,
        2,
    )

    if overall >= 80:
        recommendation = "Strong"
    elif overall >= 65:
        recommendation = "Moderate"
    else:
        recommendation = "Needs Improvement"

    return (
        round(clarity, 2),
        round(confidence, 2),
        round(relevance, 2),
        overall,
        recommendation,
    )


def transcribe_audio(audio_path: str) -> str:
    """
    Transcribe WAV audio with SpeechRecognition/Google speech recognition.

    The service is optional: if SpeechRecognition is not installed or the
    recognition service cannot be reached, a clear exception is returned to
    the caller so the UI can explain the next step.
    """
    try:
        import speech_recognition as sr
    except ImportError as exc:
        raise RuntimeError(
            "SpeechRecognition is not installed. Run: "
            "pip install SpeechRecognition"
        ) from exc

    recognizer = sr.Recognizer()

    with sr.AudioFile(audio_path) as source:
        audio = recognizer.record(source)

    try:
        return recognizer.recognize_google(audio)
    except sr.UnknownValueError as exc:
        raise RuntimeError(
            "The speech could not be understood. Please record clearly "
            "and speak for a few seconds."
        ) from exc
    except sr.RequestError as exc:
        raise RuntimeError(
            "Speech transcription service is unavailable. "
            "Check your internet connection and try again."
        ) from exc


def save_voice_screening(
    db,
    candidate_id: int,
    job_id: int,
    audio_path: str,
    transcript: str,
    job,
    candidate,
):
    clarity, confidence, relevance, overall, recommendation = (
        _score_from_transcript(transcript, job, candidate)
    )

    record = VoiceScreening(
        candidate_id=candidate_id,
        job_id=job_id,
        audio_path=audio_path,
        transcript=transcript,
        clarity_score=clarity,
        confidence_score=confidence,
        relevance_score=relevance,
        overall_score=overall,
        recommendation=recommendation,
    )

    db.add(record)
    db.commit()
    db.refresh(record)

    return record
