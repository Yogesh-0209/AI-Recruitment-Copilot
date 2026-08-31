from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.section_parser import extract_sections


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

sections = extract_sections(text)


print("\n===== RESUME SECTIONS =====")

for section, content in sections.items():

    print(f"\n--- {section.upper()} ---")
    print(content)