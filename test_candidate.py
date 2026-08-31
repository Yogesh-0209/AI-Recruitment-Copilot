from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import extract_candidate_info


file_path = "data/resumes/test_resume.pdf"

# Step 1: Extract raw text
text = extract_text(file_path)

# Step 2: Extract candidate information
candidate = extract_candidate_info(text)

# Step 3: Display structured profile
print("\n===== STRUCTURED CANDIDATE PROFILE =====\n")

for key, value in candidate.items():

    print(f"{key.upper()}:")
    print(value)
    print()

    