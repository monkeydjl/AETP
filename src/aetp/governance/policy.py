"""Pure versioned policy and subject validation, with implementation risk floors."""

import copy

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, canonical_json, digest_value, text
from aetp.governance.contracts import ACTION_RISKS, RISKS, ROLES, system_actor
from aetp.meetings.policy import natural


def fields(value, allowed, required=()):
    if not isinstance(value, dict) or value.keys() - set(allowed) or set(required) - value.keys():
        raise PolicyViolation("INVALID_PAYLOAD")


def revision(command, previous):
    if previous is None:
        if command.expected_revision not in (None, 0):
            raise PolicyViolation("REVISION_CONFLICT")
    elif command.expected_revision != previous["revision"]:
        raise PolicyViolation("REVISION_CONFLICT")


def current(state, project_id):
    project = state.get(f"project:{project_id}")
    if project is None:
        raise PolicyViolation("INVALID_TARGET")
    governance = project.get("governance")
    if governance is None:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    return governance, governance["versions"][governance["current_version"]]["policy"]


def principal(state, project_id, actor, *, internal=False):
    governance, value = current(state, project_id)
    if actor == system_actor(project_id):
        if not internal or f"agent:{actor}" in state:
            raise PolicyViolation("PERMISSION_DENIED")
        return {"type": "system", "id": actor}
    subject = value["subjects"].get(actor)
    if (subject is None or (subject["type"] == "agent" and not participant(state, actor))
            or (subject["type"] == "human" and f"agent:{actor}" in state)):
        raise PolicyViolation("PERMISSION_DENIED")
    return {"type": subject["type"], "id": actor}


def validate_agent_identity(state, project_id, actor):
    """Human identities remain distinct even after their current role is removed."""
    governance = state.get(f"project:{project_id}", {}).get("governance", {})
    if actor == system_actor(project_id) or any(
            version["policy"]["subjects"].get(actor, {}).get("type") == "human"
            for version in governance.get("versions", {}).values()):
        raise PolicyViolation("IDENTITY_CONFLICT")


def has_role(value, actor, role):
    roles = value["subjects"].get(actor, {}).get("roles", [])
    if role == "human_collaborator":
        return bool(set(roles) & {"human_collaborator", "human_owner"})
    return role in roles


def normalize(value, state, project_id, owner):
    try:
        fields(value, {"version", "mode", "rules", "subjects", "max_ttl_ms", "max_renewals"},
               {"version", "mode", "rules", "subjects", "max_ttl_ms", "max_renewals"})
        result = copy.deepcopy(value)
        text(result["version"], identifier=True)
        if result["mode"] not in {"manual", "selective", "autonomous"}:
            raise PolicyViolation("INVALID_POLICY")
        natural(result["max_ttl_ms"], 30 * 86400000, positive=True)
        natural(result["max_renewals"], 3)
        subjects = result["subjects"]
        if not isinstance(subjects, dict) or not subjects:
            raise PolicyViolation("INVALID_POLICY")
        for actor, subject in subjects.items():
            text(actor, identifier=True)
            fields(subject, {"type", "roles"}, {"type", "roles"})
            roles = subject["roles"]
            if (not isinstance(roles, list) or not roles or any(not isinstance(role, str) or role not in ROLES for role in roles)
                    or len(roles) != len(set(roles)) or actor == system_actor(project_id)):
                raise PolicyViolation("INVALID_POLICY")
            if subject["type"] == "agent":
                if not participant(state, actor) or any(role.startswith("human_") for role in roles):
                    raise PolicyViolation("INVALID_POLICY")
            elif subject["type"] == "human":
                if f"agent:{actor}" in state or any(not role.startswith("human_") for role in roles):
                    raise PolicyViolation("INVALID_POLICY")
            else:
                raise PolicyViolation("INVALID_POLICY")
            if "human_owner" in roles and actor != owner:
                raise PolicyViolation("INVALID_POLICY")
            subject["roles"] = sorted(roles)
        if subjects.get(owner) != {"type": "human", "roles": ["human_owner"]}:
            raise PolicyViolation("INVALID_POLICY")
        if not isinstance(result["rules"], list) or not result["rules"]:
            raise PolicyViolation("INVALID_POLICY")
        seen = set()
        for rule in result["rules"]:
            fields(rule, {"action", "risk_level", "approval", "delegate", "revocable_within_ms"},
                   {"action", "risk_level", "approval"})
            action, risk, mode = rule["action"], rule["risk_level"], rule["approval"]
            if (not isinstance(action, str) or action not in ACTION_RISKS or action in seen
                    or risk not in RISKS or RISKS.index(risk) < RISKS.index(ACTION_RISKS[action])
                    or mode not in {"auto", "decision_based", "delegated", "human"}):
                raise PolicyViolation("INVALID_POLICY")
            seen.add(action)
            if risk == "critical" and mode != "human":
                raise PolicyViolation("INVALID_POLICY")
            if mode == "delegated":
                delegate = rule.get("delegate")
                if not isinstance(delegate, str) or delegate not in subjects:
                    raise PolicyViolation("INVALID_POLICY")
                natural(rule.get("revocable_within_ms"), 30 * 86400000, positive=True)
                if risk == "high" and subjects[delegate]["type"] != "human":
                    raise PolicyViolation("INVALID_POLICY")
            elif set(rule) & {"delegate", "revocable_within_ms"}:
                raise PolicyViolation("INVALID_POLICY")
        result["rules"].sort(key=lambda rule: rule["action"])
        return result
    except (KeyError, TypeError, ValueError, PolicyViolation) as exc:
        raise PolicyViolation("INVALID_POLICY") from exc


def configure(command, state, at, context):
    fields(command.payload, {"policy"}, {"policy"})
    previous = state.get(f"project:{command.project_id}")
    if previous is None or command.target_id != command.project_id:
        raise PolicyViolation("INVALID_TARGET")
    revision(command, previous)
    governance = previous.get("governance")
    owner = governance["owner_id"] if governance else context.get("bootstrap_owner")
    if owner is None:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    if command.actor_id != owner:
        raise PolicyViolation("PERMISSION_DENIED")
    value = normalize(command.payload["policy"], state, command.project_id, owner)
    governance = copy.deepcopy(governance or {"owner_id": owner, "versions": {},
                                             "input_authority_id": context.get("input_authority_id")})
    version = value["version"]
    if version in governance["versions"]:
        raise PolicyViolation("POLICY_VERSION_CONFLICT")
    governance["versions"][version] = {"policy": value, "content_digest": digest_value(value),
                                        "configured_by": command.actor_id, "command_id": command.id}
    governance["current_version"] = version
    return {**copy.deepcopy(previous), "revision": previous["revision"] + 1,
            "observed_at_ms": at, "governance": governance}


def route(value, action, declared_risk, untrusted):
    rule = next((row for row in value["rules"] if row["action"] == action), None)
    if rule is None:
        raise PolicyViolation("POLICY_DENIED")
    if declared_risk not in RISKS:
        raise PolicyViolation("INVALID_PAYLOAD")
    level = max(RISKS.index(rule["risk_level"]), RISKS.index(ACTION_RISKS[action]), RISKS.index(declared_risk))
    if untrusted and level < 2:
        level += 1
    risk = RISKS[level]
    mode = rule["approval"]
    if value["mode"] == "manual" or risk == "critical":
        mode = "human"
    elif risk == "high":
        mode = "human" if mode != "delegated" else mode
    elif untrusted and mode == "auto" or risk == "medium" and mode == "auto":
        mode = "decision_based"
    role = "human_owner" if risk == "critical" else ("human_collaborator" if risk == "high" or mode == "human"
            else "agent_reviewer" if mode != "auto" else None)
    if mode == "delegated":
        delegate = rule["delegate"]
        if not has_role(value, delegate, role):
            raise PolicyViolation("POLICY_DENIED")
    return {"risk_level": risk, "mode": mode, "required_role": role, "rule": copy.deepcopy(rule)}
