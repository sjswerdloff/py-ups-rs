"""Utility functions for working with DICOM data."""

from datetime import datetime

from pydicom import uid, valuerep

VR_STRFTIME = {valuerep.VR.DA: "%Y%m%d", valuerep.VR.TM: "%H%M%S.%f", valuerep.VR.DT: "%Y%m%d%H%M%S.%f"}


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


def to_dicom_date_str(date: datetime, vr: valuerep.VR = valuerep.VR.DA) -> str:
    """
    Convert a python datetime to the string representation for one of the date/time VRs.

    Args:
        date (datetime): the python datetime value.
        vr (valuerep.VR, optional): The VR desired DA|TM|DT. Defaults to valuerep.VR.DA.

    Returns:
        str: The string representation for the specified date/time VR.

    """
    return date.strftime(VR_STRFTIME.get(vr, default=valuerep.VR.DA))
