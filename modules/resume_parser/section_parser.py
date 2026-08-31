import re


def extract_sections(text):
    """
    Extract major resume sections from raw resume text.

    Returns:
        dict containing education, skills, experience,
        certifications and projects.
    """

    sections = {
        "education": [],
        "skills": [],
        "experience": [],
        "certifications": [],
        "projects": []
    }

    # Section heading patterns
    section_patterns = {
        "education": r"^(education|academic background|academic qualifications?)$",
        "skills": r"^(skills|technical skills|key skills|core skills)$",
        "experience": r"^(experience|work experience|professional experience|employment history)$",
        "certifications": r"^(certifications?|certificates?)$",
        "projects": r"^(projects?|academic projects?|personal projects?)$"
    }

    current_section = None

    for line in text.splitlines():

        line = line.strip()

        if not line:
            continue

        # Remove common bullets
        clean_line = re.sub(r"^[•\-\*\u2022]+", "", line).strip()

        # Check whether line is a section heading
        matched_section = None

        for section, pattern in section_patterns.items():

            if re.match(pattern, clean_line, re.IGNORECASE):
                matched_section = section
                break

        if matched_section:
            current_section = matched_section
            continue

        # Add content to current section
        if current_section:
            sections[current_section].append(clean_line)

    return sections