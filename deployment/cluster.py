"""Opt-in pod entry point; local launcher and local peer restrictions stay intact."""
import json
import logging
import os
from pathlib import Path
import re

from pydantic import field_validator
from starlette.responses import JSONResponse
import uvicorn

from documents.app import create_document_app
from documents.rules import policy_network
from documents.state import DocumentSettings

PORT = 19980
NAMESPACE = 'tfi-hospital'
PEER = re.compile(r'^http://hisjb-[0-4]\.hisjb-headless\.tfi-hospital\.svc\.cluster\.local:19980$')


class ClusterSettings(DocumentSettings):
    @field_validator('peers')
    @classmethod
    def validate_peers(cls, peers):
        # Replaces only the inherited field validator in this explicit profile.
        if any(not PEER.fullmatch(p) for p in peers):
            raise ValueError('peer must be an exact HISJB StatefulSet pod in tfi-hospital')
        if len(set(peers)) != len(peers):
            raise ValueError('duplicate peer')
        return peers


class ConsoleLoopbackOnly:
    """kubectl port-forward only; spoofing Host from another pod is insufficient."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http' and (scope['path'] == '/console' or scope['path'].startswith('/console/')):
            if (scope.get('client') or ('', 0))[0] not in ('127.0.0.1', '::1'):
                return await JSONResponse({'detail': 'console requires local port-forward'}, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)


def settings_from_environment(env, shared):
    name = env['POD_NAME']
    if env.get('POD_NAMESPACE') != NAMESPACE or not re.fullmatch(r'hisjb-[0-4]', name):
        raise ValueError('unexpected pod identity or namespace')
    replicas = int(env['TFI_REPLICAS'])
    if replicas not in (1, 3, 5) or int(name.rsplit('-', 1)[1]) >= replicas:
        raise ValueError('replica count/ordinal mismatch')
    experiment = env.get('TFI_EXPERIMENT', 'demo')
    if not re.fullmatch(r'[a-z0-9-]{1,40}', experiment):
        raise ValueError('invalid experiment directory')
    difficulty = int(env.get('TFI_DIFFICULTY', '1'))
    if difficulty not in (1, 2, 3):
        raise ValueError('difficulty must be 1, 2 or 3')
    mode = env.get('TFI_DIFFICULTY_MODE', 'dynamic')
    if mode not in ('fixed', 'dynamic'):
        raise ValueError('unsupported difficulty mode')
    network = {'network_id': policy_network(shared['actors']), 'initial_difficulty': difficulty,
               'min_difficulty': difficulty if mode == 'fixed' else 1,
               'max_difficulty': difficulty if mode == 'fixed' else 3,
               'max_transactions_per_block': 256}
    return ClusterSettings(node_id=name, port=PORT, data_dir=f'/data/{experiment}',
        actors=shared['actors'], console=True, network=network,
        peers=[f'http://hisjb-{n}.hisjb-headless.{NAMESPACE}.svc.cluster.local:{PORT}'
               for n in range(replicas) if f'hisjb-{n}' != name])


def main():
    settings = settings_from_environment(os.environ, json.loads(Path('/config/actors.json').read_text()))
    credentials = json.loads(Path('/run/hisjb/credentials.json').read_text())
    app = create_document_app(settings, credentials)
    app.add_middleware(ConsoleLoopbackOnly)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    # This bind is pod-only. No ingress/LB; policy restricts traffic to this namespace.
    uvicorn.run(app, host='0.0.0.0', port=PORT, workers=1, proxy_headers=False,
                loop='asyncio', http='h11', ws='none', access_log=False,
                limit_concurrency=32, timeout_keep_alive=2, timeout_graceful_shutdown=5)


if __name__ == '__main__':
    main()
