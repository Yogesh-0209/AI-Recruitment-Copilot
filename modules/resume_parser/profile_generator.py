import pandas as pd
import json


def generate_profile(candidate):
    """
    Convert candidate dictionary into a Pandas DataFrame.
    """

    profile = pd.DataFrame([candidate])

    return profile


def save_profile_json(candidate, output_path):
    """
    Save candidate profile as JSON.
    """

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(candidate, file, indent=4)

    return output_path