from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.section_parser import (
    extract_sections,
    extract_education,
    extract_experience,
    extract_certifications,
    extract_projects
)


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

sections = extract_sections(text)


print("\n===== EDUCATION =====")

education = extract_education(
    sections.get("education", "")
)

print(education)


print("\n===== EXPERIENCE =====")

experience = extract_experience(
    sections.get("experience", "")
)

print(experience)


print("\n===== CERTIFICATIONS =====")

certifications = extract_certifications(
    sections.get("certifications", "")
)

print(certifications)


print("\n===== PROJECTS =====")

projects = extract_projects(
    sections.get("projects", "")
)

print(projects)