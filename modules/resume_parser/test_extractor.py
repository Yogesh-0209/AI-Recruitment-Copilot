from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import extract_email, extract_phone


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

email = extract_email(text)
phone = extract_phone(text)

print("Email:", email)
print("Phone:", phone)