from dataclasses import replace
import hashlib
import json
import time
from uuid import UUID
import pytest
from blockchain.chain import mine_next
from blockchain.genesis import genesis
from blockchain.transaction import Transaction
from node.settings import Settings
from node.state import NodeState, NodeError
from node.persistence import SnapshotStore, StateError

def uid(n):
    return str(UUID(int=n,version=4))

def settings(path, **kw):
    return Settings(node_id='test-node',data_dir=str(path),port=19881,network={'initial_difficulty':1},**kw)

def tx(config, n=1):
    return Transaction.create(network_hash=config.fingerprint, document_id=uid(n),version_id=uid(n+100),
       document_hash=hashlib.sha256(f'SYNTHETIC-{n}'.encode()).hexdigest(),event_type='VERSION_PREPARED',
       actor_id=uid(999),timestamp=int(time.time()*1000)-1000)

def test_atomic_restart_preserves_chain_and_mempool(tmp_path):
    opts=settings(tmp_path)
    state=NodeState(opts)
    first=tx(state.config); state.add_transaction(first); state.mine()
    second=tx(state.config,2); state.add_transaction(second)
    before=state.snapshot(); identity=state.store.path.stat()
    state.close()
    recovered=NodeState(opts)
    try:
        assert recovered.snapshot()==before
        assert recovered.pending==(second,)
        raw=json.loads(recovered.store.path.read_bytes())
        assert raw['payload']['node_id']=='test-node'
        assert raw['payload']['schema']==1
    finally:
        recovered.close()

def test_corruption_is_not_overwritten(tmp_path):
    opts=settings(tmp_path); state=NodeState(opts); path=state.store.path; state.close()
    path.write_bytes(b'{broken state')
    before=path.read_bytes()
    with pytest.raises(StateError,match='preserved'):
        NodeState(opts)
    assert path.read_bytes()==before

def test_checksum_mismatch_is_rejected(tmp_path):
    opts=settings(tmp_path); state=NodeState(opts); path=state.store.path; state.close()
    data=json.loads(path.read_bytes()); data['payload']['node_id']='changed'
    path.write_text(json.dumps(data)); before=path.read_bytes()
    with pytest.raises(StateError):
        NodeState(opts)
    assert path.read_bytes()==before

def test_second_writer_and_wrong_identity_rejected(tmp_path):
    opts=settings(tmp_path); state=NodeState(opts)
    try:
        with pytest.raises(StateError,match='writer'):
            NodeState(opts)
    finally:
        state.close()
    with pytest.raises(StateError):
        NodeState(opts.model_copy(update={'node_id':'other-node'}))

def test_failed_atomic_replace_preserves_disk_and_memory(tmp_path,monkeypatch):
    state=NodeState(settings(tmp_path)); before=state.snapshot(); raw=state.store.path.read_bytes()
    def failure(*args):
        raise OSError('injected local write failure')
    monkeypatch.setattr('node.persistence.os.replace',failure)
    try:
        with pytest.raises(NodeError) as err:
            state.add_transaction(tx(state.config))
        assert err.value.status==503
        assert (state.chain,state.pending)==before
        assert state.store.path.read_bytes()==raw
        assert not list(tmp_path.glob('.state-*.tmp'))
        assert not state.healthy
    finally:
        state.close()

def test_duplicates_before_and_after_mining(tmp_path):
    state=NodeState(settings(tmp_path)); entry=tx(state.config)
    try:
        state.add_transaction(entry)
        with pytest.raises(NodeError) as error:
            state.add_transaction(entry)
        assert error.value.status==409
        state.mine()
        with pytest.raises(NodeError):
            state.add_transaction(entry)
        assert len(state.chain[-1].transactions)==1 and not state.pending
    finally:
        state.close()

def test_miners_busy_stale_tip_and_invalid_chain(tmp_path,monkeypatch):
    state=NodeState(settings(tmp_path))
    try:
        state.miner_lock.acquire()
        with pytest.raises(NodeError,match='busy'):
            state.mine()
        state.miner_lock.release()
        original=state.snapshot()[0]
        actual=mine_next
        def concurrent_tip(chain,pending,timestamp,config,**budget):
            other=actual(chain,(),timestamp+1,config).block
            state.adopt(chain+(other,))
            return actual(chain,pending,timestamp,config,**budget)
        monkeypatch.setattr('node.state.mine_next',concurrent_tip)
        with pytest.raises(NodeError,match='tip changed'):
            state.mine()
        bad=original+(replace(state.chain[-1],hash='f'*64),)
        with pytest.raises(NodeError):
            state.adopt(bad)
        assert len(state.chain)==2
    finally:
        state.close()

def test_reorg_restores_orphaned_transactions(tmp_path):
    state=NodeState(settings(tmp_path)); entry=tx(state.config)
    try:
        state.add_transaction(entry); state.mine()
        alternate=(genesis(state.config),)
        stamp=int(time.time()*1000)-100
        for i in range(2):
            alternate+=(mine_next(alternate,(),stamp+i,state.config).block,)
        assert state.adopt(alternate)
        assert state.pending==(entry,)
        assert state.chain==alternate
    finally:
        state.close()

def test_admission_limits_future_and_mempool(tmp_path):
    state=NodeState(settings(tmp_path,max_pending=1))
    try:
        entry=tx(state.config)
        with pytest.raises(NodeError):
            future=Transaction.create(**(entry.payload()|{'timestamp':int(time.time()*1000)+60000}))
            state.add_transaction(future)
        state.add_transaction(entry)
        with pytest.raises(NodeError) as err:
            state.add_transaction(tx(state.config,2))
        assert err.value.status==429
    finally:
        state.close()

def test_api_validation_and_synthetic_document_endpoints(tmp_path):
    print('API: importing test client',flush=True)
    from fastapi.testclient import TestClient
    from node.app import create_app
    print('API: creating app',flush=True)
    app=create_app(settings(tmp_path))
    with TestClient(app) as client:
        print('API: lifespan ready, calling endpoints',flush=True)
        assert client.get('/healthz').status_code==200
        assert client.get('/blocks/999').status_code==404
        assert client.post('/transactions',json={'patient_name':'NOT ACCEPTED'}).status_code==422
        assert client.post('/transactions',content=b'x'*65537).status_code==413
        request={'fixture_id':42,'document_id':uid(1),'version_id':uid(101),'actor_id':uid(999)}
        registered=client.post('/documents/register',json=request)
        print('API: registration response',registered.status_code,flush=True)
        assert registered.status_code==202
        assert client.post('/documents/register',json=request).status_code==409
        assert client.post('/mine').status_code==200
        verified=client.post('/documents/verify',json={'document_id':uid(1),'version_id':uid(101),
                                                    'document_hash':registered.json()['document_hash']})
        assert verified.json()['integrity']=='MATCH'
        assert len(client.get('/documents/'+uid(1)+'/history').json())==1
        assert 'pow_block_height 1.0' in client.get('/metrics').text
        assert client.get('/peers').json()['peers']==[]
        assert client.post('/peers/sync').status_code==200

def test_peer_urls_are_restricted():
    for bad in ('https://example.org','http://169.254.169.254:80','http://user@127.0.0.1:1234',
                'http://127.0.0.1:1234/redirect','http://localhost:1234'):
        with pytest.raises(ValueError):
            Settings(node_id='test',data_dir='unused',port=19881,peers=[bad])
