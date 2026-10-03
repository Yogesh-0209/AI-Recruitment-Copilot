import json
import os

from modules.resume_parser.file_loader import extract_text
from modules.resume_parser.extractor import extract_candidate_info
from modules.resume_parser.section_parser import extract_sections


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

RESUME_FOLDER = os.path.join(
    BASE_DIR,
    "data",
    "resumes"
)

GROUND_TRUTH_FILE = os.path.join(
    BASE_DIR,
    "data",
    "ground_truth",
    "expected_profiles.json"
)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize(value):
    """
    Normalize text for comparison.
    """

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


def normalize_list(values):
    """
    Normalize a list of values.
    """

    if not values:
        return set()

    return {
        normalize(item)
        for item in values
        if normalize(item)
    }


# ============================================================
# FIELD COMPARISON
# ============================================================

def compare_field(expected, actual):
    """
    Compare one field.

    Returns:
        score      -> value between 0 and 1
        matched    -> number of matched items
        expected_n -> total expected items
    """

    # --------------------------------------------------------
    # LIST FIELD
    # --------------------------------------------------------

    if isinstance(expected, list):

        expected_set = normalize_list(expected)
        actual_set = normalize_list(actual)

        if not expected_set:
            return 1.0, 0, 0

        matched = len(
            expected_set.intersection(actual_set)
        )

        score = matched / len(expected_set)

        return score, matched, len(expected_set)


    # --------------------------------------------------------
    # SINGLE VALUE
    # --------------------------------------------------------

    expected_value = normalize(expected)
    actual_value = normalize(actual)

    if expected_value == "":
        return 1.0, 0, 0

    if expected_value == actual_value:
        return 1.0, 1, 1

    return 0.0, 0, 1


# ============================================================
# EVALUATE ONE RESUME
# ============================================================

def evaluate_resume(filename, expected):

    file_path = os.path.join(
        RESUME_FOLDER,
        filename
    )

    if not os.path.exists(file_path):

        print(
            f"\nWARNING: Resume not found: {file_path}"
        )

        return 0, 0, 0


    # --------------------------------------------------------
    # EXTRACT TEXT
    # --------------------------------------------------------

    text = extract_text(file_path)


    # --------------------------------------------------------
    # BASIC EXTRACTION
    # --------------------------------------------------------

    actual = extract_candidate_info(text)


    # --------------------------------------------------------
    # SECTION EXTRACTION
    # --------------------------------------------------------

    try:

        sections = extract_sections(text)

    except Exception as error:

        print(
            f"Section extraction error: {error}"
        )

        sections = {}


    # --------------------------------------------------------
    # COMBINE SECTION DATA
    # --------------------------------------------------------

    if isinstance(sections, dict):

        if sections.get("education"):
            actual["education"] = sections["education"]

        if sections.get("experience"):
            actual["experience"] = sections["experience"]

        if sections.get("certifications"):
            actual["certifications"] = sections["certifications"]

        if sections.get("projects"):
            actual["projects"] = sections["projects"]


    # --------------------------------------------------------
    # FIELDS
    # --------------------------------------------------------

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


    total_score = 0.0

    print("\n")
    print("=" * 60)
    print(filename)
    print("=" * 60)


    # --------------------------------------------------------
    # FIELD-BY-FIELD EVALUATION
    # --------------------------------------------------------

    for field in fields:

        expected_value = expected.get(field)
        actual_value = actual.get(field)


        score, matched, expected_count = compare_field(
            expected_value,
            actual_value
        )


        percentage = score * 100

        total_score += score


        if percentage == 100:

            status = "PASS"

        elif percentage > 0:

            status = "PARTIAL"

        else:

            status = "FAIL"


        print(
            f"{field:20} : "
            f"{status:8} "
            f"{percentage:6.2f}%"
        )


        # Show details for list fields

        if isinstance(expected_value, list):

            print(
                f"  Matched: "
                f"{matched}/{expected_count}"
            )

            if percentage < 100:

                expected_set = normalize_list(
                    expected_value
                )

                actual_set = normalize_list(
                    actual_value
                )

                missing = expected_set - actual_set

                if missing:

                    print(
                        f"  Missing: {sorted(missing)}"
                    )


        elif percentage < 100:

            print(
                f"  Expected: {expected_value}"
            )

            print(
                f"  Actual:   {actual_value}"
            )


    # --------------------------------------------------------
    # RESUME ACCURACY
    # --------------------------------------------------------

    accuracy = (
        total_score / len(fields)
    ) * 100


    print("-" * 60)

    print(
        f"Resume Accuracy: {accuracy:.2f}%"
    )


    return (
        total_score,
        len(fields),
        accuracy
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("\n")
    print("=" * 60)
    print("AI RECRUITMENT COPILOT")
    print("RESUME EXTRACTION ACCURACY EVALUATION")
    print("=" * 60)


    # --------------------------------------------------------
    # LOAD GROUND TRUTH
    # --------------------------------------------------------

    try:

        with open(
            GROUND_TRUTH_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            ground_truth = json.load(file)

    except FileNotFoundError:

        print(
            "\nERROR: expected_profiles.json not found."
        )

        print(
            f"Expected location:\n{GROUND_TRUTH_FILE}"
        )

        return

    except json.JSONDecodeError as error:

        print(
            "\nERROR: Invalid JSON file."
        )

        print(error)

        return


    # --------------------------------------------------------
    # GLOBAL TOTALS
    # --------------------------------------------------------

    total_score = 0.0
    total_fields = 0

    processed = 0
    missing_files = 0


    # --------------------------------------------------------
    # EVALUATE EVERY RESUME
    # --------------------------------------------------------

    for filename, expected in ground_truth.items():

        score, fields, accuracy = evaluate_resume(
            filename,
            expected
        )

        if fields == 0:

            missing_files += 1

            continue


        total_score += score
        total_fields += fields

        processed += 1


    # --------------------------------------------------------
    # OVERALL ACCURACY
    # --------------------------------------------------------

    if total_fields == 0:

        print(
            "\nNo resumes were successfully evaluated."
        )

        return


    overall_accuracy = (
        total_score / total_fields
    ) * 100


    # --------------------------------------------------------
    # FINAL REPORT
    # --------------------------------------------------------

    print("\n")
    print("=" * 60)
    print("FINAL EXTRACTION ACCURACY")
    print("=" * 60)


    print(
        f"Resumes evaluated : {processed}"
    )

    print(
        f"Missing resumes   : {missing_files}"
    )

    print(
        f"Overall accuracy  : {overall_accuracy:.2f}%"
    )


    print("=" * 60)


    # --------------------------------------------------------
    # MILESTONE STATUS
    # --------------------------------------------------------

    if overall_accuracy >= 95:

        print(
            "STATUS: PASSED"
        )

        print(
            "Target: >= 95%"
        )

    else:

        print(
            "STATUS: NEEDS IMPROVEMENT"
        )

        print(
            "Target: >= 95%"
        )


    print("=" * 60)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()