import argparse
import os
import uvicorn
from .app import create_gateway

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--node-url',required=True)
    parser.add_argument('--port',type=int,default=19980)
    args=parser.parse_args()
    if not 1024<=args.port<=65535: parser.error('port out of range')
    key=os.environ.get('TFI_GATEWAY_ADMIN_KEY','')
    app=create_gateway(args.database,args.node_url,f'http://127.0.0.1:{args.port}',key)
    uvicorn.run(app,host='127.0.0.1',port=args.port,workers=1,access_log=False,
                limit_concurrency=16,timeout_keep_alive=2,ws='none')

if __name__=='__main__': main()
