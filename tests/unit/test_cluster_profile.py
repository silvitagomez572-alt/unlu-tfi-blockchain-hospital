"""New deployment boundary coverage; does not rerun the approved engine suite."""
import asyncio
from uuid import uuid4
import pytest
from deployment.cluster import ClusterSettings, ConsoleLoopbackOnly, settings_from_environment
from documents.state import DocumentSettings


def test_cluster_isolation_and_configuration():
    actors = {'actors': {k: str(uuid4()) for k in ('mesa', 'direccion', 'legal', 'bio')}}
    env = {'POD_NAME': 'hisjb-0', 'POD_NAMESPACE': 'tfi-hospital', 'TFI_REPLICAS': '3'}
    s = settings_from_environment(env, actors)
    assert s.port == 19980 and s.node_id == 'hisjb-0' and len(s.peers) == 2
    assert all('hisjb-0.' not in p for p in s.peers)
    assert s.directory().as_posix().endswith('/data/demo')
    assert s.network['min_difficulty'] == 1 and s.network['max_difficulty'] == 3
    for n in (1, 3, 5):
        assert len(settings_from_environment(env | {'TFI_REPLICAS': str(n)}, actors).peers) == n - 1
    for difficulty in (1, 2, 3):
        fixed = settings_from_environment(env | {'TFI_DIFFICULTY': str(difficulty), 'TFI_DIFFICULTY_MODE': 'fixed'}, actors)
        assert fixed.config().min_difficulty == fixed.config().max_difficulty == difficulty
    for change in ({'POD_NAMESPACE': 'bc-clase8'}, {'POD_NAME': 'other-0'}, {'TFI_REPLICAS': '2'},
                   {'POD_NAME': 'hisjb-4'}, {'TFI_EXPERIMENT': '../other'}, {'TFI_DIFFICULTY': '6'}):
        with pytest.raises(ValueError):
            settings_from_environment(env | change, actors)
    for peer in ('http://metadata.google.internal:19980', 'http://127.0.0.1:19980',
                 'http://hisjb-1.hisjb-headless.tfi-hospital.svc.cluster.local:19980.evil',
                 'http://hisjb-1.hisjb-headless.bc-clase8.svc.cluster.local:19980'):
        with pytest.raises(ValueError):
            ClusterSettings.model_validate(s.model_dump() | {'peers': [peer]})
    with pytest.raises(ValueError):
        DocumentSettings.model_validate(s.model_dump())  # local profile still rejects pod DNS

    async def exercise(ip):
        sent, called = [], []
        async def app(scope, receive, send):
            called.append(True)
        async def receive():
            return {'type': 'http.request', 'body': b''}
        async def send(message):
            sent.append(message)
        await ConsoleLoopbackOnly(app)({'type': 'http', 'path': '/console/', 'client': (ip, 1)}, receive, send)
        return called, sent
    called, denied = asyncio.run(exercise('10.73.0.2'))
    assert not called and denied[0]['status'] == 403
    called, sent = asyncio.run(exercise('127.0.0.1'))
    assert called and not sent
