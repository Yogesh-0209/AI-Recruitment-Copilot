import re
import spacy

nlp = spacy.load("en_core_web_sm")


SKILLS = [

    # Programming Languages
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

    # Web Development
    "HTML",
    "CSS",
    "React",
    "Angular",
    "Node.js",
    "Django",
    "Flask",

    # Database
    "SQL",
    "MySQL",
    "PostgreSQL",
    "MongoDB",
    "Oracle",

    # Data Science / AI
    "Machine Learning",
    "Deep Learning",
    "Artificial Intelligence",
    "Natural Language Processing",
    "NLP",
    "Computer Vision",
    "Data Science",
    "Data Analysis",

    # ML Libraries
    "TensorFlow",
    "PyTorch",
    "Scikit-learn",
    "Pandas",
    "NumPy",
    "Matplotlib",
    "Keras",

    # Cloud / DevOps
    "AWS",
    "Azure",
    "Google Cloud",
    "Docker",
    "Kubernetes",

    # Tools
    "Git",
    "GitHub",
    "Linux",
    "Jenkins",

    # Other
    "REST API",
    "Power BI",
    "Tableau"
]


def extract_email(text):
    """Extract email address from resume text."""

    pattern = r'[\w\.-]+@[\w\.-]+\.\w+'

    match = re.search(pattern, text)

    if match:
        return match.group(0)

    return None


def extract_phone(text):
    """Extract phone number from resume text."""

    pattern = r'\+?\d[\d\s\-\(\)]{8,}\d'

    match = re.search(pattern, text)

    if match:
        return match.group(0).strip()

    return None


def extract_name(text):
    """Extract candidate name using spaCy NER."""

    doc = nlp(text)

    for entity in doc.ents:

        if entity.label_ == "PERSON":

            return entity.text

    return None


def extract_skills(text):
    """Extract known skills from resume text."""

    found_skills = []

    text_lower = text.lower()

    for skill in SKILLS:

        if skill.lower() in text_lower:

            found_skills.append(skill)

    return found_skills