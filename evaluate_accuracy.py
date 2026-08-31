import json
import os

from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import extract_candidate_info


RESUME_FOLDER = "data/resumes"
GROUND_TRUTH_FILE = "data/ground_truth/expected_profiles.json"


def normalize(value):
    """
    Normalize text before comparison.
    """

    if value is None:
        return ""

    return str(value).strip().lower()


def compare_values(expected, actual):
    """
    Compare expected and actual values.
    """

    if isinstance(expected, list):

        expected_normalized = {
            normalize(item)
            for item in expected
        }

        actual_normalized = {
            normalize(item)
            for item in (actual or [])
        }

        return expected_normalized.issubset(actual_normalized)

    return normalize(expected) == normalize(actual)


def evaluate_resume(filename, expected):
    """
    Evaluate one resume.
    """

    file_path = os.path.join(
        RESUME_FOLDER,
        filename
    )

    text = extract_text(file_path)

    actual = extract_candidate_info(text)

    fields = [
        "name",
        "email",
        "phone",
        "education",
        "skills",
        "experience",
        "certifications",
        "projects"
    ]

    correct = 0
    total = len(fields)

    print(f"\n===== {filename} =====")

    for field in fields:

        expected_value = expected.get(field)
        actual_value = actual.get(field)

        result = compare_values(
            expected_value,
            actual_value
        )

        if result:
            correct += 1
            status = "PASS"
        else:
            status = "FAIL"

        print(f"{field:20} : {status}")

        if not result:

            print(
                f"  Expected: {expected_value}"
            )

            print(
                f"  Actual:   {actual_value}"
            )

    accuracy = (correct / total) * 100

    print(
        f"\nAccuracy: {accuracy:.2f}%"
    )

    return correct, total


def main():

    with open(
        GROUND_TRUTH_FILE,
        "r",
        encoding="utf-8"
    ) as file:

        ground_truth = json.load(file)

    total_correct = 0
    total_fields = 0

    for filename, expected in ground_truth.items():

        correct, total = evaluate_resume(
            filename,
            expected
        )

        total_correct += correct
        total_fields += total

    overall_accuracy = (
        total_correct / total_fields
    ) * 100

    print("\n===================================")
    print("FINAL EXTRACTION ACCURACY")
    print("===================================")

    print(
        f"{overall_accuracy:.2f}%"
    )

    print(
        f"Correct: {total_correct}/{total_fields}"
    )

    if overall_accuracy >= 95:

        print(
            "STATUS: PASSED - Target >= 95%"
        )

    else:

        print(
            "STATUS: NEEDS IMPROVEMENT"
        )


if __name__ == "__main__":
    main()