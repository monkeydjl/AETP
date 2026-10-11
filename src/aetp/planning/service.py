"""Trusted planning host using the common atomic Command acceptance path."""

import copy

from aetp.collaboration.policy import PolicyViolation, text
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from aetp.governance.service import GovernanceService
from aetp.meetings.policy import natural
from aetp.meetings.records import require_member
from aetp.planning.contracts import AGGREGATES, COMMAND_AGGREGATES, SCHEMA
from aetp.planning.records import evaluate
from aetp.runtime.policy import observed_time


class PlanningService(GovernanceService):
    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        state = Projection.rebuild(self.store.read_events(command.project_id))
        try:
            at = observed_time(state, self.clock())
            kind, record = evaluate(command, state, at)
            payload = {"planning_schema": SCHEMA, "command": command.to_dict(), "observed_at_ms": at, "record": record}
            return self._batch(command, state, [(kind, COMMAND_AGGREGATES[command.type], command.target_id,
                                                record["revision"], payload)])
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, KeyError, TypeError, ValueError):
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def candidate(self, project_id, kind, identifier, *, version=None, authenticated_actor_id):
        with self.store.transaction():
            state = Projection.rebuild(self.store.read_events(project_id))
            require_member(state, project_id, self._authenticated_actor(authenticated_actor_id))
            if not isinstance(kind, str) or kind not in AGGREGATES:
                raise PolicyViolation("INVALID_TARGET")
            text(identifier, identifier=True, limit=512)
            record = state.get(f"{kind}:{identifier}")
            if record is None:
                raise PolicyViolation("INVALID_TARGET")
            version = record["latest_proposal_version"] if version is None else natural(version, positive=True)
            result = record["versions"].get(str(version))
            if result is None:
                raise PolicyViolation("INVALID_REFERENCE")
            return copy.deepcopy(result)

    def preview(self, project_id, blueprint_id, *, version=None, authenticated_actor_id):
        from aetp.planning.preview import build
        # Candidate, references and current approval time come from one snapshot.
        with self.store.transaction():
            candidate = self.candidate(project_id, "blueprint", blueprint_id, version=version,
                                       authenticated_actor_id=authenticated_actor_id)
            state = Projection.rebuild(self.store.read_events(project_id))
            return build(candidate, state, observed_time(state, self.clock()))
