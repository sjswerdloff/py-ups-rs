# py-ups-rs

A DICOMWeb UPS-RS server implementation with WebSocket notifications using Falcon.

## Features

- Implementation of the DICOMWeb UPS-RS standard
- WebSocket notifications for UPS events
- RESTful API for UPS workitem management
- Clean architecture with separation of concerns

## Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/py-ups-rs.git
cd py-ups-rs

# Create a virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies with uv
uv pip install -e .
```

## Development

```bash
# Install development dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Run integration tests
pytest -m integration

# Run linting
ruff check .
```

## Usage

```bash
# Run the server
python -m pyupsrs.app
```

For more information, see the DICOMWeb UPS-RS standard documentation:
[DICOM PS3.18](https://dicom.nema.org/medical/dicom/current/output/html/part18.html)
