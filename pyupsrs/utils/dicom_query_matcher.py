"""Module for DICOM query matching functionality."""

import re
from datetime import datetime

import pydicom
import pydicom.valuerep
from pydicom.dataset import Dataset

# DICOM VR constants
DT = "DT"  # Date Time
TM = "TM"  # Time
DA = "DA"  # Date


def parse_dicom_date(date_str: str) -> datetime | None:
    """
    Parse a DICOM date/time string into a Python datetime object.

    Handles:
    - DA format (YYYYMMDD)
    - TM format (HHMMSS.FFFFFF)
    - DT format (YYYYMMDDHHMMSS.FFFFFF)

    Returns None if parsing fails.
    """
    if not date_str or date_str == "*":
        return None

    try:
        # Remove any timezone offset for simplicity
        date_str = date_str.split("+")[0].split("-")[0]

        # Handle DA format (YYYYMMDD)
        if len(date_str) == 8:
            return datetime.strptime(date_str, "%Y%m%d")

        # Handle TM format (HHMMSS.FFFFFF)
        elif len(date_str) <= 16 and "." in date_str:
            parts = date_str.split(".")
            time_part = parts[0].ljust(6, "0")  # Pad with zeros if needed
            if len(time_part) > 6:
                time_part = time_part[:6]

            if len(parts) > 1:
                # Handle microseconds
                micro = parts[1].ljust(6, "0")[:6]
                return datetime.strptime(f"19000101{time_part}.{micro}", "%Y%m%d%H%M%S.%f")
            else:
                return datetime.strptime(f"19000101{time_part}", "%Y%m%d%H%M%S")

        # Handle TM format without microseconds
        elif len(date_str) <= 6:
            time_part = date_str.ljust(6, "0")  # Pad with zeros if needed
            if len(time_part) > 6:
                time_part = time_part[:6]
            return datetime.strptime(f"19000101{time_part}", "%Y%m%d%H%M%S")

        # Handle DT format (YYYYMMDDHHMMSS.FFFFFF)
        else:
            parts = date_str.split(".")
            datetime_part = parts[0].ljust(14, "0")  # Pad with zeros if needed
            if len(datetime_part) > 14:
                datetime_part = datetime_part[:14]

            if len(parts) > 1:
                # Handle microseconds
                micro = parts[1].ljust(6, "0")[:6]
                return datetime.strptime(f"{datetime_part}.{micro}", "%Y%m%d%H%M%S.%f")
            else:
                return datetime.strptime(datetime_part, "%Y%m%d%H%M%S")
    except Exception as e:
        print(f"Error parsing DICOM date '{date_str}': {e}")
        return None


def match_datetime(query_datetime: str, dataset_datetime: str) -> bool:
    """
    Match date/time values according to DICOM rules.

    Handles:
    - Empty values (universal match)
    - Range matching with '-'
    - Wildcard matching with '*' and '?'
    - Proper chronological comparison using datetime objects
    """
    if not query_datetime or query_datetime == "*":
        # Empty query matches anything
        return True

    # Handle wildcard patterns first
    if "*" in query_datetime or "?" in query_datetime:
        pattern = "^" + query_datetime.replace("*", ".*").replace("?", ".") + "$"
        return bool(re.match(pattern, dataset_datetime))

    # Handle range matching
    if "-" in query_datetime:
        range_parts = query_datetime.split("-")
        if len(range_parts) == 2:
            start_date_str, end_date_str = range_parts

            # Parse the dates to datetime objects
            start_date = parse_dicom_date(start_date_str)
            end_date = parse_dicom_date(end_date_str)
            ds_date = parse_dicom_date(dataset_datetime)

            if not ds_date:
                return False

            # Check range with proper comparison
            if start_date and end_date:
                return start_date <= ds_date <= end_date
            elif start_date:
                return start_date <= ds_date
            elif end_date:
                return ds_date <= end_date

    # Direct comparison after parsing to ensure chronological accuracy
    query_dt = parse_dicom_date(query_datetime)
    dataset_dt = parse_dicom_date(dataset_datetime)

    if query_dt and dataset_dt:
        return query_dt == dataset_dt

    # Fall back to string comparison if parsing fails
    return query_datetime == dataset_datetime


def match_ups_specific_attributes(query: Dataset, dataset: Dataset, tag: int) -> bool:
    """
    Match specific UPS attributes according to the IHE-RO TDW-II profile.

    Args:
        query: Query dataset
        dataset: Dataset to match against
        tag: The tag being evaluated

    Returns:
        bool: True if matches, False otherwise

    """
    elem = query[tag]
    query_value = elem.value
    dataset_value = dataset[tag].value

    # Handle Scheduled Procedure Step Start Date and Time (0040,4005)
    if tag == 0x00404005:
        return match_datetime(query_value, dataset_value)

    # For sequences, use the standard sequence matching logic
    return True  # Default to letting the standard sequence matcher handle it


def is_code_sequence(elem: pydicom.DataElement, tag: int = None) -> bool:
    """
    Determine if a data element is a code sequence.

    Some tags are known code sequences in UPS.
    """
    # Known code sequence tags in UPS
    ups_code_sequence_tags = [
        0x00404025,  # Scheduled Station Name Code Sequence
        0x00404018,  # Scheduled Workitem Code Sequence
        # Add other known code sequence tags as needed
    ]

    if tag in ups_code_sequence_tags:
        return True

    if elem.VR != "SQ" or len(elem.value) == 0:
        return False

    # Check if the first item has the expected attributes of a code sequence
    first_item = elem.value[0]
    return "CodeValue" in first_item and "CodingSchemeDesignator" in first_item and "CodeMeaning" in first_item


def match_code_sequence(query_seq: list[Dataset], dataset_seq: list[Dataset], tag: int = None) -> bool:
    """
    Match code sequences according to DICOM rules, with special handling for UPS sequences.

    Args:
        query_seq: The sequence from the query
        dataset_seq: The sequence from the dataset
        tag: The parent tag of the sequence

    Returns:
        bool: True if sequences match, False otherwise

    """
    if not query_seq:  # Empty query sequence matches anything
        return True

    if not dataset_seq:  # Can't match against empty dataset sequence
        return False

    # Handle Scheduled Station Name Code Sequence (0040,4025)
    if tag == 0x00404025:
        return match_scheduled_station_name(query_seq, dataset_seq)

    # Handle Scheduled Workitem Code Sequence (0040,4018)
    if tag == 0x00404018:
        return match_scheduled_workitem_code(query_seq, dataset_seq)

    # Default code sequence matching
    for query_item in query_seq:
        match_found = False

        if "CodeValue" not in query_item or "CodingSchemeDesignator" not in query_item:
            continue

        query_code_value = query_item.CodeValue
        query_scheme = query_item.CodingSchemeDesignator

        for ds_item in dataset_seq:
            if "CodeValue" not in ds_item or "CodingSchemeDesignator" not in ds_item:
                continue

            if ds_item.CodeValue == query_code_value and ds_item.CodingSchemeDesignator == query_scheme:
                match_found = True
                break

        if not match_found:
            return False

    return True


def match_scheduled_station_name(query_seq: list[Dataset], dataset_seq: list[Dataset]) -> bool:
    """
    Match Scheduled Station Name Code Sequence according to IHE-RO TDW-II rules.

    This requires matching on CodeValue and CodingSchemeDesignator.
    """
    # For TDW-II, we need to match each code in the query against the dataset
    for query_item in query_seq:
        match_found = False

        if "CodeValue" not in query_item or "CodingSchemeDesignator" not in query_item:
            continue

        query_code_value = query_item.CodeValue
        query_scheme = query_item.CodingSchemeDesignator

        for ds_item in dataset_seq:
            if "CodeValue" not in ds_item or "CodingSchemeDesignator" not in ds_item:
                continue

            if ds_item.CodeValue == query_code_value and ds_item.CodingSchemeDesignator == query_scheme:
                match_found = True
                break

        if not match_found:
            return False

    return True


def match_scheduled_workitem_code(query_seq: list[Dataset], dataset_seq: list[Dataset]) -> bool:
    """
    Match Scheduled Workitem Code Sequence according to IHE-RO TDW-II rules.

    This is typically used to filter for specific treatment workitems.
    """
    # Similar to standard code sequence matching but with IHE-RO TDW-II specific rules
    for query_item in query_seq:
        match_found = False

        if "CodeValue" not in query_item or "CodingSchemeDesignator" not in query_item:
            continue

        query_code_value = query_item.CodeValue
        query_scheme = query_item.CodingSchemeDesignator

        for ds_item in dataset_seq:
            if "CodeValue" not in ds_item or "CodingSchemeDesignator" not in ds_item:
                continue

            if ds_item.CodeValue == query_code_value and ds_item.CodingSchemeDesignator == query_scheme:
                match_found = True
                break

        if not match_found:
            return False

    return True


def match_query_to_dataset(query: Dataset, dataset: Dataset) -> bool:
    """Match a DICOM query against a dataset, with special handling for UPS attributes."""
    # Iterate through each element in the query
    for elem in query:
        tag = elem.tag

        # Skip meta information
        if tag.group == 0x0002:
            continue

        # If the dataset doesn't have this tag, it doesn't match
        if tag not in dataset:
            return False

        # Check for UPS-specific attributes with special matching rules
        if tag == 0x00404005:  # Scheduled Procedure Step Start Date and Time
            if not match_ups_specific_attributes(query, dataset, tag):
                return False
            continue

        # Get the query value
        query_value = elem.value

        # Get the dataset value
        dataset_value = dataset[tag].value

        # Check if this is a code sequence
        if elem.VR == "SQ" and (is_code_sequence(elem, tag) or tag in [0x00404025, 0x00404018]):
            if not match_code_sequence(query_value, dataset_value, tag):
                return False
        # Handle regular sequence elements
        elif elem.VR == "SQ":
            # If query has an empty sequence, it matches any sequence
            if len(query_value) == 0:
                continue

            # If dataset has an empty sequence but query isn't empty, no match
            if len(dataset_value) == 0:
                return False

            # Try to match any item in the sequence
            match_found = False
            for q_item in query_value:
                for ds_item in dataset_value:
                    if match_query_to_dataset(q_item, ds_item):
                        match_found = True
                        break
                if match_found:
                    break

            if not match_found:
                return False
        # Handle date/time attributes
        elif elem.VR in [DA, DT, TM]:
            if isinstance(query_value, str) and isinstance(dataset_value, str):
                if not match_datetime(query_value, dataset_value):
                    return False
        # Handle wildcard matching for strings
        elif isinstance(query_value, str) or isinstance(query_value, pydicom.valuerep.PersonName):
            # If query value is empty or universal match, it matches anything
            query_value = str(query_value)  # convert from PN to str if necessary
            if query_value == "" or query_value == "*":
                continue

            # Convert dataset value to string for comparison
            ds_value_str = str(dataset_value)

            # Handle wildcards
            if "*" in query_value or "?" in query_value:
                pattern = "^" + query_value.replace("*", ".*").replace("?", ".") + "$"
                if not re.match(pattern, ds_value_str):
                    return False
            # Direct comparison for non-wildcard strings
            elif query_value != ds_value_str:
                return False
        # Direct comparison for other value types
        elif query_value != dataset_value:
            return False

    return True


def query_datasets(query: Dataset, datasets: list[Dataset]) -> list[Dataset]:
    """
    Find all datasets matching the DICOM query.

    Args:
        query: A DICOM dataset containing query parameters
        datasets: List of datasets to search

    Returns:
        list[Dataset]: List of matching datasets

    """
    return [ds for ds in datasets if match_query_to_dataset(query, ds)]


# Example usage with UPS for IHE-RO TDW-II
def example_ups_query() -> list[Dataset]:
    """
    Provide Example of using the query matcher with UPS in the IHE-RO TDW-II context.

    Returns:
        list[Dataset]: List of matching UPS instances

    """
    # Create a UPS query for IHE-RO TDW-II
    query = Dataset()
    query.QueryRetrieveLevel = "WORKLIST"

    # Create Scheduled Station Name Code Sequence
    station_name_seq = Dataset()
    station_name_seq.CodeValue = "TRTMACHINE1"
    station_name_seq.CodingSchemeDesignator = "99CLINIC"
    station_name_seq.CodeMeaning = "Treatment Machine 1"

    # Add sequence to query
    query.ScheduledStationNameCodeSequence = [station_name_seq]

    # Add date range for Scheduled Procedure Step Start Date and Time
    query.ScheduledProcedureStepStartDateTime = "20230101000000-20231231235959"

    # Add Scheduled Workitem Code Sequence for treatment delivery
    workitem_seq = Dataset()
    workitem_seq.CodeValue = "121726"
    workitem_seq.CodingSchemeDesignator = "DCM"
    workitem_seq.CodeMeaning = "RT Treatment"

    query.ScheduledWorkitemCodeSequence = [workitem_seq]

    # List of datasets to search (UPS instances)
    datasets = []  # This would be your list of UPS datasets

    # Perform the query
    matching_datasets = query_datasets(query, datasets)

    return matching_datasets


if __name__ == "__main__":
    # Example usage
    example_ups_query()
