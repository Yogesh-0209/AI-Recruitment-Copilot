import re
import spacy


# ============================================================
# LOAD NLP MODEL
# ============================================================

nlp = spacy.load("en_core_web_sm")


# ============================================================
# SKILLS
# ============================================================

SKILLS = [
    "Python",
    "Java",
    "C",
    "C++",
    "C#",
    "JavaScript",
    "TypeScript",
    "R",
    "Go",
    "PHP",
    "HTML",
    "CSS",
    "React",
    "Angular",
    "Node.js",
    "Django",
    "Flask",
    "SQL",
    "MySQL",
    "PostgreSQL",
    "MongoDB",
    "Oracle",
    "Machine Learning",
    "Deep Learning",
    "Artificial Intelligence",
    "Natural Language Processing",
    "NLP",
    "Computer Vision",
    "Data Science",
    "Data Analysis",
    "TensorFlow",
    "PyTorch",
    "Scikit-learn",
    "Pandas",
    "NumPy",
    "Matplotlib",
    "Keras",
    "AWS",
    "Azure",
    "Google Cloud",
    "Docker",
    "Kubernetes",
    "Git",
    "GitHub",
    "Linux",
    "Jenkins",
    "REST API",
    "Power BI",
    "Tableau",
]


# ============================================================
# EMAIL EXTRACTION
# ============================================================

def extract_email(text):
    """
    Extract email address from resume text.
    """

    pattern = r'[\w\.-]+@[\w\.-]+\.\w+'

    match = re.search(
        pattern,
        text
    )

    if match:
        return match.group(0)

    return None


# ============================================================
# PHONE EXTRACTION
# ============================================================

def extract_phone(text):
    """
    Extract phone number from resume text.
    """

    pattern = r'\+?\d[\d\s\-\(\)]{8,}\d'

    match = re.search(
        pattern,
        text
    )

    if match:

        return match.group(0).strip()

    return None


# ============================================================
# NAME EXTRACTION
# ============================================================

def extract_name(text):
    """
    Extract candidate name from resume.

    Strategy:
    1. Check the first few meaningful lines.
    2. Reject lines that are clearly skills/contact information.
    3. Prefer a normal human-name pattern.
    4. Use spaCy PERSON detection only as fallback.
    """

    if not text:
        return None

    # --------------------------------------------------------
    # Build clean lines
    # --------------------------------------------------------

    lines = []

    for line in text.splitlines():

        line = line.strip()

        if line:
            lines.append(line)

    # --------------------------------------------------------
    # Words that should never be considered a name
    # --------------------------------------------------------

    blocked_words = {
        skill.lower()
        for skill in SKILLS
    }

    blocked_words.update({
        "resume",
        "curriculum vitae",
        "cv",
        "education",
        "skills",
        "experience",
        "certifications",
        "certification",
        "projects",
        "project",
        "software engineer",
        "data scientist",
        "developer",
        "engineer",
        "intern",
        "email",
        "phone",
        "contact",
        "linkedin",
        "github",
    })

    # --------------------------------------------------------
    # Check first 10 lines
    # --------------------------------------------------------

    for line in lines[:10]:

        cleaned = line.strip()

        lower_line = cleaned.lower()

        # Skip blocked terms
        if lower_line in blocked_words:
            continue

        # Skip email lines
        if "@" in cleaned:
            continue

        # Skip lines containing phone numbers
        if re.search(
            r'\+?\d[\d\s\-\(\)]{7,}\d',
            cleaned
        ):
            continue

        # Skip lines that are too long
        words = cleaned.split()

        if len(words) < 2 or len(words) > 4:
            continue

        # ----------------------------------------------------
        # Normal name pattern
        # ----------------------------------------------------
        #
        # Examples:
        # Ananya Sharma
        # Sarah Johnson
        # Rahul Kumar
        #
        # Allows initials such as:
        # A. Sharma
        # R Kumar
        # ----------------------------------------------------

        name_pattern = (
            r'^[A-Za-z]+(?:[.\'-][A-Za-z]+)*'
            r'(?:\s+[A-Za-z]+(?:[.\'-][A-Za-z]+)*){1,3}$'
        )

        if re.match(
            name_pattern,
            cleaned
        ):

            # Make sure the complete line is not a skill
            if lower_line not in blocked_words:

                return cleaned

    # --------------------------------------------------------
    # spaCy fallback
    # --------------------------------------------------------

    doc = nlp(text)

    for entity in doc.ents:

        if entity.label_ != "PERSON":
            continue

        candidate = entity.text.strip()

        candidate_lower = candidate.lower()

        # Never return a known skill
        if candidate_lower in blocked_words:
            continue

        # Never return email
        if "@" in candidate:
            continue

        # Candidate should look like a name
        words = candidate.split()

        if len(words) < 2 or len(words) > 4:
            continue

        if re.match(
            r'^[A-Za-z .\'-]+$',
            candidate
        ):

            return candidate

    return None


# ============================================================
# SKILL EXTRACTION
# ============================================================

def extract_skills(text):
    """
    Extract skills from resume text using
    the predefined skill vocabulary.
    """

    found_skills = []

    text_lower = text.lower()

    for skill in SKILLS:

        if skill.lower() in text_lower:

            found_skills.append(skill)

    return found_skills