"""Fixed admission policy and pure clock/accounting checks."""

import math

from aetp.collaboration.policy import PolicyViolation, text
from aetp.meetings.contracts import POLICY_VERSION

DEFAULTS = {"token_budget": 100000, "time_budget_ms": 1200000, "max_rounds": 3,
            "no_new_evidence_rounds": 2, "consensus_threshold": 0.8}


def natural(value, maximum=2**63 - 1, *, positive=False):
    if type(value) is not int or value < int(positive) or value > maximum:
        raise PolicyViolation("INVALID_PAYLOAD")
    return value


def policy(value, kind="meeting"):
    defaults = {key: val for key, val in DEFAULTS.items()
                if kind == "meeting" or key not in {"max_rounds", "no_new_evidence_rounds"}}
    if not isinstance(value, dict) or value.keys() - defaults.keys():
        raise PolicyViolation("INVALID_PAYLOAD")
    result = {**defaults, **value}
    for field, ceiling in (("token_budget", 1000000), ("time_budget_ms", 86400000),
                           ("max_rounds", 100), ("no_new_evidence_rounds", 100)):
        if field in result:
            natural(result[field], ceiling, positive=True)
    threshold = result["consensus_threshold"]
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise PolicyViolation("INVALID_PAYLOAD")
    return result


def payload(value, allowed):
    if value.keys() - set(allowed) - {"policy_version"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    if value.get("policy_version", POLICY_VERSION) != POLICY_VERSION:
        raise PolicyViolation("POLICY_UNAVAILABLE")


def evidence_refs(value, state):
    if not isinstance(value, (tuple, list)) or len(value) > 32:
        raise PolicyViolation("INVALID_REFERENCE")
    result = []
    for ref in value:
        if not isinstance(ref, dict) or set(ref) != {"artifact_id", "content_digest"}:
            raise PolicyViolation("INVALID_REFERENCE")
        identifier = text(ref["artifact_id"], identifier=True)
        artifact = state.get(f"artifact:{identifier}")
        if artifact is None or artifact["content_digest"] != ref["content_digest"]:
            raise PolicyViolation("INVALID_REFERENCE")
        if ref in result:
            raise PolicyViolation("INVALID_REFERENCE")
        result.append(dict(ref))
    return result


def governance_time(events, wall_ms):
    """Stable wall-time origin minus durable pause intervals, even before M1 configuration."""
    natural(wall_ms)
    paused_at = None
    excluded = 0
    for event in events:
        at = event.payload.get("observed_at_ms", 0)
        if at > wall_ms:
            raise PolicyViolation("CLOCK_REGRESSION")
        if event.type == "project.paused":
            paused_at = at
        elif event.type == "project.resumed" and paused_at is not None:
            excluded += at - paused_at
            paused_at = None
    if paused_at is not None:
        excluded += wall_ms - paused_at
    return wall_ms - excluded


def projected_time(project, wall_ms):
    """Pure equivalent of the durable pause intervals, independent of M1's origin."""
    natural(wall_ms)
    clock = project.get("collaboration_clock", {"excluded_ms": 0, "paused_at_ms": None})
    excluded = clock["excluded_ms"]
    if clock["paused_at_ms"] is not None:
        if wall_ms < clock["paused_at_ms"]:
            raise PolicyViolation("CLOCK_REGRESSION")
        excluded += wall_ms - clock["paused_at_ms"]
    if wall_ms < project.get("observed_at_ms", 0):
        raise PolicyViolation("CLOCK_REGRESSION")
    return wall_ms - excluded


def termination(record, stats, at):
    if record["deadline_ms"] is not None and at >= record["deadline_ms"]:
        return "time_budget"
    if stats["tokens"] >= record["policy"]["token_budget"]:
        return "token_budget"
    if record["kind"] == "meeting" and record["completed_rounds"] >= record["policy"]["max_rounds"]:
        return "max_rounds"
    if record["kind"] == "meeting" and record["no_new_evidence"] >= record["policy"]["no_new_evidence_rounds"]:
        return "no_new_evidence"
    if record["status"] in {"open", "debate"} and stats["consensus_peak"] >= record["policy"]["consensus_threshold"]:
        return "consensus_threshold"
    return None
