"""Complete candidate DAG validation and deterministic impact analysis."""

import copy

from aetp.collaboration.policy import (
    PolicyViolation,
    canonical_json,
    digest_value,
    strings,
    text,
)
from aetp.governance.policy import fields
from aetp.planning.references import decisions, resolve


def artifact_reference(value, state, project_id):
    fields(value, {"type", "id", "content_digest"}, {"type", "id", "content_digest"})
    identifier = text(value["id"], identifier=True, limit=512)
    record = state.get(f"artifact:{identifier}")
    if value["type"] != "artifact" or record is None or record["project_id"] != project_id:
        raise PolicyViolation("INVALID_REFERENCE")
    if value["content_digest"] != record["content_digest"]:
        raise PolicyViolation("REFERENCE_STALE")


def blueprint_content(value, state, project_id, version):
    required = {"mission", "team", "requirements", "architecture", "technology", "components",
                "milestones", "tasks", "risks", "acceptance_criteria"}
    fields(value, required, required)
    resolve(value["mission"], state, project_id, "mission")
    team = resolve(value["team"], state, project_id, "team")
    if team["content"]["mission"] != value["mission"]:
        raise PolicyViolation("INVALID_REFERENCE")
    text(value["architecture"])
    for field in ("requirements", "technology", "components", "risks", "acceptance_criteria"):
        strings(value[field], required=field != "risks")
    milestones = value["milestones"]
    if not isinstance(milestones, list) or not 1 <= len(milestones) <= 64:
        raise PolicyViolation("INVALID_DAG")
    milestone_ids = set()
    for milestone in milestones:
        fields(milestone, {"id", "title"}, {"id", "title"})
        identifier = text(milestone["id"], identifier=True, limit=512)
        text(milestone["title"], limit=512)
        if identifier in milestone_ids:
            raise PolicyViolation("INVALID_DAG")
        milestone_ids.add(identifier)
    tasks = value["tasks"]
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 128:
        raise PolicyViolation("INVALID_DAG")
    by_id = {}
    for task in tasks:
        required = {"id", "title", "type", "milestone_id", "required_capabilities", "dependencies", "inputs",
                    "expected_outputs", "acceptance_criteria"}
        fields(task, required, required)
        identifier = text(task["id"], identifier=True, limit=512)
        if identifier in by_id or task["milestone_id"] not in milestone_ids:
            raise PolicyViolation("INVALID_DAG")
        by_id[identifier] = task
        text(task["title"], limit=512)
        text(task["type"], identifier=True, limit=128)
        for field in ("required_capabilities", "expected_outputs", "acceptance_criteria"):
            strings(task[field], required=True)
        for field in ("dependencies", "inputs"):
            if not isinstance(task[field], list) or len(task[field]) > 128:
                raise PolicyViolation("INVALID_DAG")
        if len({canonical_json(ref) for ref in task["inputs"]}) != len(task["inputs"]):
            raise PolicyViolation("INVALID_DAG")
        for ref in task["inputs"]:
            artifact_reference(ref, state, project_id)
    parents, successors = {key: set() for key in by_id}, {key: set() for key in by_id}
    decision_dependencies = []
    for identifier, task in by_id.items():
        seen = set()
        for dependency in task["dependencies"]:
            if not isinstance(dependency, dict):
                raise PolicyViolation("INVALID_DEPENDENCY")
            token = canonical_json(dependency)
            if token in seen:
                raise PolicyViolation("INVALID_DAG")
            seen.add(token)
            if dependency.get("type") == "task":
                fields(dependency, {"type", "id"}, {"type", "id"})
                parent = text(dependency["id"], identifier=True, limit=512)
                if parent not in by_id:
                    raise PolicyViolation("INVALID_DEPENDENCY")
                parents[identifier].add(parent)
                successors[parent].add(identifier)
            elif dependency.get("type") == "decision":
                proof = decisions([dependency], state, project_id)[0]
                decision_dependencies.append({"task_id": identifier, **proof})
            else:
                raise PolicyViolation("INVALID_DEPENDENCY")
    remaining = {key: set(value) for key, value in parents.items()}
    layers, ordered = [], []
    while remaining:
        ready = sorted(key for key, dependencies in remaining.items() if not dependencies)
        if not ready:
            raise PolicyViolation("DAG_CYCLE")
        layers.append(ready)
        ordered.extend(ready)
        for key in ready:
            del remaining[key]
        for dependencies in remaining.values():
            dependencies.difference_update(ready)
    edges = [{"from": parent, "to": child} for child in sorted(parents) for parent in sorted(parents[child])]
    dag = {"version": version, "task_ids": sorted(by_id), "edges": edges, "layers": layers,
           "topological_order": ordered,
           "decision_dependencies": sorted(decision_dependencies, key=lambda item: (item["task_id"], item["reference"]["id"])),
           "content_digest": digest_value({"version": version, "tasks": tasks})}
    return copy.deepcopy(value), dag


def impact(old, new, state, project_id, declaration):
    before = {task["id"]: task for task in old["tasks"]}
    after = {task["id"]: task for task in new["tasks"]}
    changed = {key for key in before.keys() | after.keys() if canonical_json(before.get(key)) != canonical_json(after.get(key))}
    # Requirements, architecture, technology and acceptance changes potentially
    # affect every task, not only the edited task row.
    if any(canonical_json(old[key]) != canonical_json(new[key]) for key in old.keys() - {"tasks", "risks"}):
        changed.update(before.keys() | after.keys())
    all_tasks = list(before.values()) + list(after.values())
    affected = set(changed)
    while True:
        downstream = {task["id"] for task in all_tasks if any(
            dep["type"] == "task" and dep["id"] in affected for dep in task["dependencies"])}
        if downstream <= affected:
            break
        affected.update(downstream)
    artifacts, decision_ids, dependencies = set(), set(), {}
    for task in all_tasks:
        if task["id"] not in affected:
            continue
        artifacts.update(ref["id"] for ref in task["inputs"])
        for dependency in task["dependencies"]:
            if dependency["type"] == "decision":
                decision_ids.add(dependency["id"])
            entry = {"task_id": task["id"], "dependency": copy.deepcopy(dependency)}
            dependencies[canonical_json(entry)] = entry
    members = set()
    for content in (old, new):
        team = resolve(content["team"], state, project_id, "team", latest=False)
        members.update(member["agent_id"] for member in team["content"]["members"])
    return {"scope": "candidate_graph_only", "changed_tasks": sorted(changed), "affected_tasks": sorted(affected),
            "affected_artifacts": sorted(artifacts), "affected_decisions": sorted(decision_ids),
            "affected_dependencies": [dependencies[key] for key in sorted(dependencies)],
            "affected_team_members": sorted(members), "risk_level": declaration["risk_level"],
            "estimated_cost": copy.deepcopy(declaration["estimated_cost"]),
            "estimated_delay_ms": declaration["estimated_delay_ms"], "estimates_are": "proposer_declarations"}
