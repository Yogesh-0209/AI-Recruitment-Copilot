from modules.resume_parser.file_loader import extract_text


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

print("===== EXTRACTED RESUME TEXT =====")
print(text)
print("===== END =====")