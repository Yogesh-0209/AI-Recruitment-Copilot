import random
import string


# ============================================================
# CAPTCHA GENERATOR
# ============================================================

def generate_captcha(length=6):
    """
    Generate a simple CAPTCHA code.
    """

    characters = (
        string.ascii_uppercase
        + string.digits
    )

    return "".join(
        random.choice(characters)
        for _ in range(length)
    )


# ============================================================
# CAPTCHA VALIDATION
# ============================================================

def verify_captcha(
    expected,
    entered,
):
    """
    Verify CAPTCHA input.
    """

    if not expected or not entered:
        return False

    return (
        expected.strip().upper()
        ==
        entered.strip().upper()
    )