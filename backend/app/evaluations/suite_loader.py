import hashlib
import json
import logging
import os
from typing import Literal

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

HASH_ALGORITHM = "sha256"

InputType = Literal["text", "image"]
CaseType = Literal["transcribe", "interpret", "image"]


class CaseImage(BaseModel):
    file: str = Field(min_length=1, max_length=400)


class _CaseModel(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    category: str | None = None
    prompt: str = Field(min_length=1)
    input_type: InputType = "text"
    case_type: CaseType | None = None
    expected_properties: list[str] = Field(default_factory=list)
    disabled: bool = False
    image: CaseImage | None = None

    @field_validator("id")
    @classmethod
    def _validate_id(cls, value: str) -> str:
        if not value.replace("-", "").replace(".", "").replace("_", "").isalnum():
            raise ValueError("case id must be alphanumeric")
        return value


class _SuiteDocument(BaseModel):
    version: int = Field(ge=1)
    cases: list[_CaseModel] = Field(min_length=1)


class LoadedCase:
    def __init__(
        self,
        id: str,
        category: str | None,
        prompt: str,
        input_type: InputType,
        case_type: CaseType | None,
        expected_properties: list[str],
        disabled: bool,
        image: CaseImage | None,
    ) -> None:
        self.id = id
        self.category = category
        self.prompt = prompt
        self.input_type = input_type
        self.case_type = case_type
        self.expected_properties = expected_properties
        self.disabled = disabled
        self.image = image

    @property
    def key(self) -> str:
        return self.id

    @property
    def is_image(self) -> bool:
        return self.input_type == "image"


class LoadedSuite:
    def __init__(
        self,
        name: str,
        version: str,
        hash: str,
        source_path: str,
        cases: list[LoadedCase],
        raw: str,
    ) -> None:
        self.name = name
        self.version = version
        self.hash = hash
        self.source_path = source_path
        self.cases = cases
        self.raw = raw

    def enabled_cases(self) -> list[LoadedCase]:
        return [case for case in self.cases if not case.disabled]

    def enabled_image_cases(self) -> list[LoadedCase]:
        return [case for case in self.enabled_cases() if case.is_image]

    def enabled_text_cases(self) -> list[LoadedCase]:
        return [case for case in self.enabled_cases() if not case.is_image]

    def all_cases(self) -> list[LoadedCase]:
        return list(self.cases)

    @property
    def case_count(self) -> int:
        return len(self.cases)


class SuiteNotFoundError(Exception):
    pass


class SuiteValidationError(Exception):
    pass


def hash_bytes(raw: bytes) -> str:
    digest = hashlib.new(HASH_ALGORITHM)
    digest.update(raw)
    return digest.hexdigest()


def _suite_path(suites_dir: str, name: str) -> str:
    return os.path.join(suites_dir, f"{name}.json")


def load_suite(name: str, suites_dir: str) -> LoadedSuite:
    path = _suite_path(suites_dir, name)
    if not os.path.exists(path):
        raise SuiteNotFoundError(name)
    with open(path, "rb") as handle:
        raw = handle.read()
    return _parse(name, path, raw)


def parse_snapshot(name: str, raw: str) -> LoadedSuite:
    """Build a LoadedSuite from a previously stored snapshot string.

    The snapshot is an immutable copy of the suite file taken when the run was
    created, so edits to the on-disk suite afterwards must not change what this
    run executes. ``parse_snapshot`` never touches the filesystem.
    """
    return _parse(name, f"{name}.json", raw.encode("utf-8"))


def _parse(name: str, path: str, raw: bytes) -> LoadedSuite:
    document_text = raw.decode("utf-8")
    try:
        document = _SuiteDocument.model_validate(json.loads(document_text))
    except (json.JSONDecodeError, ValueError) as exc:
        raise SuiteValidationError(name) from exc
    cases = [
        LoadedCase(
            id=case.id,
            category=case.category,
            prompt=case.prompt,
            input_type=case.input_type,
            case_type=case.case_type,
            expected_properties=case.expected_properties,
            disabled=case.disabled,
            image=case.image,
        )
        for case in document.cases
    ]
    return LoadedSuite(
        name=name,
        version=str(document.version),
        hash=hash_bytes(raw),
        source_path=path,
        cases=cases,
        raw=document_text,
    )
