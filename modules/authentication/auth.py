import hashlib
import hmac
import secrets

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from database.connection import SessionLocal, engine
from database.models import User


SECURITY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS user_security (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL UNIQUE,
    security_question VARCHAR(255) NOT NULL,
    security_answer_hash VARCHAR(255) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_user_security_user
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE
)
"""


def _ensure_security_table():
    with engine.begin() as connection:
        connection.execute(text(SECURITY_TABLE_SQL))


_ensure_security_table()


def hash_password(password: str) -> str:
    """Create a salted PBKDF2 password hash."""
    salt = secrets.token_bytes(16)

    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        310_000,
    )

    return (
        f"pbkdf2_sha256$310000$"
        f"{salt.hex()}${derived.hex()}"
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_hex, digest_hex = (
            stored_hash.split("$", 3)
        )

        if algorithm != "pbkdf2_sha256":
            return False

        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)

        actual = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            int(iterations),
        )

        return hmac.compare_digest(actual, expected)

    except (ValueError, TypeError):
        return False


def _hash_security_answer(answer: str) -> str:
    return hash_password(
        answer.strip().lower()
    )


def signup_user(
    name,
    email,
    password,
    security_question,
    security_answer,
    role="candidate",
):
    name = str(name or "").strip()
    email = str(email or "").strip().lower()
    role = str(role or "candidate").strip().lower()

    if not name or not email or not password:
        return False, "Name, email and password are required."

    if role not in {"candidate", "recruiter"}:
        role = "candidate"

    if (
        not security_question
        or not str(security_answer or "").strip()
    ):
        return False, "Security question and answer are required."

    db = SessionLocal()

    try:
        existing = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if existing:
            return (
                False,
                "An account with this email already exists. "
                "Please login instead.",
            )

        user = User(
            name=name,
            email=email,
            password_hash=hash_password(password),
            role=role,
        )

        db.add(user)
        db.flush()

        db.execute(
            text(
                "INSERT INTO user_security "
                "(user_id, security_question, security_answer_hash) "
                "VALUES (:user_id, :question, :answer_hash)"
            ),
            {
                "user_id": user.id,
                "question": str(
                    security_question
                ).strip(),
                "answer_hash": _hash_security_answer(
                    security_answer
                ),
            },
        )

        db.commit()

        return True, "Account created successfully."

    except IntegrityError:
        db.rollback()

        return (
            False,
            "An account with this email already exists. "
            "Please login instead.",
        )

    except Exception as exc:
        db.rollback()

        return (
            False,
            f"Could not create account: {exc}",
        )

    finally:
        db.close()


def login_user(email, password):
    email = str(email or "").strip().lower()

    db = SessionLocal()

    try:
        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            return False, None

        if not _verify_password(
            password,
            user.password_hash,
        ):
            return False, None

        return True, {
            "id": user.id,
            "name": user.name,
            "email": user.email,
            "role": (
                user.role or "candidate"
            ).strip().lower(),
        }

    finally:
        db.close()


def get_security_question(email):
    email = str(email or "").strip().lower()

    db = SessionLocal()

    try:
        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            return None

        row = db.execute(
            text(
                "SELECT security_question "
                "FROM user_security "
                "WHERE user_id = :user_id"
            ),
            {
                "user_id": user.id
            },
        ).first()

        return row[0] if row else None

    finally:
        db.close()


def verify_security_answer(email, answer):
    email = str(email or "").strip().lower()

    db = SessionLocal()

    try:
        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            return False

        row = db.execute(
            text(
                "SELECT security_answer_hash "
                "FROM user_security "
                "WHERE user_id = :user_id"
            ),
            {
                "user_id": user.id
            },
        ).first()

        if not row:
            return False

        return _verify_password(
            str(answer or "").strip().lower(),
            row[0],
        )

    finally:
        db.close()


def reset_password(email, new_password):
    email = str(email or "").strip().lower()

    db = SessionLocal()

    try:
        user = (
            db.query(User)
            .filter(User.email == email)
            .first()
        )

        if not user:
            return (
                False,
                "No account was found with this email.",
            )

        user.password_hash = hash_password(
            new_password
        )

        db.commit()

        return True, "Password reset successfully."

    except Exception as exc:
        db.rollback()

        return (
            False,
            f"Could not reset password: {exc}",
        )

    finally:
        db.close()


# Kept for backward compatibility with older imports.
USERS = {}