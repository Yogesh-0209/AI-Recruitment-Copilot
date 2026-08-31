from modules.resume_parser.file_loader import extract_text

from modules.resume_parser.extractor import (
    extract_email,
    extract_phone,
    extract_skills,
    extract_name
)


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

print("===== CANDIDATE INFORMATION =====")

print("NAME:", extract_name(text))
print("Email:", extract_email(text))
print("Phone:", extract_phone(text))
print("Skills:", extract_skills(text))