"""Utility functions for working with DICOM data."""

from pydicom import uid


def generate_uid() -> str:
    """
    Generate a DICOM UID.

    Returns:
        A valid DICOM UID.

    """
    return uid.generate_uid()


def validate_uid(uid: str) -> bool:
    """
    Validate a DICOM UID.

    Args:
        uid: The UID to validate.

    Returns:
        True if valid, False otherwise.

    """
    return uid.UID(uid).is_valid
