from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import extract_candidate_info
from modules.resume_parser.profile_generator import generate_profile


file_path = "data/resumes/test_resume.pdf"

text = extract_text(file_path)

candidate = extract_candidate_info(text)

profile = generate_profile(candidate)

print("\n===== STRUCTURED CANDIDATE PROFILE =====\n")

print(profile.to_string(index=False))