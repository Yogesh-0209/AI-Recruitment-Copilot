import json
import os


def load_candidate_profiles():
    candidates = []

    project_root = os.path.dirname(
        os.path.dirname(
            os.path.dirname(__file__)
        )
    )

    candidate_directory = os.path.join(
        project_root,
        "data",
        "candidates"
    )

    if not os.path.exists(candidate_directory):
        return candidates

    for filename in os.listdir(candidate_directory):

        if not filename.endswith(".json"):
            continue

        filepath = os.path.join(
            candidate_directory,
            filename
        )

        try:
            with open(
                filepath,
                "r",
                encoding="utf-8"
            ) as file:

                candidate = json.load(file)

            candidates.append(candidate)

        except Exception as error:
            print(
                f"Could not load {filename}: {error}"
            )

    return candidates