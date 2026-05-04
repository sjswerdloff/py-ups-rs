"""
Unit tests for pyupsrs.utils.dicom_utils.

Tests cover:
- VR_STRFTIME contains expected keys (DA, TM, DT)
- generate_uid returns a non-empty string that is a valid DICOM UID
- validate_uid returns True for valid UIDs and False for invalid ones
- to_dicom_date_str formats correctly for DA, TM, and DT VRs
- to_dicom_date_str falls back to DA format (%Y%m%d) for unknown VR
"""

from datetime import datetime

import pytest
from pydicom import valuerep

from pyupsrs.utils.dicom_utils import VR_STRFTIME, generate_uid, to_dicom_date_str, validate_uid

# ---------------------------------------------------------------------------
# VR_STRFTIME constant
# ---------------------------------------------------------------------------


def test_vr_strftime_contains_da_key() -> None:
    """Contract: VR_STRFTIME has an entry for the DA (date) VR."""
    assert valuerep.VR.DA in VR_STRFTIME


def test_vr_strftime_contains_tm_key() -> None:
    """Contract: VR_STRFTIME has an entry for the TM (time) VR."""
    assert valuerep.VR.TM in VR_STRFTIME


def test_vr_strftime_contains_dt_key() -> None:
    """Contract: VR_STRFTIME has an entry for the DT (datetime) VR."""
    assert valuerep.VR.DT in VR_STRFTIME


def test_vr_strftime_da_format_produces_8_digits() -> None:
    """Contract: DA format string produces an 8-digit date (YYYYMMDD)."""
    dt = datetime(2025, 3, 7, 12, 30, 45)
    formatted = dt.strftime(VR_STRFTIME[valuerep.VR.DA])
    assert formatted == "20250307"


def test_vr_strftime_tm_format_produces_hhmmss_microseconds() -> None:
    """Contract: TM format string produces HHMMSS.ffffff."""
    dt = datetime(2025, 3, 7, 12, 30, 45, 123456)
    formatted = dt.strftime(VR_STRFTIME[valuerep.VR.TM])
    assert formatted == "123045.123456"


def test_vr_strftime_dt_format_produces_combined_string() -> None:
    """Contract: DT format string produces YYYYMMDDHHmmSS.ffffff."""
    dt = datetime(2025, 3, 7, 12, 30, 45, 123456)
    formatted = dt.strftime(VR_STRFTIME[valuerep.VR.DT])
    assert formatted == "20250307123045.123456"


# ---------------------------------------------------------------------------
# generate_uid
# ---------------------------------------------------------------------------


def test_generate_uid_returns_string() -> None:
    """Contract: generate_uid returns a str instance."""
    result = generate_uid()
    assert isinstance(result, str)


def test_generate_uid_returns_non_empty_string() -> None:
    """Contract: generate_uid returns a non-empty string."""
    result = generate_uid()
    assert len(result) > 0


def test_generate_uid_returns_valid_dicom_uid() -> None:
    """Contract: the UID returned by generate_uid passes validate_uid."""
    result = generate_uid()
    assert validate_uid(result) is True


def test_generate_uid_produces_unique_values() -> None:
    """Contract: successive calls to generate_uid return different values."""
    uid1 = generate_uid()
    uid2 = generate_uid()
    assert uid1 != uid2


# ---------------------------------------------------------------------------
# validate_uid
# ---------------------------------------------------------------------------


def test_validate_uid_returns_true_for_generated_uid() -> None:
    """Contract: validate_uid returns True for a freshly generated UID."""
    valid_uid = generate_uid()
    assert validate_uid(valid_uid) is True


def test_validate_uid_returns_true_for_well_known_uid() -> None:
    """Contract: validate_uid returns True for a well-known DICOM UID."""
    # 1.2.840.10008.1.2 = Implicit VR Little Endian Transfer Syntax
    assert validate_uid("1.2.840.10008.1.2") is True


def test_validate_uid_returns_false_for_empty_string() -> None:
    """Contract: validate_uid returns False for an empty string."""
    assert validate_uid("") is False


def test_validate_uid_returns_false_for_uid_with_leading_zero_component() -> None:
    """Contract: validate_uid returns False when a component has a leading zero."""
    # Each component must not have a leading zero (except the component '0' itself)
    assert validate_uid("1.02.3") is False


def test_validate_uid_returns_false_for_uid_with_non_numeric_characters() -> None:
    """Contract: validate_uid returns False for UIDs containing letters."""
    assert validate_uid("1.2.abc.4") is False


def test_validate_uid_returns_false_for_uid_exceeding_64_chars() -> None:
    """Contract: validate_uid returns False for UIDs longer than 64 characters."""
    # Build a UID that is guaranteed to exceed 64 characters
    long_uid = "1." + ".".join(["1234567890"] * 7)  # > 64 chars
    assert len(long_uid) > 64
    assert validate_uid(long_uid) is False


# ---------------------------------------------------------------------------
# to_dicom_date_str
# ---------------------------------------------------------------------------

_REFERENCE_DT = datetime(2024, 11, 5, 8, 3, 7, 654321)


def test_to_dicom_date_str_da_format() -> None:
    """Contract: to_dicom_date_str with VR.DA returns YYYYMMDD."""
    result = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.DA)
    assert result == "20241105"


def test_to_dicom_date_str_tm_format() -> None:
    """Contract: to_dicom_date_str with VR.TM returns HHMMSS.ffffff."""
    result = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.TM)
    assert result == "080307.654321"


def test_to_dicom_date_str_dt_format() -> None:
    """Contract: to_dicom_date_str with VR.DT returns YYYYMMDDHHmmSS.ffffff."""
    result = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.DT)
    assert result == "20241105080307.654321"


def test_to_dicom_date_str_default_vr_is_da() -> None:
    """Contract: to_dicom_date_str with no VR argument defaults to DA format."""
    result_default = to_dicom_date_str(_REFERENCE_DT)
    result_explicit_da = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.DA)
    assert result_default == result_explicit_da


def test_to_dicom_date_str_fallback_for_unknown_vr() -> None:
    """Contract: to_dicom_date_str falls back to DA format for an unknown VR."""
    # Use a VR that is not in VR_STRFTIME (e.g., LO — long string)
    unknown_vr = valuerep.VR.LO
    assert unknown_vr not in VR_STRFTIME

    result = to_dicom_date_str(_REFERENCE_DT, unknown_vr)
    # Fallback is the DA format string "%Y%m%d"
    assert result == "20241105"


def test_to_dicom_date_str_returns_string() -> None:
    """Contract: to_dicom_date_str always returns a str."""
    for vr in (valuerep.VR.DA, valuerep.VR.TM, valuerep.VR.DT):
        result = to_dicom_date_str(_REFERENCE_DT, vr)
        assert isinstance(result, str)


def test_to_dicom_date_str_da_length_is_eight() -> None:
    """Contract: DA output is exactly 8 characters."""
    result = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.DA)
    assert len(result) == 8


def test_to_dicom_date_str_dt_length_is_21() -> None:
    """Contract: DT output is exactly 21 characters (YYYYMMDDHHmmSS.ffffff)."""
    result = to_dicom_date_str(_REFERENCE_DT, valuerep.VR.DT)
    assert len(result) == 21


@pytest.mark.parametrize(
    ("dt", "vr", "expected"),
    [
        (datetime(2000, 1, 1, 0, 0, 0, 0), valuerep.VR.DA, "20000101"),
        (datetime(1999, 12, 31, 23, 59, 59, 999999), valuerep.VR.DA, "19991231"),
        (datetime(2000, 1, 1, 0, 0, 0, 0), valuerep.VR.TM, "000000.000000"),
        (datetime(1999, 12, 31, 23, 59, 59, 999999), valuerep.VR.TM, "235959.999999"),
        (datetime(2000, 1, 1, 0, 0, 0, 0), valuerep.VR.DT, "20000101000000.000000"),
        (datetime(1999, 12, 31, 23, 59, 59, 999999), valuerep.VR.DT, "19991231235959.999999"),
    ],
)
def test_to_dicom_date_str_parametrized_boundary_values(dt: datetime, vr: valuerep.VR, expected: str) -> None:
    """Contract: to_dicom_date_str produces correct output at date/time boundaries."""
    assert to_dicom_date_str(dt, vr) == expected
