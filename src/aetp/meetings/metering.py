"""Trusted-host local admission capabilities, not provider usage or payment receipts."""

import threading
import uuid
from dataclasses import asdict, dataclass

from aetp.collaboration.policy import PolicyViolation, text
from aetp.meetings.policy import natural
from aetp.meetings.records import Contribution


@dataclass(frozen=True, slots=True)
class UsageReceipt:
    receipt_id: str
    source_id: str
    call_id: str
    subject_digest: str
    tokens: int
    purpose: str = "process_admission"
    unit: str = "token"


class MeteringAuthority:
    """Install/issue only through the trusted host, outside Agent input APIs.

    Strong object references prevent copied capabilities. Actual consumption is
    recorded in SQLite by (source_id, call_id), never in this process registry.
    Issuing a capability does not call a provider or report incurred charges.
    """

    def __init__(self, source_id):
        self.source_id = text(source_id, identifier=True, limit=512)
        self._issued = {}
        self._lock = threading.RLock()

    def issue(self, contribution, *, call_id, tokens):
        if not isinstance(contribution, Contribution):
            raise TypeError("Contribution required")
        try:
            natural(tokens, 1000000, positive=True)
            text(call_id, identifier=True, limit=512)
        except PolicyViolation as exc:
            raise ValueError("invalid admission token count or call ID") from exc
        receipt = UsageReceipt(uuid.uuid4().hex, self.source_id, call_id, contribution.digest(), tokens)
        with self._lock:
            self._issued[receipt.receipt_id] = receipt
        return receipt

    def verify(self, contribution, receipt):
        with self._lock:
            if (not isinstance(receipt, UsageReceipt) or self._issued.get(receipt.receipt_id) is not receipt
                    or receipt.source_id != self.source_id or receipt.subject_digest != contribution.digest()
                    or receipt.purpose != "process_admission" or receipt.unit != "token"):
                raise PolicyViolation("INVALID_USAGE_RECEIPT")
            return asdict(receipt)
