"""
Unit tests for the DICOM query matching engine (dicom_query_matcher module).

Tests cover:
- Basic exact matching on PatientID, PatientName
- Wildcard matching with * prefix/suffix
- Date range matching (YYYYMMDD-YYYYMMDD format)
- Empty query returning all datasets
- No match returning empty list
- Multi-value queries
- Date/time parsing (parse_dicom_date)
- Sequence matching
- Case-sensitive vs case-insensitive matching per VR
- TM format with and without microseconds
- DT format truncation and padding
- UID matching (UI VR)
- Person name component matching (PN VR)
- is_code_sequence detection
- match_code_sequence default and UPS-specific paths
- match_scheduled_station_name and match_scheduled_workitem_code
- match_query_to_dataset: meta-group skipping, regular SQ matching, direct comparison
- example_ups_query smoke test

Known issues / xfail markers:
- match_datetime uses '-' to detect range, so negative timezone offsets in date
  strings may be misinterpreted as ranges. Tests that exercise this are marked
  xfail if the behaviour is incorrect.
"""

from datetime import datetime

import pydicom
from pydicom import Dataset

from pyupsrs.utils.dicom_query_matcher import (
    example_ups_query,
    is_code_sequence,
    match_code_sequence,
    match_datetime,
    match_query_to_dataset,
    match_scheduled_station_name,
    match_scheduled_workitem_code,
    match_ups_specific_attributes,
    parse_dicom_date,
    query_datasets,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_patient_dataset(patient_id: str, patient_name: str) -> Dataset:
    """
    Build a minimal pydicom Dataset with PatientID and PatientName.

    Args:
        patient_id: Value for the PatientID (0010,0020) attribute.
        patient_name: Value for the PatientName (0010,0010) attribute.

    Returns:
        A pydicom Dataset containing only PatientID and PatientName.

    """
    ds = Dataset()
    ds.PatientID = patient_id
    ds.PatientName = patient_name
    return ds


def make_date_dataset(date_str: str) -> Dataset:
    """
    Build a pydicom Dataset that carries a StudyDate DA attribute.

    Args:
        date_str: DICOM DA-formatted date string (e.g. ``"20230601"``).

    Returns:
        A pydicom Dataset containing only StudyDate.

    """
    ds = Dataset()
    ds.StudyDate = date_str
    return ds


def make_datetime_dataset(datetime_str: str) -> Dataset:
    """
    Build a pydicom Dataset that carries a ScheduledProcedureStepStartDateTime DT attribute.

    Args:
        datetime_str: DICOM DT-formatted datetime string (e.g. ``"20230601120000"``).

    Returns:
        A pydicom Dataset containing only ScheduledProcedureStepStartDateTime.

    """
    ds = Dataset()
    ds.ScheduledProcedureStepStartDateTime = datetime_str
    return ds


# ---------------------------------------------------------------------------
# Tests for parse_dicom_date
# ---------------------------------------------------------------------------


class TestParseDicomDate:
    """
    Contract: parse_dicom_date converts DICOM date/time strings into datetime objects.

    None is returned for empty strings, ``"*"`` wildcards, and unparseable values.
    """

    def test_da_format_parses_correctly(self) -> None:
        """
        Verify that an 8-digit DA string parses to the expected date.

        A date of ``"20230601"`` should yield year=2023, month=6, day=1.
        """
        result = parse_dicom_date("20230601")
        assert result is not None
        assert result.year == 2023
        assert result.month == 6
        assert result.day == 1

    def test_dt_format_with_time_parses_correctly(self) -> None:
        """
        Verify that a 14-digit DT string parses to the expected date and time.

        ``"20230601120000"`` should yield year=2023, month=6, day=1, hour=12.
        """
        result = parse_dicom_date("20230601120000")
        assert result is not None
        assert result.year == 2023
        assert result.month == 6
        assert result.day == 1
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0

    def test_dt_format_with_microseconds_parses_correctly(self) -> None:
        """
        Verify that a DT string with fractional seconds parses microseconds correctly.

        ``"20230601120000.123456"`` should yield microsecond=123456.
        """
        result = parse_dicom_date("20230601120000.123456")
        assert result is not None
        assert result.microsecond == 123456

    def test_empty_string_returns_none(self) -> None:
        """Verify that an empty string returns None."""
        result = parse_dicom_date("")
        assert result is None

    def test_wildcard_star_returns_none(self) -> None:
        """Verify that the universal-match wildcard ``"*"`` returns None."""
        result = parse_dicom_date("*")
        assert result is None

    def test_unparseable_string_returns_none(self) -> None:
        """Verify that a clearly invalid string returns None instead of raising."""
        result = parse_dicom_date("not-a-date")
        assert result is None

    def test_tm_format_hhmmss_parses_to_epoch_date(self) -> None:
        """
        Verify that a 6-digit TM string is parsed with a base date of 1900-01-01.

        DICOM TM strings carry only time information; the implementation anchors
        them to January 1 1900 for comparison purposes.
        """
        result = parse_dicom_date("120000")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0


# ---------------------------------------------------------------------------
# Tests for match_datetime
# ---------------------------------------------------------------------------


class TestMatchDatetime:
    """
    Contract: match_datetime evaluates DICOM date/time query values against dataset values.

    Supports empty/wildcard (universal match), range syntax (``start-end``),
    wildcard patterns (``*``, ``?``), and exact comparison.
    """

    def test_empty_query_matches_any_date(self) -> None:
        """Verify that an empty query string is a universal match."""
        assert match_datetime("", "20230601") is True

    def test_star_wildcard_matches_any_date(self) -> None:
        """Verify that ``"*"`` alone is a universal match."""
        assert match_datetime("*", "20230601") is True

    def test_exact_date_matches(self) -> None:
        """Verify that an exact DA string matches the same dataset value."""
        assert match_datetime("20230601", "20230601") is True

    def test_exact_date_nonmatch(self) -> None:
        """Verify that a different exact DA string does not match."""
        assert match_datetime("20230601", "20230602") is False

    def test_range_date_start_and_end_within(self) -> None:
        """Verify that a date within the range [start, end] matches."""
        assert match_datetime("20230101-20231231", "20230601") is True

    def test_range_date_before_start_does_not_match(self) -> None:
        """Verify that a date before the range start does not match."""
        assert match_datetime("20230101-20231231", "20221231") is False

    def test_range_date_after_end_does_not_match(self) -> None:
        """Verify that a date after the range end does not match."""
        assert match_datetime("20230101-20231231", "20240101") is False

    def test_range_date_on_start_boundary_matches(self) -> None:
        """Verify that a date exactly on the start boundary matches (inclusive)."""
        assert match_datetime("20230101-20231231", "20230101") is True

    def test_range_date_on_end_boundary_matches(self) -> None:
        """Verify that a date exactly on the end boundary matches (inclusive)."""
        assert match_datetime("20230101-20231231", "20231231") is True

    def test_open_ended_range_start_only(self) -> None:
        """Verify that a range with only a start date (``"start-"``) matches any later date."""
        assert match_datetime("20230101-", "20240101") is True

    def test_open_ended_range_start_only_rejects_earlier(self) -> None:
        """Verify that a range with only a start date rejects a date before that start."""
        assert match_datetime("20230601-", "20230101") is False

    def test_open_ended_range_end_only(self) -> None:
        """Verify that a range with only an end date (``"-end"``) matches any earlier date."""
        assert match_datetime("-20231231", "20230601") is True

    def test_open_ended_range_end_only_rejects_later(self) -> None:
        """Verify that a range with only an end date rejects a date after that end."""
        assert match_datetime("-20231231", "20240101") is False

    def test_wildcard_suffix_matches_prefix(self) -> None:
        """Verify that a suffix wildcard (``"2023*"``) matches any date starting with ``"2023"``."""
        assert match_datetime("2023*", "20230601") is True

    def test_wildcard_suffix_does_not_match_wrong_prefix(self) -> None:
        """Verify that a suffix wildcard does not match a date with a different prefix."""
        assert match_datetime("2023*", "20240101") is False

    def test_wildcard_question_mark_matches_single_char(self) -> None:
        """Verify that ``"?"`` matches exactly one character in the string."""
        assert match_datetime("2023060?", "20230601") is True

    def test_wildcard_question_mark_does_not_match_two_chars(self) -> None:
        """Verify that a single ``"?"`` does not match more than one character."""
        assert match_datetime("202306?", "20230601") is False


# ---------------------------------------------------------------------------
# Tests for query_datasets — empty query
# ---------------------------------------------------------------------------


class TestQueryDatasetsEmptyQuery:
    """
    Contract: an empty query (no attributes set) matches every dataset in the list.

    DICOM QIDO-RS specifies that an empty query is a universal match.
    """

    def test_empty_query_returns_all_datasets(self) -> None:
        """Verify that an empty query returns all provided datasets unchanged."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
            make_patient_dataset("P003", "Jones^Alice"),
        ]
        query = Dataset()
        result = query_datasets(query, datasets)
        assert len(result) == 3

    def test_empty_query_on_empty_list_returns_empty(self) -> None:
        """Verify that an empty query against an empty list returns an empty list."""
        query = Dataset()
        result = query_datasets(query, [])
        assert result == []


# ---------------------------------------------------------------------------
# Tests for query_datasets — exact matching
# ---------------------------------------------------------------------------


class TestQueryDatasetsExactMatch:
    """Contract: exact attribute values in the query must match dataset attributes precisely."""

    def test_exact_patient_id_match(self) -> None:
        """Verify that a query with an exact PatientID returns only matching datasets."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientID = "P001"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].PatientID == "P001"

    def test_exact_patient_id_no_match(self) -> None:
        """Verify that a query with a non-existent PatientID returns an empty list."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientID = "UNKNOWN"
        result = query_datasets(query, datasets)
        assert result == []

    def test_exact_patient_name_match(self) -> None:
        """Verify that a query with an exact PatientName returns only the matching dataset."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientName = "Doe^John"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert str(result[0].PatientName) == "Doe^John"

    def test_multi_attribute_exact_match(self) -> None:
        """Verify that a query with both PatientID and PatientName narrows results correctly."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P001", "Doe^Jane"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientID = "P001"
        query.PatientName = "Doe^John"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].PatientID == "P001"
        assert str(result[0].PatientName) == "Doe^John"

    def test_missing_attribute_in_dataset_is_no_match(self) -> None:
        """Verify that a query attribute absent from a dataset causes a non-match."""
        ds = Dataset()
        ds.PatientID = "P001"
        # PatientName intentionally omitted from dataset
        query = Dataset()
        query.PatientName = "Doe^John"
        result = query_datasets(query, [ds])
        assert result == []


# ---------------------------------------------------------------------------
# Tests for query_datasets — wildcard matching
# ---------------------------------------------------------------------------


class TestQueryDatasetsWildcardMatch:
    """Contract: wildcard characters ``*`` and ``?`` are applied per DICOM matching rules."""

    def test_suffix_wildcard_on_patient_id(self) -> None:
        """
        Verify that a PatientID query of ``"P00*"`` matches all IDs starting with ``"P00"``.

        All three sample IDs (P001, P002, P003) should be returned.
        """
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
            make_patient_dataset("P003", "Jones^Alice"),
            make_patient_dataset("X999", "Other^Person"),
        ]
        query = Dataset()
        query.PatientID = "P00*"
        result = query_datasets(query, datasets)
        assert len(result) == 3
        returned_ids = {ds.PatientID for ds in result}
        assert returned_ids == {"P001", "P002", "P003"}

    def test_prefix_wildcard_on_patient_name(self) -> None:
        """
        Verify that a PatientName query of ``"*Jane"`` matches names ending in ``"Jane"``.

        Only ``"Smith^Jane"`` should be returned.
        """
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientName = "*Jane"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert str(result[0].PatientName) == "Smith^Jane"

    def test_star_alone_on_patient_id_matches_all(self) -> None:
        """Verify that a PatientID query of ``"*"`` returns all datasets."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientID = "*"
        result = query_datasets(query, datasets)
        assert len(result) == 2

    def test_question_mark_wildcard_on_patient_id(self) -> None:
        """
        Verify that ``"?001"`` matches ``"P001"`` but not ``"PP001"``.

        A single ``"?"`` replaces exactly one character.
        """
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("PP001", "Doe^Jane"),
        ]
        query = Dataset()
        query.PatientID = "?001"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].PatientID == "P001"

    def test_wildcard_no_match_returns_empty(self) -> None:
        """Verify that a wildcard pattern that matches nothing returns an empty list."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
        ]
        query = Dataset()
        query.PatientID = "X*"
        result = query_datasets(query, datasets)
        assert result == []


# ---------------------------------------------------------------------------
# Tests for query_datasets — date matching via DA VR
# ---------------------------------------------------------------------------


class TestQueryDatasetsDateMatch:
    """Contract: DA (Date) attributes are matched using DICOM date comparison rules."""

    def test_exact_date_match(self) -> None:
        """Verify that an exact StudyDate query matches datasets with that date."""
        datasets = [
            make_date_dataset("20230601"),
            make_date_dataset("20230602"),
        ]
        query = Dataset()
        query.StudyDate = "20230601"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].StudyDate == "20230601"

    def test_date_range_match(self) -> None:
        """Verify that a date range query returns datasets within the range."""
        datasets = [
            make_date_dataset("20220101"),  # before range
            make_date_dataset("20230601"),  # within range
            make_date_dataset("20230615"),  # within range
            make_date_dataset("20240101"),  # after range
        ]
        query = Dataset()
        query.StudyDate = "20230101-20231231"
        result = query_datasets(query, datasets)
        assert len(result) == 2
        dates = {ds.StudyDate for ds in result}
        assert dates == {"20230601", "20230615"}

    def test_date_wildcard_year_match(self) -> None:
        """Verify that a year-level wildcard ``"2023*"`` matches any 2023 date."""
        datasets = [
            make_date_dataset("20230601"),
            make_date_dataset("20231201"),
            make_date_dataset("20240101"),
        ]
        query = Dataset()
        query.StudyDate = "2023*"
        result = query_datasets(query, datasets)
        assert len(result) == 2

    def test_empty_date_query_matches_all(self) -> None:
        """Verify that an empty StudyDate query matches all datasets."""
        datasets = [
            make_date_dataset("20230601"),
            make_date_dataset("20230602"),
        ]
        query = Dataset()
        query.StudyDate = ""
        result = query_datasets(query, datasets)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests for query_datasets — scheduled procedure step date/time (DT, tag 0x00404005)
# ---------------------------------------------------------------------------


class TestQueryDatasetsScheduledDateTime:
    """
    Contract: tag (0040,4005) ScheduledProcedureStepStartDateTime uses DT VR matching.

    This tag receives special handling through ``match_ups_specific_attributes``.
    """

    def test_exact_datetime_match(self) -> None:
        """Verify exact DT value match for ScheduledProcedureStepStartDateTime."""
        datasets = [
            make_datetime_dataset("20230601120000"),
            make_datetime_dataset("20230601130000"),
        ]
        query = Dataset()
        query.ScheduledProcedureStepStartDateTime = "20230601120000"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].ScheduledProcedureStepStartDateTime == "20230601120000"

    def test_datetime_range_match(self) -> None:
        """Verify that a DT range query returns datasets within the range."""
        datasets = [
            make_datetime_dataset("20221231235959"),  # before range
            make_datetime_dataset("20230601120000"),  # within range
            make_datetime_dataset("20231201000000"),  # within range
            make_datetime_dataset("20240101000000"),  # after range
        ]
        query = Dataset()
        query.ScheduledProcedureStepStartDateTime = "20230101000000-20231231235959"
        result = query_datasets(query, datasets)
        assert len(result) == 2

    def test_empty_datetime_query_matches_all(self) -> None:
        """Verify that an empty DT query is a universal match."""
        datasets = [
            make_datetime_dataset("20230601120000"),
            make_datetime_dataset("20230602090000"),
        ]
        query = Dataset()
        query.ScheduledProcedureStepStartDateTime = ""
        result = query_datasets(query, datasets)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Tests for query_datasets — multi-value / multiple datasets
# ---------------------------------------------------------------------------


class TestQueryDatasetsMultiValue:
    """Contract: multiple datasets are evaluated independently; all matching ones are returned."""

    def test_multiple_matching_datasets_returned(self) -> None:
        """Verify that all datasets matching a query are included in the result."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P001", "Doe^Jane"),
            make_patient_dataset("P002", "Smith^Bob"),
        ]
        query = Dataset()
        query.PatientID = "P001"
        result = query_datasets(query, datasets)
        assert len(result) == 2

    def test_no_datasets_match_returns_empty(self) -> None:
        """Verify that when nothing matches the result is an empty list."""
        datasets = [
            make_patient_dataset("P001", "Doe^John"),
            make_patient_dataset("P002", "Smith^Jane"),
        ]
        query = Dataset()
        query.PatientID = "ZZZZ"
        result = query_datasets(query, datasets)
        assert result == []

    def test_single_dataset_single_match(self) -> None:
        """Verify that a single-element list returns at most one result."""
        datasets = [make_patient_dataset("P001", "Doe^John")]
        query = Dataset()
        query.PatientID = "P001"
        result = query_datasets(query, datasets)
        assert len(result) == 1

    def test_query_with_multiple_attributes_all_must_match(self) -> None:
        """
        Verify that a query with N attributes acts as a logical AND.

        A dataset must match every query attribute to appear in the results.
        """
        datasets = [
            make_patient_dataset("P001", "Doe^John"),  # matches both
            make_patient_dataset("P001", "Smith^Jane"),  # matches PatientID only
            make_patient_dataset("P002", "Doe^John"),  # matches PatientName only
        ]
        query = Dataset()
        query.PatientID = "P001"
        query.PatientName = "Doe^John"
        result = query_datasets(query, datasets)
        assert len(result) == 1
        assert result[0].PatientID == "P001"
        assert str(result[0].PatientName) == "Doe^John"


# ---------------------------------------------------------------------------
# Tests for query_datasets — sequence matching
# ---------------------------------------------------------------------------


class TestQueryDatasetsSequenceMatch:
    """
    Contract: SQ (sequence) attributes support empty-query universal match and item matching.

    An empty query sequence matches any dataset sequence.
    A non-empty query sequence must match at least one dataset sequence item.
    """

    def _make_code_sequence_dataset(self, code_value: str, scheme: str, meaning: str) -> Dataset:
        """
        Build a dataset containing a ScheduledStationNameCodeSequence.

        Args:
            code_value: The code value for the sequence item.
            scheme: The coding scheme designator.
            meaning: The code meaning text.

        Returns:
            A Dataset with a ScheduledStationNameCodeSequence containing one item.

        """
        item = Dataset()
        item.CodeValue = code_value
        item.CodingSchemeDesignator = scheme
        item.CodeMeaning = meaning

        ds = Dataset()
        ds.ScheduledStationNameCodeSequence = [item]
        return ds

    def test_empty_sequence_query_matches_any(self) -> None:
        """Verify that an empty sequence in the query is a universal match for that attribute."""
        ds = self._make_code_sequence_dataset("STATION1", "99CLINIC", "Station One")
        query = Dataset()
        query.ScheduledStationNameCodeSequence = []
        result = query_datasets(query, [ds])
        assert len(result) == 1

    def test_matching_code_value_in_sequence(self) -> None:
        """Verify that matching CodeValue and CodingSchemeDesignator in a sequence returns the dataset."""
        ds = self._make_code_sequence_dataset("STATION1", "99CLINIC", "Station One")

        query_item = Dataset()
        query_item.CodeValue = "STATION1"
        query_item.CodingSchemeDesignator = "99CLINIC"
        query_item.CodeMeaning = "Station One"

        query = Dataset()
        query.ScheduledStationNameCodeSequence = [query_item]
        result = query_datasets(query, [ds])
        assert len(result) == 1

    def test_non_matching_code_value_in_sequence(self) -> None:
        """Verify that a mismatched CodeValue in a sequence query yields no results."""
        ds = self._make_code_sequence_dataset("STATION1", "99CLINIC", "Station One")

        query_item = Dataset()
        query_item.CodeValue = "STATION2"
        query_item.CodingSchemeDesignator = "99CLINIC"
        query_item.CodeMeaning = "Station Two"

        query = Dataset()
        query.ScheduledStationNameCodeSequence = [query_item]
        result = query_datasets(query, [ds])
        assert result == []


# ---------------------------------------------------------------------------
# Tests for parse_dicom_date return type contract
# ---------------------------------------------------------------------------


class TestParseDicomDateReturnType:
    """Contract: parse_dicom_date always returns a datetime or None — never raises."""

    def test_returns_datetime_for_valid_da(self) -> None:
        """Verify the return type is datetime for a valid DA string."""
        result = parse_dicom_date("20230101")
        assert isinstance(result, datetime)

    def test_returns_none_for_empty_string(self) -> None:
        """Verify the return type is None for an empty string."""
        result = parse_dicom_date("")
        assert result is None

    def test_does_not_raise_for_garbage_input(self) -> None:
        """Verify that arbitrary garbage input does not raise an exception."""
        result = parse_dicom_date("garbage!@#$")
        assert result is None

    def test_returns_none_for_star(self) -> None:
        """Verify the return type is None for the universal wildcard."""
        result = parse_dicom_date("*")
        assert result is None


# ---------------------------------------------------------------------------
# Additional tests for parse_dicom_date — TM and DT edge paths
# ---------------------------------------------------------------------------


class TestMatchDatetimeRangeBranchEdgeCases:
    """
    Contract: match_datetime range parsing handles degenerate range strings correctly.

    A range string with more than one '-' separator does not split into exactly 2 parts
    and falls through to direct datetime comparison. A range with both start and end
    unparseable also falls through to direct comparison.
    """

    def test_range_with_extra_dash_falls_through_to_direct_comparison(self) -> None:
        """
        Verify that a query string with more than two '-'-separated parts falls through.

        ``"20230101-20231231-extra"`` splits into 3 parts, so the range block
        (which requires exactly 2 parts) is skipped. The function then falls through
        to direct datetime comparison between the full query string and dataset string.
        Both strings are unparseable as valid datetime values, so string equality is used.
        """
        # The query string itself won't parse as a valid datetime, and neither part will
        # equal the dataset value, so the result is False.
        result = match_datetime("20230101-20231231-extra", "20230601")
        assert result is False

    def test_range_with_both_sides_unparseable_falls_through(self) -> None:
        """
        Verify that a range where both sides are empty strings falls through to string comparison.

        ``"-"`` splits into ``["", ""]``; both parse to None (empty string → None).
        With start_date=None and end_date=None, all three elif branches are False,
        falling through to the direct comparison block.
        Since ``"-"`` != ``"20230601"`` as strings, the result is False.
        """
        result = match_datetime("-", "20230601")
        assert result is False


class TestParseDicomDateTmAndDtEdgePaths:
    """
    Contract: parse_dicom_date correctly handles TM (time) and DT edge cases.

    TM values shorter than 6 characters are padded; fractional seconds are parsed.
    DT values longer than 14 characters are truncated before parsing.
    """

    def test_tm_format_with_microseconds_parses_correctly(self) -> None:
        """
        Verify that a TM string with a decimal point parses microseconds.

        ``"120000.123456"`` should yield hour=12 and microsecond=123456.
        The implementation anchors TM to 1900-01-01 for comparison.
        """
        result = parse_dicom_date("120000.123456")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0
        assert result.microsecond == 123456

    def test_tm_format_with_short_microseconds_is_zero_padded(self) -> None:
        """
        Verify that a TM string with fractional seconds shorter than 6 digits is zero-padded on the right.

        ``"12.123"`` (length 6, <= 16, contains ".") exercises the TM-with-microseconds branch.
        ``parts[1]="123"`` padded to 6 digits gives microsecond=123000.
        The time part ``"12"`` is padded to ``"120000"`` (HHMMSS).
        """
        result = parse_dicom_date("12.123")
        assert result is not None
        assert result.microsecond == 123000

    def test_tm_format_hhmm_no_seconds_parses_correctly(self) -> None:
        """
        Verify that a 4-digit TM string (HHMM) is padded to HHMMSS before parsing.

        ``"1230"`` should yield hour=12, minute=30, second=0.
        """
        result = parse_dicom_date("1230")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 30
        assert result.second == 0

    def test_tm_format_hh_only_parses_correctly(self) -> None:
        """
        Verify that a 2-digit TM string (HH) is padded to HHMMSS before parsing.

        ``"12"`` should yield hour=12, minute=0, second=0.
        """
        result = parse_dicom_date("12")
        assert result is not None
        assert result.hour == 12
        assert result.minute == 0
        assert result.second == 0

    def test_dt_format_padded_to_14_digits(self) -> None:
        """
        Verify that a DT string shorter than 14 digits is left-padded with zeros.

        ``"2023060112"`` (10 chars) should parse correctly to 2023-06-01 12:00:00.
        """
        result = parse_dicom_date("2023060112")
        assert result is not None
        assert result.year == 2023
        assert result.month == 6
        assert result.day == 1
        assert result.hour == 12

    def test_dt_format_with_microseconds_parses_correctly(self) -> None:
        """
        Verify a full DT string with microseconds parses both datetime and microsecond.

        ``"20230601120000.123456"`` should yield year=2023 and microsecond=123456.
        """
        result = parse_dicom_date("20230601120000.123456")
        assert result is not None
        assert result.year == 2023
        assert result.microsecond == 123456

    def test_dt_format_without_microseconds_parses_correctly(self) -> None:
        """
        Verify that a 14-char DT string without fractional seconds parses to second precision.

        ``"20230601120000"`` should yield year=2023, minute=0, second=0.
        """
        result = parse_dicom_date("20230601120000")
        assert result is not None
        assert result.year == 2023
        assert result.second == 0
        assert result.microsecond == 0

    def test_tm_fractional_time_part_longer_than_6_is_truncated(self) -> None:
        """
        Verify that when the time portion in a TM string is longer than 6 chars, it is truncated.

        ``"1200001.5"`` has parts[0]="1200001" (7 chars); after ``ljust(6)`` it stays 7
        chars (ljust only pads, never truncates), so the ``if len(time_part) > 6`` branch
        on line 43 truncates it to ``"120000"``.  The result should be hour=12.
        """
        result = parse_dicom_date("1200001.5")
        assert result is not None
        assert result.hour == 12

    def test_dt_format_datetime_part_longer_than_14_is_truncated(self) -> None:
        """
        Verify that when the non-fractional DT portion exceeds 14 chars it is truncated.

        ``"202306011200001"`` has 15 chars (no dot), falling into the DT branch.
        After ``ljust(14)`` it remains 15 chars, so the ``if len(datetime_part) > 14``
        branch on line 64 truncates it to ``"20230601120000"``.
        The result should be year=2023, hour=12.
        """
        result = parse_dicom_date("202306011200001")
        assert result is not None
        assert result.year == 2023
        assert result.hour == 12


# ---------------------------------------------------------------------------
# Tests for match_datetime — unparseable dataset value
# ---------------------------------------------------------------------------


class TestMatchDatetimeUnparseableDatasetValue:
    """
    Contract: match_datetime falls back to string comparison when datetime parsing fails.

    If both query and dataset values fail to parse, the function compares strings directly.
    """

    def test_range_with_unparseable_dataset_date_returns_false(self) -> None:
        """
        Verify that a range query against an unparseable dataset value returns False.

        If the dataset date cannot be parsed to a datetime, no range comparison is possible.
        """
        assert match_datetime("20230101-20231231", "not-a-date") is False

    def test_exact_string_fallback_when_parsing_fails(self) -> None:
        """
        Verify that string comparison is used when both values fail datetime parsing.

        Two identical unparseable strings should still compare equal.
        """
        assert match_datetime("INVALID", "INVALID") is True

    def test_exact_string_fallback_mismatch_when_parsing_fails(self) -> None:
        """Verify that differing unparseable strings do not match via string fallback."""
        assert match_datetime("INVALID1", "INVALID2") is False


# ---------------------------------------------------------------------------
# Tests for match_ups_specific_attributes
# ---------------------------------------------------------------------------


class TestMatchUpsSpecificAttributes:
    """
    Contract: match_ups_specific_attributes dispatches tag 0x00404005 to match_datetime.

    All other tags return True (delegated to standard sequence matcher).
    """

    def test_scheduled_start_datetime_tag_dispatches_to_match_datetime(self) -> None:
        """
        Verify tag 0x00404005 is matched via match_datetime.

        An exact datetime query should return True when the dataset value matches.
        """
        query = Dataset()
        query.ScheduledProcedureStepStartDateTime = "20230601120000"
        ds = Dataset()
        ds.ScheduledProcedureStepStartDateTime = "20230601120000"
        assert match_ups_specific_attributes(query, ds, 0x00404005) is True

    def test_scheduled_start_datetime_tag_mismatch_returns_false(self) -> None:
        """Verify tag 0x00404005 returns False when datetime values differ."""
        query = Dataset()
        query.ScheduledProcedureStepStartDateTime = "20230601120000"
        ds = Dataset()
        ds.ScheduledProcedureStepStartDateTime = "20230601130000"
        assert match_ups_specific_attributes(query, ds, 0x00404005) is False

    def test_non_datetime_tag_returns_true_by_default(self) -> None:
        """
        Verify that unrecognised tags return True (deferred to standard sequence matcher).

        Tag 0x00404025 (ScheduledStationNameCodeSequence) is a sequence handled elsewhere;
        the UPS-specific attribute function should return True for it.
        """
        item = Dataset()
        item.CodeValue = "STATION1"
        item.CodingSchemeDesignator = "99CLINIC"
        item.CodeMeaning = "Station One"

        query = Dataset()
        query.ScheduledStationNameCodeSequence = [item]

        ds = Dataset()
        ds.ScheduledStationNameCodeSequence = [item]

        assert match_ups_specific_attributes(query, ds, 0x00404025) is True


# ---------------------------------------------------------------------------
# Tests for is_code_sequence
# ---------------------------------------------------------------------------


class TestIsCodeSequence:
    """
    Contract: is_code_sequence identifies DICOM code sequence elements.

    Returns True for known UPS code sequence tags and for SQ elements whose
    first item contains CodeValue, CodingSchemeDesignator, and CodeMeaning.
    """

    def test_known_ups_tag_returns_true_regardless_of_element(self) -> None:
        """
        Verify that tag 0x00404025 is identified as a code sequence even with an empty element.

        The function checks the known tag list before inspecting the element content.
        """
        elem = pydicom.DataElement(0x00404025, "SQ", [])
        assert is_code_sequence(elem, tag=0x00404025) is True

    def test_known_workitem_tag_returns_true(self) -> None:
        """Verify that tag 0x00404018 is also in the known code sequence tag list."""
        elem = pydicom.DataElement(0x00404018, "SQ", [])
        assert is_code_sequence(elem, tag=0x00404018) is True

    def test_non_sq_element_returns_false(self) -> None:
        """Verify that a non-SQ element is not a code sequence."""
        elem = pydicom.DataElement(0x00100020, "LO", "P001")
        assert is_code_sequence(elem) is False

    def test_empty_sq_returns_false(self) -> None:
        """Verify that an empty SQ with an unknown tag returns False."""
        elem = pydicom.DataElement(0x00081110, "SQ", [])
        assert is_code_sequence(elem) is False

    def test_sq_with_code_attributes_returns_true(self) -> None:
        """
        Verify an SQ element with all three code attributes is a code sequence.

        An SQ element whose first item has CodeValue, CodingSchemeDesignator,
        and CodeMeaning is recognised as a code sequence.
        """
        item = Dataset()
        item.CodeValue = "121726"
        item.CodingSchemeDesignator = "DCM"
        item.CodeMeaning = "RT Treatment"

        elem = pydicom.DataElement(0x00081110, "SQ", [item])
        assert is_code_sequence(elem) is True

    def test_sq_without_code_attributes_returns_false(self) -> None:
        """Verify that an SQ element whose first item lacks CodeValue returns False."""
        item = Dataset()
        item.PatientID = "P001"

        elem = pydicom.DataElement(0x00081110, "SQ", [item])
        assert is_code_sequence(elem) is False


# ---------------------------------------------------------------------------
# Tests for match_code_sequence — default path and UPS dispatch
# ---------------------------------------------------------------------------


class TestMatchCodeSequence:
    """
    Contract: match_code_sequence returns True when every query item finds a matching dataset item.

    Empty query sequences are universal matches. UPS-specific tags dispatch to dedicated functions.
    Dataset items missing CodeValue or CodingSchemeDesignator are skipped during matching.
    """

    def _make_code_item(self, code_value: str, scheme: str, meaning: str = "Meaning") -> Dataset:
        """
        Build a single code sequence item Dataset.

        Args:
            code_value: The CodeValue for the item.
            scheme: The CodingSchemeDesignator for the item.
            meaning: The CodeMeaning for the item.

        Returns:
            A Dataset representing one code sequence item.

        """
        item = Dataset()
        item.CodeValue = code_value
        item.CodingSchemeDesignator = scheme
        item.CodeMeaning = meaning
        return item

    def test_empty_query_sequence_matches_any_dataset_sequence(self) -> None:
        """Verify that an empty query list is a universal match for any dataset sequence."""
        ds_seq = [self._make_code_item("CODE1", "SCHEME1")]
        assert match_code_sequence([], ds_seq) is True

    def test_empty_dataset_sequence_does_not_match_non_empty_query(self) -> None:
        """Verify that a non-empty query sequence does not match an empty dataset sequence."""
        query_seq = [self._make_code_item("CODE1", "SCHEME1")]
        assert match_code_sequence(query_seq, []) is False

    def test_matching_code_and_scheme_returns_true(self) -> None:
        """Verify that a query item whose code and scheme exist in the dataset returns True."""
        query_seq = [self._make_code_item("CODE1", "SCHEME1")]
        ds_seq = [self._make_code_item("CODE1", "SCHEME1"), self._make_code_item("CODE2", "SCHEME1")]
        assert match_code_sequence(query_seq, ds_seq) is True

    def test_mismatched_code_returns_false(self) -> None:
        """Verify that a query code not found in the dataset sequence returns False."""
        query_seq = [self._make_code_item("CODE_MISSING", "SCHEME1")]
        ds_seq = [self._make_code_item("CODE1", "SCHEME1")]
        assert match_code_sequence(query_seq, ds_seq) is False

    def test_mismatched_scheme_returns_false(self) -> None:
        """Verify that mismatched CodingSchemeDesignator returns False even when CodeValue matches."""
        query_seq = [self._make_code_item("CODE1", "SCHEME_WRONG")]
        ds_seq = [self._make_code_item("CODE1", "SCHEME1")]
        assert match_code_sequence(query_seq, ds_seq) is False

    def test_query_item_without_code_value_is_skipped(self) -> None:
        """
        Verify that a query item lacking CodeValue is skipped, leaving overall result True.

        If all query items are skipped (none had CodeValue+CodingSchemeDesignator), the
        function returns True because no constraint was applied.
        """
        incomplete = Dataset()
        incomplete.CodeMeaning = "Incomplete item"
        ds_seq = [self._make_code_item("CODE1", "SCHEME1")]
        assert match_code_sequence([incomplete], ds_seq) is True

    def test_dataset_item_without_code_value_is_skipped_in_matching(self) -> None:
        """
        Verify that a dataset item lacking CodeValue is skipped when evaluating a query item.

        If the only dataset item is incomplete, the query item has no candidate to match,
        so the function returns False.
        """
        query_seq = [self._make_code_item("CODE1", "SCHEME1")]
        incomplete_ds_item = Dataset()
        incomplete_ds_item.CodeMeaning = "No code fields"
        assert match_code_sequence(query_seq, [incomplete_ds_item]) is False

    def test_dispatches_to_scheduled_station_name_for_tag_00404025(self) -> None:
        """
        Verify that tag 0x00404025 is dispatched to match_scheduled_station_name.

        A matching code should return True.
        """
        query_seq = [self._make_code_item("STATION1", "99CLINIC")]
        ds_seq = [self._make_code_item("STATION1", "99CLINIC", "Station One")]
        assert match_code_sequence(query_seq, ds_seq, tag=0x00404025) is True

    def test_dispatches_to_scheduled_workitem_code_for_tag_00404018(self) -> None:
        """
        Verify that tag 0x00404018 is dispatched to match_scheduled_workitem_code.

        A matching code should return True.
        """
        query_seq = [self._make_code_item("121726", "DCM")]
        ds_seq = [self._make_code_item("121726", "DCM", "RT Treatment")]
        assert match_code_sequence(query_seq, ds_seq, tag=0x00404018) is True


# ---------------------------------------------------------------------------
# Tests for match_scheduled_station_name
# ---------------------------------------------------------------------------


class TestMatchScheduledStationName:
    """
    Contract: match_scheduled_station_name requires every query station to exist in the dataset.

    Station items missing CodeValue or CodingSchemeDesignator are skipped.
    """

    def _make_station(self, code_value: str, scheme: str) -> Dataset:
        """
        Build a single station code item.

        Args:
            code_value: The CodeValue for the station.
            scheme: The CodingSchemeDesignator for the station.

        Returns:
            A Dataset representing one station code item.

        """
        item = Dataset()
        item.CodeValue = code_value
        item.CodingSchemeDesignator = scheme
        return item

    def test_matching_station_returns_true(self) -> None:
        """Verify a query station present in the dataset returns True."""
        query_seq = [self._make_station("LINAC1", "99CLINIC")]
        ds_seq = [self._make_station("LINAC1", "99CLINIC")]
        assert match_scheduled_station_name(query_seq, ds_seq) is True

    def test_mismatched_station_returns_false(self) -> None:
        """Verify a query station not in the dataset returns False."""
        query_seq = [self._make_station("LINAC1", "99CLINIC")]
        ds_seq = [self._make_station("LINAC2", "99CLINIC")]
        assert match_scheduled_station_name(query_seq, ds_seq) is False

    def test_query_item_without_code_value_is_skipped(self) -> None:
        """
        Verify that a query item without CodeValue or CodingSchemeDesignator is skipped.

        The loop continues without returning False for that item.
        """
        incomplete = Dataset()
        incomplete.CodeMeaning = "No required fields"
        ds_seq = [self._make_station("LINAC1", "99CLINIC")]
        assert match_scheduled_station_name([incomplete], ds_seq) is True

    def test_dataset_item_without_code_value_is_skipped(self) -> None:
        """
        Verify that a dataset item missing CodeValue is skipped.

        If no dataset item can match the query item, the result is False.
        """
        query_seq = [self._make_station("LINAC1", "99CLINIC")]
        incomplete_ds = Dataset()
        incomplete_ds.CodeMeaning = "No code fields"
        assert match_scheduled_station_name(query_seq, [incomplete_ds]) is False

    def test_multiple_query_stations_all_must_match(self) -> None:
        """Verify that all query stations must be found in the dataset sequence."""
        query_seq = [
            self._make_station("LINAC1", "99CLINIC"),
            self._make_station("LINAC2", "99CLINIC"),
        ]
        ds_seq = [self._make_station("LINAC1", "99CLINIC")]
        assert match_scheduled_station_name(query_seq, ds_seq) is False


# ---------------------------------------------------------------------------
# Tests for match_scheduled_workitem_code
# ---------------------------------------------------------------------------


class TestMatchScheduledWorkitemCode:
    """
    Contract: match_scheduled_workitem_code requires every query workitem to exist in the dataset.

    Items missing CodeValue or CodingSchemeDesignator are skipped.
    """

    def _make_workitem(self, code_value: str, scheme: str) -> Dataset:
        """
        Build a single workitem code item.

        Args:
            code_value: The CodeValue for the workitem.
            scheme: The CodingSchemeDesignator for the workitem.

        Returns:
            A Dataset representing one workitem code item.

        """
        item = Dataset()
        item.CodeValue = code_value
        item.CodingSchemeDesignator = scheme
        return item

    def test_matching_workitem_returns_true(self) -> None:
        """Verify a workitem code present in the dataset returns True."""
        query_seq = [self._make_workitem("121726", "DCM")]
        ds_seq = [self._make_workitem("121726", "DCM")]
        assert match_scheduled_workitem_code(query_seq, ds_seq) is True

    def test_mismatched_workitem_returns_false(self) -> None:
        """Verify a workitem code absent from the dataset returns False."""
        query_seq = [self._make_workitem("121726", "DCM")]
        ds_seq = [self._make_workitem("999999", "DCM")]
        assert match_scheduled_workitem_code(query_seq, ds_seq) is False

    def test_query_item_without_required_fields_is_skipped(self) -> None:
        """
        Verify that a query workitem item lacking CodeValue is skipped.

        The result is True because no valid constraint was applied.
        """
        incomplete = Dataset()
        incomplete.CodeMeaning = "No code"
        ds_seq = [self._make_workitem("121726", "DCM")]
        assert match_scheduled_workitem_code([incomplete], ds_seq) is True

    def test_dataset_item_without_required_fields_is_skipped(self) -> None:
        """
        Verify that a dataset workitem item missing CodeValue is skipped during matching.

        Since no valid dataset item matches the query item, the result is False.
        """
        query_seq = [self._make_workitem("121726", "DCM")]
        incomplete_ds = Dataset()
        incomplete_ds.CodeMeaning = "No code"
        assert match_scheduled_workitem_code(query_seq, [incomplete_ds]) is False

    def test_multiple_query_workitems_all_must_match(self) -> None:
        """Verify that all query workitems must be present in the dataset."""
        query_seq = [
            self._make_workitem("121726", "DCM"),
            self._make_workitem("121727", "DCM"),
        ]
        ds_seq = [self._make_workitem("121726", "DCM")]
        assert match_scheduled_workitem_code(query_seq, ds_seq) is False


# ---------------------------------------------------------------------------
# Tests for match_query_to_dataset — meta-group, regular SQ, and direct comparison
# ---------------------------------------------------------------------------


class TestMatchQueryToDatasetAdditional:
    """
    Contract: match_query_to_dataset handles all attribute types and edge cases.

    Covers meta-group tags, regular SQ items, non-string direct comparison,
    and UID (UI VR) matching.
    """

    def test_meta_group_tags_are_skipped(self) -> None:
        """
        Verify that tags in group 0x0002 (DICOM meta information) are ignored by the matcher.

        A query attribute in the meta group should not cause a non-match even if the
        dataset has no corresponding attribute in that group.
        """
        ds = Dataset()
        ds.PatientID = "P001"

        # Build a raw tag in group 0x0002 directly in a query dataset.
        # Tag (0002,0010) = TransferSyntaxUID — this should be skipped by the matcher.
        meta_query = Dataset()
        meta_query.add_new(pydicom.tag.Tag(0x0002, 0x0010), "UI", "1.2.840.10008.1.2.1")

        result = match_query_to_dataset(meta_query, ds)
        assert result is True

    def test_regular_sq_empty_query_matches_any_dataset_sq(self) -> None:
        """
        Verify that an empty regular SQ query (non-code sequence) is a universal match.

        A non-UPS SQ with zero items in the query should match any dataset with that tag.
        """
        ref_item = Dataset()
        ref_item.ReferencedSOPInstanceUID = "1.2.3.4.5"

        ds = Dataset()
        ds.ReferencedStudySequence = [ref_item]

        query = Dataset()
        query.ReferencedStudySequence = []

        assert match_query_to_dataset(query, ds) is True

    def test_regular_sq_nonempty_query_matches_if_any_item_pair_matches(self) -> None:
        """
        Verify that a non-empty regular SQ query matches when at least one query/dataset item pair matches.

        The inner recursive call must find at least one matching pair of items.
        """
        ref_item1 = Dataset()
        ref_item1.ReferencedSOPInstanceUID = "1.2.3.4.5"

        ref_item2 = Dataset()
        ref_item2.ReferencedSOPInstanceUID = "9.9.9.9.9"

        ds = Dataset()
        ds.ReferencedStudySequence = [ref_item1, ref_item2]

        query_item = Dataset()
        query_item.ReferencedSOPInstanceUID = "1.2.3.4.5"

        query = Dataset()
        query.ReferencedStudySequence = [query_item]

        assert match_query_to_dataset(query, ds) is True

    def test_regular_sq_nonempty_query_no_match_when_items_differ(self) -> None:
        """Verify that a non-empty regular SQ query fails when no dataset item satisfies the query item."""
        ref_item = Dataset()
        ref_item.ReferencedSOPInstanceUID = "9.9.9.9.9"

        ds = Dataset()
        ds.ReferencedStudySequence = [ref_item]

        query_item = Dataset()
        query_item.ReferencedSOPInstanceUID = "1.2.3.4.5"

        query = Dataset()
        query.ReferencedStudySequence = [query_item]

        assert match_query_to_dataset(query, ds) is False

    def test_regular_sq_nonempty_query_against_empty_dataset_sq_returns_false(self) -> None:
        """Verify that a non-empty regular SQ query does not match an empty dataset SQ."""
        ds = Dataset()
        ds.ReferencedStudySequence = []

        query_item = Dataset()
        query_item.ReferencedSOPInstanceUID = "1.2.3.4.5"

        query = Dataset()
        query.ReferencedStudySequence = [query_item]

        assert match_query_to_dataset(query, ds) is False

    def test_uid_exact_match(self) -> None:
        """
        Verify that a UI (UID) attribute is matched exactly as a string.

        SOPClassUID is a UI VR; exact string equality should be applied.
        """
        ds = Dataset()
        ds.SOPClassUID = "1.2.840.10008.5.1.4.34.6.4"

        query = Dataset()
        query.SOPClassUID = "1.2.840.10008.5.1.4.34.6.4"

        assert match_query_to_dataset(query, ds) is True

    def test_uid_mismatch_returns_false(self) -> None:
        """Verify that a UI attribute with a different UID value does not match."""
        ds = Dataset()
        ds.SOPClassUID = "1.2.840.10008.5.1.4.34.6.4"

        query = Dataset()
        query.SOPClassUID = "1.2.840.10008.5.1.4.34.6.99"

        assert match_query_to_dataset(query, ds) is False

    def test_numeric_attribute_exact_match(self) -> None:
        """
        Verify that numeric (non-string) attributes are compared by direct equality.

        NumberOfFrames (IS VR in some contexts) or another integer attribute exercises
        the ``elif query_value != dataset_value`` branch for non-string types.
        """
        ds = Dataset()
        ds.NumberOfFrames = 5

        query = Dataset()
        query.NumberOfFrames = 5

        assert match_query_to_dataset(query, ds) is True

    def test_numeric_attribute_mismatch_returns_false(self) -> None:
        """Verify that mismatched numeric attributes return False."""
        ds = Dataset()
        ds.NumberOfFrames = 5

        query = Dataset()
        query.NumberOfFrames = 3

        assert match_query_to_dataset(query, ds) is False

    def test_tm_vr_attribute_match(self) -> None:
        """
        Verify that a TM (Time) VR attribute is matched via match_datetime when both values are strings.

        StudyTime carries TM VR; an exact time string should match.
        """
        ds = Dataset()
        ds.StudyTime = "120000"

        query = Dataset()
        query.StudyTime = "120000"

        assert match_query_to_dataset(query, ds) is True

    def test_tm_vr_attribute_mismatch_returns_false(self) -> None:
        """Verify that a differing TM attribute value returns False."""
        ds = Dataset()
        ds.StudyTime = "120000"

        query = Dataset()
        query.StudyTime = "130000"

        assert match_query_to_dataset(query, ds) is False

    def test_person_name_wildcard_match(self) -> None:
        """
        Verify that a PN (PersonName) query value with a wildcard matches correctly.

        PersonName is a pydicom.valuerep.PersonName; the matcher converts it to str.
        """
        ds = Dataset()
        ds.PatientName = "Smith^Jane"

        query = Dataset()
        query.PatientName = "Smith*"

        assert match_query_to_dataset(query, ds) is True

    def test_person_name_exact_match(self) -> None:
        """Verify that an exact PN query value matches the dataset PersonName."""
        ds = Dataset()
        ds.PatientName = "Doe^John"

        query = Dataset()
        query.PatientName = "Doe^John"

        assert match_query_to_dataset(query, ds) is True

    def test_empty_person_name_query_matches_all(self) -> None:
        """Verify that an empty PN query value is a universal match."""
        ds = Dataset()
        ds.PatientName = "Doe^John"

        query = Dataset()
        query.PatientName = ""

        assert match_query_to_dataset(query, ds) is True

    def test_da_vr_with_non_string_value_is_not_datetime_matched(self) -> None:
        """
        Verify that a DA VR element with a non-string (None) value is not passed to match_datetime.

        When both query_value and dataset_value are strings the DA branch calls match_datetime.
        When either is not a string (e.g., None — valid in pydicom for empty elements),
        the branch condition ``isinstance(query_value, str) and isinstance(dataset_value, str)``
        is False and nothing is done; the element is effectively skipped, so the overall
        match returns True.
        """
        import pydicom.tag

        query = Dataset()
        query.add_new(pydicom.tag.Tag("StudyDate"), "DA", None)

        ds = Dataset()
        ds.add_new(pydicom.tag.Tag("StudyDate"), "DA", None)

        assert match_query_to_dataset(query, ds) is True


# ---------------------------------------------------------------------------
# Tests for example_ups_query smoke test
# ---------------------------------------------------------------------------


class TestExampleUpsQuery:
    """
    Contract: example_ups_query returns a list (possibly empty) without raising.

    This exercises the function body including Dataset construction and query_datasets call.
    """

    def test_returns_empty_list_for_empty_input(self) -> None:
        """
        Verify that example_ups_query returns an empty list when no datasets exist.

        The function is hardcoded to query against an empty list, so the result
        must always be an empty list.
        """
        result = example_ups_query()
        assert isinstance(result, list)
        assert len(result) == 0
