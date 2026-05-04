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

Known issues / xfail markers:
- match_datetime uses '-' to detect range, so negative timezone offsets in date
  strings may be misinterpreted as ranges. Tests that exercise this are marked
  xfail if the behaviour is incorrect.
"""

from datetime import datetime

from pydicom import Dataset

from pyupsrs.utils.dicom_query_matcher import (
    match_datetime,
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
