import argparse
import json
import logging
from pathlib import Path
import uvicorn
from .settings import Settings
from .app import create_app

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    args = parser.parse_args()
    settings = Settings.model_validate_json(Path(args.config).read_bytes())
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    logging.info('node=%s port=%s network=%s',settings.node_id,settings.port,settings.config().fingerprint)
    uvicorn.run(create_app(settings),host='127.0.0.1',port=settings.port,workers=1,
                loop='asyncio',http='h11',ws='none',access_log=False,timeout_keep_alive=2,
                timeout_graceful_shutdown=3,limit_concurrency=16)

if __name__ == '__main__':
    main()
