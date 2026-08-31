from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import (
    extract_name,
    extract_email,
    extract_phone,
    extract_skills
)
from modules.resume_parser.section_extractor import extract_sections

file_path = "data/resumes/resume_04_vikram_singh.pdf"

text = extract_text(file_path)

sections = extract_sections(text)

profile = {
    "name": extract_name(text),
    "email": extract_email(text),
    "phone": extract_phone(text),
    "education": sections.get("education", []),
    "skills": extract_skills(text),
    "experience": sections.get("experience", []),
    "certifications": sections.get("certifications", []),
    "projects": sections.get("projects", [])
}

print("\n========== FINAL PROFILE ==========\n")

for key, value in profile.items():
    print(f"\n{key.upper()}:")
    print(value)