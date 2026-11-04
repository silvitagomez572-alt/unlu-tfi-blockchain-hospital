"""Loopback-only profile launcher. Ephemeral credentials come from environment."""
import argparse
import json
import logging
import os
from pathlib import Path
import uvicorn
from .app import create_document_app
from .state import DocumentSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    settings = DocumentSettings.model_validate_json(Path(args.config).read_bytes())
    credentials = json.loads(os.environ['TFI_DOCUMENT_CREDENTIALS'])
    app = create_document_app(settings, credentials)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    uvicorn.run(app, host='127.0.0.1', port=settings.port, workers=1, loop='asyncio', http='h11',
                ws='none', access_log=False, timeout_keep_alive=2, timeout_graceful_shutdown=3, limit_concurrency=16)


if __name__ == '__main__':
    main()
