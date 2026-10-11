"""A fixed in-memory checker, with no executable user code or path operations."""

import copy
import hashlib
import json
import math
from pathlib import Path
import platform

from aetp.acceptance.contracts import (
    MAX_CASE_BYTES, MAX_CASES, MAX_DEPTH, MAX_DOCUMENT_BYTES, MAX_NUMBER_CHARS,
    MAX_PATH, RUNNER_ID,
)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _validate_value(value, depth=0):
    if depth > MAX_DEPTH:
        raise ValueError("JSON structure exceeds depth limit")
    kind = type(value)
    if kind is str:
        value.encode("utf-8")
    elif kind is int:
        if value.bit_length() > 426 or len(str(value)) > MAX_NUMBER_CHARS:
            raise ValueError("JSON number exceeds size limit")
    elif kind is float:
        if not math.isfinite(value):
            raise ValueError("finite JSON number required")
    elif kind is list:
        for item in value:
            _validate_value(item, depth + 1)
    elif kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError("string JSON key required")
            key.encode("utf-8")
            _validate_value(item, depth + 1)
    elif kind not in (bool, type(None)):
        raise ValueError("JSON value required")


def normalize_cases(cases, criteria=None):
    """Validate rather than silently coerce caller types or ignore extra fields."""
    try:
        if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
            raise ValueError("one to 32 Cases required")
        for case in cases:
            if type(case) is not dict or set(case) != {"criterion", "path", "equals"}:
                raise ValueError("criterion, path and equals required")
            criterion, path = case["criterion"], case["path"]
            if (type(criterion) is not str or not criterion.strip()
                    or len(criterion.encode("utf-8")) > 512 or type(path) is not list or len(path) > MAX_PATH):
                raise ValueError("invalid criterion or path")
            for part in path:
                if type(part) is int and 0 <= part <= 2 ** 31 - 1:
                    continue
                if type(part) is str:
                    part.encode("utf-8")
                    continue
                raise ValueError("string key or nonnegative bounded array index required")
            _validate_value(case["equals"])
        if criteria is not None and [case["criterion"] for case in cases] != list(criteria):
            raise ValueError("each criterion needs exactly one ordered Case")
        if len(_canonical(cases).encode("utf-8")) > MAX_CASE_BYTES:
            raise ValueError("Case-set exceeds size limit")
        return copy.deepcopy(cases)
    except (RecursionError, UnicodeError, OverflowError) as exc:
        raise ValueError("invalid Case-set") from exc


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _number(value, constructor):
    if len(value) > MAX_NUMBER_CHARS:
        raise ValueError("JSON number exceeds size limit")
    result = constructor(value)
    _validate_value(result)
    return result


def _constant(value):
    raise ValueError("nonstandard JSON constant")


def _equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return left.keys() == right.keys() and all(_equal(left[key], right[key]) for key in left)
    if type(left) is list:
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return left == right


class FixedJsonRunner:
    """Trusted host code can run this method; Agents only submit Case data."""

    def __init__(self):
        sources = {name: "sha256:" + hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                   for name in ("runner.py", "contracts.py")}
        self._descriptor = {"id": RUNNER_ID, "version": 1, "method": "strict_json_path_equals",
                            "implementation_digest": _digest(sources), "sources": sources,
                            "environment": {"implementation": platform.python_implementation(),
                                            "python_version": platform.python_version()},
                            "invocation": "FixedJsonRunner.run(immutable_content, immutable_cases)"}

    @property
    def descriptor(self):
        return copy.deepcopy(self._descriptor)

    def run(self, content, cases):
        cases = normalize_cases(cases)
        try:
            if type(content) is not str or len(content.encode("utf-8")) > MAX_DOCUMENT_BYTES:
                raise ValueError("invalid document")
            document = json.loads(content, object_pairs_hook=_pairs,
                                  parse_int=lambda value: _number(value, int),
                                  parse_float=lambda value: _number(value, float), parse_constant=_constant)
            _validate_value(document)
        except (ValueError, UnicodeError, RecursionError, OverflowError):
            return {"observed_result": "FAILED", "checks": [], "diagnostic": "INVALID_DOCUMENT"}
        missing = object()
        checks = []
        types = {str: "string", int: "integer", float: "number", bool: "boolean",
                 type(None): "null", list: "array", dict: "object"}
        for case in cases:
            observed = document
            for part in case["path"]:
                if type(observed) is dict and type(part) is str:
                    observed = observed.get(part, missing)
                elif type(observed) is list and type(part) is int and part < len(observed):
                    observed = observed[part]
                else:
                    observed = missing
                if observed is missing:
                    break
            matched = observed is not missing and _equal(observed, case["equals"])
            checks.append({"criterion": case["criterion"], "path": case["path"], "matched": matched,
                           "observed_type": "missing" if observed is missing else types[type(observed)],
                           "observed_digest": None if observed is missing else _digest(observed),
                           "diagnostic": "MATCH" if matched else "MISSING_PATH" if observed is missing else "NOT_EQUAL"})
        passed = all(check["matched"] for check in checks)
        return {"observed_result": "PASSED" if passed else "FAILED", "checks": checks,
                "diagnostic": "ALL_CHECKS_MATCHED" if passed else "CHECKS_FAILED"}
