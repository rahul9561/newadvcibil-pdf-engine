from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
# The legacy TransUnion TrueLinkCreditReport-shaped API transcript. It was
# input/sample.json before the upstream feed switched to the B2C-REPORT
# format; kept as a fixture so the TLCR / raw-subject parser paths (still
# supported) stay covered.
SAMPLE_JSON_PATH = FIXTURES_DIR / "tlcr_sample.json"
# The current upstream format - the file the CLI/example flow renders.
B2C_SAMPLE_JSON_PATH = Path(__file__).parent.parent / "input" / "sample.json"


@pytest.fixture(scope="session")
def sample_json() -> dict:
    with open(SAMPLE_JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="session")
def b2c_json() -> dict:
    with open(B2C_SAMPLE_JSON_PATH, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture()
def b2c_json_copy(b2c_json) -> dict:
    return copy.deepcopy(b2c_json)


def b2c_of(data: dict) -> dict:
    """The ``B2C-REPORT`` object inside the sample's API envelope."""
    return data["data"]["result_json"]["parsed_data"]["B2C-REPORT"]


def standard_of(data: dict) -> dict:
    return b2c_of(data)["REPORT-DATA"]["STANDARD-DATA"]


@pytest.fixture()
def sample_json_copy(sample_json) -> dict:
    """A deep copy every test can mutate freely."""
    return copy.deepcopy(sample_json)


def tlcr_of(data: dict) -> dict:
    """Reach into the sample's wrapper shape and return the
    TrueLinkCreditReport object, for tests that need to mutate it.
    """
    return data["data"]["steps"][2]["response"]["GetCustomerAssetsResponse"][
        "GetCustomerAssetsSuccess"
    ]["Asset"]["TrueLinkCreditReport"]
