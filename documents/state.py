"""Document policy guards every state transition; persistence/fork choice are reused."""
import logging
from pydantic import Field, model_validator
from node.settings import Settings
from node.state import NodeState, NodeError
from .rules import DocumentConflict, policy_network, project, validate_next, validate_pending

LOG = logging.getLogger('tfi.document')


class DocumentSettings(Settings):
    actors: dict[str, str]
    console: bool = False

    @model_validator(mode='after')
    def document_network(self):
        expected = policy_network(self.actors)
        if self.network.get('network_id') != expected:
            raise ValueError('explicit document policy network_id required')
        return self


class DocumentState(NodeState):
    def __init__(self, settings):
        super().__init__(settings)
        try:
            records = project(self.chain, settings.actors, self.config)
            validate_pending(self.pending, records, settings.actors, self.config)
        except BaseException:
            self.close()
            raise

    def add_transaction(self, tx):
        with self.lock:
            self.ensure_healthy()
            try:
                records = project(self.chain, self.settings.actors, self.config)
                validate_pending(self.pending + (tx,), records, self.settings.actors, self.config)
            except DocumentConflict as exc:
                raise NodeError(409, str(exc)) from exc
            return super().add_transaction(tx)

    def register_transaction(self, tx):
        return self.add_transaction(tx)

    def adopt(self, candidate):
        try:
            project(candidate, self.settings.actors, self.config)
        except DocumentConflict as exc:
            raise NodeError(422, 'candidate violates documentary policy') from exc
        return super().adopt(candidate)

    def commit(self, chain, pending):
        records = project(chain, self.settings.actors, self.config)
        if chain != self.chain:
            # Original consensus decides the chain. Only application mempool admission
            # is reconciled: later orphan stages require a confirmed predecessor again.
            accepted, seen = [], set()
            for tx in sorted(pending, key=lambda t: (t.timestamp, t.tx_id)):
                try:
                    if tx.document_id in seen:
                        raise DocumentConflict('pending conflict')
                    validate_next(tx, records, self.settings.actors, self.config)
                except DocumentConflict:
                    LOG.info('pending_readmission node=%s tx_id=%s result=deferred', self.settings.node_id, tx.tx_id)
                    continue
                accepted.append(tx)
                seen.add(tx.document_id)
            pending = tuple(accepted)
        validate_pending(pending, records, self.settings.actors, self.config)
        return super().commit(chain, pending)
