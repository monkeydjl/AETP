"""Tamper tests start from real accepted declarations, not candidate State."""
import copy
import unittest
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch
from aetp.collaboration.policy import digest_value
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import ModelValidationError
from tests.m3.integration_live_support import IntegrationCase, IntegrationContractService
from tests.m3.test_task_quality_replay import GUARDS

class IntegrationReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if IntegrationContractService is None: return
        fixture=IntegrationCase()
        try:
            fixture.setUp()
            cls.base_events=fixture.store.read_events("p-1")
            fixture.declare()
            fixture.declare(version=2, reason="Second intent")
            fixture.service.handle(fixture.merge(),authenticated_actor_id="a-1")
            cls.events=fixture.store.read_events("p-1")
            cls.persisted=fixture.commands()
            cls.expected=fixture.state()
        finally: fixture.doCleanups()

    def setUp(self):
        self.assertIsNotNone(IntegrationContractService,"Real Integration declaration service is missing")
        self.first=next(i for i,e in enumerate(self.events) if e.type=="project.integration_declared")
        self.second=next(i for i,e in enumerate(self.events) if e.type=="project.integration_declared" and i>self.first)

    def reject(self,index,event):
        projection=Projection()
        for prior in self.events[:index]: projection.apply(prior)
        names=("_governance_cursor","_planning_cursor","_acceptance_cursor","_quality_cursor","_integration_cursor")
        cursors={name:getattr(projection,name) for name in names}
        state,seen=projection.state,dict(projection._seen)
        with self.assertRaises(ModelValidationError): projection.apply(event)
        self.assertEqual(projection.state,state)
        self.assertEqual(projection._seen,seen)
        self.assertEqual(projection.last_sequence,index)
        for name,cursor in cursors.items(): self.assertIs(getattr(projection,name),cursor)
        for original in self.events[index:]: projection.apply(original)
        self.assertEqual(projection.state,self.expected)

    def altered(self,index,**changes):
        event=self.events[index]; payload=copy.deepcopy(event.payload);payload.update(changes)
        return replace(event,payload=payload)

    def test_every_prefix_rebuild_and_pending_are_pure(self):
        with ExitStack() as stack:
            calls=[stack.enter_context(patch(name,side_effect=AssertionError(name))) for name in GUARDS]
            current=Projection()
            for i,event in enumerate(self.events,1):
                current.apply(event)
                self.assertEqual(Projection.rebuild(self.events[:i]),current.state)
                commands=[c for c in self.persisted if c.id in {e.causation_id for e in self.events[:i]}]
                pending=Projection.pending_command_ids(self.events[:i],commands)
                if event.type=="command.received" and event.payload["command_type"] in {"project.integration.declare","git.merge"}:
                    self.assertIn(event.causation_id,pending)
            self.assertEqual(Projection.pending_command_ids(self.events,self.persisted),[])
            for call in calls: call.assert_not_called()
        self.assertNotIn("integration_contract",Projection.rebuild(self.base_events)["project:p-1"])

    def test_receipt_revision_address_digest_and_scope_are_bound(self):
        index=self.first-1; event=self.events[index]
        for changed in (replace(event,aggregate_revision=event.aggregate_revision+1),
                        replace(event,aggregate_type="task"),
                        self.altered(index,request_digest="A"*64),self.altered(index,request_digest=True),
                        self.altered(index,extra=True)):
            with self.subTest(changed=changed): self.reject(index,changed)
        # A different well-formed digest/address/correlation cannot authorize the following effect.
        for changed in (self.altered(index,request_digest="0"*64),replace(event,aggregate_id="another-project",aggregate_revision=0),
                        replace(event,correlation_id="other")):
            stream=[*self.events[:index],changed,*self.events[index+1:]]
            with self.assertRaises(ModelValidationError): Projection.rebuild(stream)

    def test_effect_identity_scope_and_causation_are_bound(self):
        e=self.events[self.first]
        for changes in ({"aggregate_id":"other"},{"aggregate_type":"task"},{"correlation_id":"other"},
                        {"causation_id":"other"},{"aggregate_revision":e.aggregate_revision+1}):
            with self.subTest(changes=changes): self.reject(self.first,replace(e,**changes))

    def test_exact_envelope_schema_index_count_and_json_types(self):
        for change in ({"effect_index":True},{"effect_index":1},{"effect_count":True},{"effect_count":2},
                       {"integration_schema":None},{"integration_schema":"future"},{"extra":0}):
            with self.subTest(change=change): self.reject(self.first,self.altered(self.first,**change))
        payload=copy.deepcopy(self.events[self.first].payload);payload.pop("integration_schema")
        self.reject(self.first,replace(self.events[self.first],payload=payload))

    def test_full_record_and_resealed_history_cannot_be_forged(self):
        for index in (self.first,self.second):
            for field,value in (("declared_by","a-1"),("task_revision",True),("reason","forged")):
                payload=copy.deepcopy(self.events[index].payload)
                record=payload["record"]["integration_contract"]["tasks"]["t-1"]["versions"]["1"]
                record[field]=value
                record["content_digest"]=digest_value({k:v for k,v in record.items() if k!="content_digest"})
                with self.subTest(index=index,field=field): self.reject(index,replace(self.events[index],payload=payload))
        record=copy.deepcopy(self.events[self.first].payload["record"]);record["status"]="completed"
        self.reject(self.first,self.altered(self.first,record=record))

    def test_context_and_command_cannot_change_under_same_receipt(self):
        for key,value in (("actor_id","human-peer"),("expected_revision",0),("id","other"),("idempotency_key","other")):
            command=copy.deepcopy(self.events[self.first].payload["command"]);command[key]=value
            self.reject(self.first,self.altered(self.first,command=command))
        context=copy.deepcopy(self.events[self.first].payload["context"])
        context["input_proof"]["exposure"]="untrusted"
        self.reject(self.first,self.altered(self.first,context=context))

    def test_missing_and_duplicate_receipts_and_second_terminal_fail(self):
        index=self.first-1
        removed=[replace(e,sequence=i) for i,e in enumerate(self.events[:index]+self.events[index+1:],1)]
        with self.assertRaises(ModelValidationError): Projection.rebuild(removed)
        projection=Projection()
        for e in self.events[:self.first+1]: projection.apply(e)
        for e in (self.events[index],self.events[self.first]):
            with self.assertRaises(ModelValidationError): projection.apply(replace(e,id="duplicate-new-id",sequence=projection.last_sequence+1))
        before=projection.state
        projection.apply(self.events[self.first])
        self.assertEqual(projection.state,before) # exact redelivery is idempotent

    def test_merge_receipt_cannot_have_a_declaration_success(self):
        index=len(self.events)-1
        payload=copy.deepcopy(self.events[self.second].payload)
        payload["command"]=next(c.to_dict() for c in self.persisted if c.type=="git.merge")
        self.reject(index,replace(self.events[index],type="project.integration_declared",payload=payload))

    def test_rejection_address_revision_and_exact_typed_error(self):
        index=len(self.events)-1;event=self.events[index]
        for changed in (replace(event,aggregate_id="other"),replace(event,aggregate_revision=0),
                        self.altered(index,error={"code":"X"}),self.altered(index,error={"code":True}),
                        self.altered(index,integration_schema="aetp-integration-contract-1")):
            with self.subTest(changed=changed):self.reject(index,changed)
        payload=copy.deepcopy(event.payload);payload["error"]["context"]["command_id"]="other"
        self.reject(index,replace(event,payload=payload))

    def test_supported_schema_is_forbidden_in_audit_and_unrelated_domain(self):
        for index in (0,self.first-1,len(self.events)-1):
            self.reject(index,self.altered(index,integration_schema="aetp-integration-contract-1"))

    def test_non_declaration_project_effect_cannot_erase_history(self):
        event=self.events[self.second]
        record=copy.deepcopy(event.payload["record"]);record.pop("integration_contract")
        self.reject(self.second,self.altered(self.second,record=record))

    def test_cursor_failure_after_reduction_publishes_nothing(self):
        import aetp.integration.causality as causality
        projection=Projection()
        for event in self.events[:self.first]:projection.apply(event)
        before=projection.state;cursor=projection._integration_cursor
        with patch.object(causality.IntegrationCursor,"advance",side_effect=ModelValidationError("injected")):
            with self.assertRaises(ModelValidationError):projection.apply(self.events[self.first])
        self.assertEqual(projection.state,before);self.assertIs(projection._integration_cursor,cursor)
        projection.apply(self.events[self.first])
        self.assertIn("integration_contract",projection.state["project:p-1"])

    def test_cached_state_never_replaces_causal_history(self):
        with self.assertRaises(ValueError):Projection._from_cache("p-1",self.expected,len(self.events))

    def test_full_store_command_comparison_rejects_changed_original(self):
        command=next(c for c in self.persisted if c.type=="project.integration.declare")
        altered=[replace(c,idempotency_key="forged") if c.id==command.id else c for c in self.persisted]
        with self.assertRaises(ModelValidationError):Projection.pending_command_ids(self.events,altered)

    def test_full_store_rejection_expected_revision_matches_original_command(self):
        event = self.events[-1]
        self.assertEqual(event.type, "command.rejected")
        payload = copy.deepcopy(event.payload)
        payload["error"]["context"]["expected_revision"] += 1
        stream = [*self.events[:-1], replace(event, payload=payload)]
        # Events-only has no rejected Command body, so cannot infer this value.
        self.assertEqual(Projection.rebuild(stream), self.expected)
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(stream, self.persisted)
