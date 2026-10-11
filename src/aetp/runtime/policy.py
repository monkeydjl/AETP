"""Fixed Policy validation; client risk labels can only restrict authority."""

from aetp.collaboration.policy import PolicyViolation, text
from aetp.runtime.contracts import POLICY_VERSION


def natural(value):
    if type(value) is not int or value < 0:
        raise PolicyViolation("INVALID_PAYLOAD")
    return value


def validate(payload, allowed, *, governed=False):
    approval = payload.get("approval_required", False)
    risk = payload.get("risk_level", "low")
    if type(approval) is not bool or not isinstance(risk, str) or risk not in {"low", "medium", "high", "critical"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    if (approval or risk != "low") and not governed:
        raise PolicyViolation("APPROVAL_REQUIRED")
    if payload.get("policy_version", POLICY_VERSION) != POLICY_VERSION:
        raise PolicyViolation("POLICY_UNAVAILABLE")
    if payload.keys() - set(allowed) - {"approval_required", "risk_level", "policy_version"}:
        raise PolicyViolation("INVALID_PAYLOAD")


def governance(project, wall_ms):
    natural(wall_ms)
    clock = project.get("execution_clock")
    if clock is None:
        raise PolicyViolation("POLICY_UNAVAILABLE")
    anchor = clock["wall_anchor_ms"]
    if wall_ms < anchor:
        raise PolicyViolation("CLOCK_REGRESSION")
    elapsed = 0 if project["status"] == "paused" else wall_ms - anchor
    return clock["elapsed_ms"] + elapsed


def observed_time(state, value):
    natural(value)
    if any(value < item.get("observed_at_ms", 0) for item in state.values()):
        raise PolicyViolation("CLOCK_REGRESSION")
    return value


def binding_payload(payload):
    text(payload.get("binding_id"), identifier=True)
    natural(payload.get("lease_epoch"))


FENCE_FIELDS = {"binding_id", "lease_epoch", "session_id"}
