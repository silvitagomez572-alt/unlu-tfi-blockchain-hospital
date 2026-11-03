"""Real loopback HTTP processes. Proxies only interrupt transport, never fake convergence."""
from contextlib import contextmanager
import ctypes as c
from ctypes import wintypes as w
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.request import Request, build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
from uuid import UUID
from blockchain.chain import mine_next
from blockchain.config import NetworkConfig
from blockchain.consensus import choose_best_chain
from blockchain.genesis import genesis
from blockchain.transaction import Transaction
from blockchain.validation import validate_chain
from blockchain.difficulty import next_difficulty
from node.settings import Settings
from node.persistence import SnapshotStore

ROOT=Path(__file__).resolve().parents[2]
EVIDENCE=Path(os.environ['TFI_EVIDENCE_DIR'])
opener=build_opener(ProxyHandler({}))

def write(name,data):
    (EVIDENCE/name).write_text(json.dumps(data,indent=2),encoding='utf-8')

def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        return sock.getsockname()[1]

def call(port,path,body=None):
    data=None if body is None else json.dumps(body).encode()
    req=Request(f'http://127.0.0.1:{port}'+path,data=data,headers={'Content-Type':'application/json'})
    try:
        with opener.open(req,timeout=3) as r:
            raw=r.read(4*1024*1024+1)
            return r.status,json.loads(raw) if 'json' in r.headers.get('Content-Type','') else raw.decode()
    except HTTPError as e:
        return e.code,json.loads(e.read())

def until(predicate,seconds=12):
    deadline=time.monotonic()+seconds
    last=None
    while time.monotonic()<deadline:
        try:
            last=predicate()
            if last: return last
        except (URLError,TimeoutError,ConnectionError):
            pass
        time.sleep(0.1)
    raise AssertionError(f'condition did not become true in {seconds}s; last={last!r}')

class Network:
    def __init__(self,tmp,network):
        self.tmp,self.config=tmp,NetworkConfig(**network)
        self.ports=[free_port() for _ in range(3)]
        assert len(set(self.ports))==3
        self.peers=[[] for _ in range(3)]
        self.proxies=[]; self.nodes={}; self.handles=[]; self.records=[]
        self.partition=set(); self.split_all=False; self.poison=False; self.allowed_edges=None
        self.stats={}; self.guard_error=None; self.monitor_stop=threading.Event()
        for source in range(3):
            for target in range(3):
                if source==target: continue
                handler=self.handler(source,target)
                server=ThreadingHTTPServer(('127.0.0.1',0),handler)
                server.daemon_threads=True
                thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':0.05},daemon=True)
                thread.start(); self.proxies.append((server,thread))
                self.peers[source].append(f'http://127.0.0.1:{server.server_port}')
        self.settings=[Settings(node_id=f'node-{i}',data_dir=str(tmp/f'data-{i}'),port=self.ports[i],
                               peers=self.peers[i],network=network,sync_interval_seconds=0.5) for i in range(3)]
        for i,settings in enumerate(self.settings):
            (tmp/f'node-{i}.json').write_text(settings.model_dump_json(),encoding='utf-8')
        self.monitor=threading.Thread(target=self.measure,daemon=True); self.monitor.start()

    def handler(self,source,target):
        network=self
        class Proxy(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def do_GET(self): self.forward()
            def do_POST(self): self.forward()
            def forward(self):
                blocked=(network.split_all or ((source in network.partition)!=(target in network.partition))
                         or (network.allowed_edges is not None and (source,target) not in network.allowed_edges))
                try:
                    if blocked:
                        code,body=503,b'{"detail":"test transport partition"}'
                    else:
                        length=int(self.headers.get('Content-Length','0'))
                        if length>65536: raise ValueError('body bound')
                        data=self.rfile.read(length) if self.command=='POST' else None
                        req=Request(f'http://127.0.0.1:{network.ports[target]}'+self.path,data=data,method=self.command,
                                    headers={'Content-Type':'application/json','X-TFI-Hops':self.headers.get('X-TFI-Hops','0')})
                        try:
                            with opener.open(req,timeout=1) as response:
                                code=response.status; body=response.read(4*1024*1024+1)
                        except HTTPError as exc:
                            code=exc.code; body=exc.read()
                        if network.poison and self.path=='/chain':
                            raw=json.loads(body); raw['blocks'][-1]['hash']='f'*64
                            body=json.dumps(raw).encode()  # explicit invalid-chain injection only
                    self.send_response(code); self.send_header('Content-Type','application/json')
                    self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
                except (OSError,ValueError,KeyError):
                    try:
                        body=b'{"detail":"peer unavailable"}'
                        self.send_response(503); self.send_header('Content-Type','application/json')
                        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
                    except OSError: pass
        return Proxy

    def measure(self):
        # Each child inherits its parent's Windows Job committed-memory limit.
        sys.path.insert(0,str(ROOT/'tools'))
        if sys.platform == 'linux':
            from run_consensus_linux import process_memory, CAP
            while not self.monitor_stop.wait(0.05):
                for i,proc in list(self.nodes.items()):
                    if proc.poll() is not None: continue
                    sample=process_memory(proc.pid)
                    if sample is None: continue
                    key=str(proc.pid)
                    self.stats[key]={'node':i,
                        'peak_working_set_bytes':max(sample['rss_bytes'],sample['peak_rss_bytes'],
                                                    self.stats.get(key,{}).get('peak_working_set_bytes',0)),
                        'peak_private_bytes':max(sample['private_bytes'],
                                                self.stats.get(key,{}).get('peak_private_bytes',0))}
                    if max(sample['rss_bytes'],sample['private_bytes'])>CAP:
                        self.guard_error='node memory cap exceeded'
                        proc.terminate()
            return
        from run_bounded_tests import Counters,psapi,MiB
        cap=int(os.environ.get('TFI_PROCESS_CAP_BYTES',str(192*MiB)))
        while not self.monitor_stop.wait(0.05):
            for i,proc in list(self.nodes.items()):
                if proc.poll() is not None: continue
                counters=Counters(); counters.size=c.sizeof(counters)
                if psapi.GetProcessMemoryInfo(w.HANDLE(int(proc._handle)),c.byref(counters),c.sizeof(counters)):
                    key=str(proc.pid)
                    self.stats[key]={'node':i,'peak_working_set_bytes':max(counters.peak_ws,self.stats.get(key,{}).get('peak_working_set_bytes',0)),
                                     'peak_private_bytes':max(counters.private,self.stats.get(key,{}).get('peak_private_bytes',0))}
                    if max(counters.ws,counters.private)>cap:
                        self.guard_error='node memory cap exceeded'
                        proc.terminate()

    def start(self,i):
        assert i not in self.nodes or self.nodes[i].poll() is not None
        logfile=(EVIDENCE/f'node-{i}-start-{len(self.records)}.log').open('wb'); self.handles.append(logfile)
        proc=subprocess.Popen([sys.executable,'-B','-m','node','--config',str(self.tmp/f'node-{i}.json')],
                              cwd=ROOT,stdout=logfile,stderr=subprocess.STDOUT,env=dict(os.environ))
        self.nodes[i]=proc
        self.records.append({'node':i,'pid':proc.pid,'port':self.ports[i],'started_utc_ns':time.time_ns()})
        until(lambda: proc.poll() is None and call(self.ports[i],'/healthz')[0]==200,seconds=10)
        assert call(self.ports[i],'/healthz')[1]['pid']==proc.pid

    def stop(self,i):
        proc=self.nodes[i]
        if proc.poll() is None:
            proc.terminate()  # only this test's child; models abrupt process loss
        proc.wait(timeout=3)
        self.records.append({'node':i,'pid':proc.pid,'stopped_exit_code':proc.returncode})

    def chain(self,i):
        code,body=call(self.ports[i],'/chain'); assert code==200
        return body

    def same(self,nodes=(0,1,2)):
        values=[self.chain(i) for i in nodes]
        if all(v['blocks']==values[0]['blocks'] for v in values):
            assert len({v['cumulative_work'] for v in values})==1
            return values
        return False

    def checkpoint(self,name,nodes=(0,1,2)):
        data={'chains':{str(i):self.chain(i) for i in nodes},
              'pending':{str(i):call(self.ports[i],'/transactions/pending')[1] for i in nodes},
              'peers':{str(i):call(self.ports[i],'/peers')[1] for i in nodes},'utc_ns':time.time_ns()}
        write(name+'.json',data); return data

    def close(self):
        for i in list(self.nodes):
            self.stop(i)
        self.monitor_stop.set(); self.monitor.join(timeout=2)
        for server,thread in self.proxies:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        for file in self.handles: file.close()
        for i in range(3):
            path=self.tmp/f'data-{i}'/'state.json'
            if path.exists(): (EVIDENCE/f'final-state-node-{i}.json').write_bytes(path.read_bytes())
        write('processes.json',{'events':self.records,'memory':self.stats,'guard_error':self.guard_error,
                               'active_after_cleanup':[p.pid for p in self.nodes.values() if p.poll() is None],
                               'proxy_threads_alive':[t.name for _,t in self.proxies if t.is_alive()]})
        assert self.guard_error is None

def entry(config,n):
    return Transaction.create(network_hash=config.fingerprint,document_id=str(UUID(int=n,version=4)),
        version_id=str(UUID(int=n+100,version=4)),actor_id=str(UUID(int=999,version=4)),
        document_hash=hashlib.sha256(f'SYNTHETIC-NETWORK-{n}'.encode()).hexdigest(),
        event_type='VERSION_PREPARED',timestamp=50)

def test_three_nodes_real_http_lifecycle(tmp_path):
    net=Network(tmp_path,{'initial_difficulty':1,'retarget_window':100})
    try:
        net.start(0); net.start(1)
        first=entry(net.config,1)
        assert call(net.ports[0],'/transactions',first.to_dict())[0]==202
        until(lambda:any(t['tx_id']==first.tx_id for t in call(net.ports[1],'/transactions/pending')[1]))
        assert call(net.ports[0],'/mine',{})[0]==200
        until(lambda:net.same((0,1)) and len(net.chain(1)['blocks'])==2)
        net.checkpoint('01-propagation-two-nodes',nodes=(0,1))
        net.start(2)
        until(lambda:net.same() and len(net.chain(2)['blocks'])==2)
        net.checkpoint('02-startup-sync-three-processes')
        assert len({p.pid for p in net.nodes.values()})==3

        net.partition={2}
        pending=entry(net.config,2)
        assert call(net.ports[2],'/transactions',pending.to_dict())[0]==202
        before=(tmp_path/'data-2/state.json').read_bytes()
        before_id=net.nodes[2].pid; net.stop(2); net.start(2)
        assert net.nodes[2].pid!=before_id
        assert (tmp_path/'data-2/state.json').read_bytes()==before
        assert any(t['tx_id']==pending.tx_id for t in call(net.ports[2],'/transactions/pending')[1])
        write('03-restart-persistent-directory.json',{'pid_before':before_id,'pid_after':net.nodes[2].pid,
              'path':str(tmp_path/'data-2'),'sha256_before':hashlib.sha256(before).hexdigest(),
              'sha256_after':hashlib.sha256((tmp_path/'data-2/state.json').read_bytes()).hexdigest()})
        assert call(net.ports[2],'/mine',{})[0]==200
        assert call(net.ports[0],'/mine',{})[0]==200
        assert call(net.ports[0],'/mine',{})[0]==200
        until(lambda:net.same((0,1)))
        assert net.chain(0)['blocks']!=net.chain(2)['blocks']
        net.checkpoint('04-real-partition-divergence')
        net.partition=set()
        until(lambda:net.same() and len(net.chain(2)['blocks'])==4)
        until(lambda:any(t['tx_id']==pending.tx_id for t in call(net.ports[0],'/transactions/pending')[1]))
        net.checkpoint('05-reconvergence-orphan-restored')
        assert call(net.ports[0],'/mine',{})[0]==200
        until(lambda:net.same() and len(net.chain(2)['blocks'])==5)
        assert call(net.ports[1],'/transactions',first.to_dict())[0]==409
        chain=net.chain(0)['blocks']
        ids=[t['tx_id'] for b in chain for t in b['transactions']]
        assert ids.count(first.tx_id)==1 and ids.count(pending.tx_id)==1
        good_tip=chain[-1]['hash']; net.poison=True
        until(lambda:any(e['error']=='ValueError' for e in call(net.ports[0],'/peers')[1]['sync']['errors']))
        assert net.chain(0)['tip']==good_tip
        net.checkpoint('06-invalid-peer-chain-rejected')
        net.poison=False
        until(lambda:net.same() and all(call(net.ports[i],'/peers')[1]['sync']['state']=='synced' for i in range(3)))
        net.checkpoint('07-final-equal-full-chains')
        for i in range(3):
            code,metrics=call(net.ports[i],'/metrics')
            assert code==200 and 'pow_block_height 4.0' in metrics
            (EVIDENCE/f'metrics-node-{i}.txt').write_text(metrics)
        write('assertions.json',{'independent_processes':3,'transaction_propagation':True,'block_propagation':True,
             'startup_sync':True,'persisted_chain_and_mempool':True,'real_partition':True,'reconvergence':True,
             'invalid_chain_rejected':True,'exact_replay_rejected':True,'final_height':4,'final_tip':good_tip})
    finally:
        net.close()

def prepare_consensus_fixture(net,index,stamps,tx_number):
    chain=(genesis(net.config),)
    for k,stamp in enumerate(stamps):
        chain+=(mine_next(chain,(entry(net.config,tx_number),) if k==0 else (),stamp,net.config).block,)
    validation=validate_chain(chain,net.config)
    assert validation.valid
    records=[]
    for position,block in enumerate(chain):
        computed=block.compute_hash()
        expected=next_difficulty(chain[:position],net.config)
        assert block.hash==computed
        assert block.difficulty==expected and computed.startswith('0'*expected)
        records.append({'index':position,'hash':block.hash,'recomputed_hash':computed,
                        'difficulty':block.difficulty,'expected_difficulty':expected,'work':16**expected})
    assert sum(b['work'] for b in records)==validation.cumulative_work
    path=EVIDENCE/f'original-chain-{index}.json'
    path.write_text(json.dumps([b.to_dict() for b in chain],indent=2),encoding='utf-8')
    write(f'validation-chain-{index}.json',{'valid':True,'blocks':records,
         'network_config':net.settings[0].network,'network_fingerprint':net.config.fingerprint,
         'cumulative_work':validation.cumulative_work,'original_file_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return chain

def seed_node(net,index,chain):
    store=SnapshotStore(net.settings[index].directory(),net.settings[index].node_id,net.config,256)
    try: store.save(chain,())
    finally: store.close()

def decisions(index):
    rows=[]
    for path in sorted(EVIDENCE.glob(f'node-{index}-start-*.log')):
        for line in path.read_text(errors='replace').splitlines():
            if 'fork_choice ' in line:
                rows.append(json.loads(line.split('fork_choice ',1)[1]))
    return rows

def verify_originals():
    results=[]
    for path in EVIDENCE.glob('original-chain-*.json'):
        index=path.stem.rsplit('-',1)[1]
        expected=json.loads((EVIDENCE/f'validation-chain-{index}.json').read_text())['original_file_sha256']
        actual=hashlib.sha256(path.read_bytes()).hexdigest()
        assert actual==expected
        results.append({'file':path.name,'sha256':actual,'unchanged':True})
    write('original-integrity.json',results)

def test_scenario_a_shorter_chain_with_more_work(tmp_path):
    net=Network(tmp_path,{'initial_difficulty':1,'retarget_window':2,'target_interval_ms':1000})
    net.split_all=True
    try:
        longer=prepare_consensus_fixture(net,0,[3000,6000,9000,12000,15000],10)
        shorter=prepare_consensus_fixture(net,1,[100,200,300],11)
        assert len(shorter)<len(longer)
        assert validate_chain(shorter,net.config).cumulative_work>validate_chain(longer,net.config).cumulative_work
        for i,chain in enumerate((longer,shorter,longer)): seed_node(net,i,chain)
        for i in range(3): net.start(i)
        net.checkpoint('01-independent-states')
        started=time.perf_counter()
        net.split_all=False
        until(lambda:net.same() and all(net.chain(i)['tip']==shorter[-1].hash for i in range(3)))
        elapsed=time.perf_counter()-started
        net.checkpoint('02-full-chain-convergence')
        assert all(net.chain(i)['blocks']==[b.to_dict() for b in shorter] for i in range(3))
        observed={str(i):decisions(i) for i in range(3)}
        for i in (0,2):
            assert any(d['current_tip']==longer[-1].hash and d['candidate_tip']==shorter[-1].hash
                       and d['selected_tip']==shorter[-1].hash and d['rule']=='greater_work'
                       and d['adopted'] for d in observed[str(i)])
        assert all(d['selected_tip']==shorter[-1].hash for d in observed['1'])
        write('fork-choice-decisions.json',observed)
        verify_originals()
        write('assertions.json',{'scenario':'A','real_processes':3,'status':'PASS',
             'longer_height':longer[-1].index,'longer_work':validate_chain(longer,net.config).cumulative_work,
             'selected_height':shorter[-1].index,'selected_work':validate_chain(shorter,net.config).cumulative_work,
             'selected_tip':shorter[-1].hash,'full_chains_equal':True,'observed_sync_seconds':elapsed,
             'polling_interval_seconds':0.1,'fixture_note':'Valid chains premined locally; adoption by real HTTP nodes'})
    finally:
        net.close()

def test_scenario_b_equal_work_reversed_arrival(tmp_path):
    net=Network(tmp_path,{'initial_difficulty':1,'retarget_window':2,'target_interval_ms':1000})
    net.split_all=True
    try:
        a=prepare_consensus_fixture(net,0,[100,200,300],20)
        b=prepare_consensus_fixture(net,1,[100,200,301],21)
        assert validate_chain(a,net.config).cumulative_work==validate_chain(b,net.config).cumulative_work
        winner,loser=sorted((a,b),key=lambda c:c[-1].hash)
        for i,chain in enumerate((winner,loser,winner)): seed_node(net,i,chain)
        for i in range(3): net.start(i)
        net.checkpoint('01-independent-tied-forks')
        first_start=time.perf_counter(); net.allowed_edges={(0,1),(2,1)}; net.split_all=False
        def compared(i,current,candidate):
            return [d for d in decisions(i) if d['current_tip']==current[-1].hash and d['candidate_tip']==candidate[-1].hash]
        until(lambda:compared(0,winner,loser) and compared(2,winner,loser))
        first_elapsed=time.perf_counter()-first_start
        # The losing fork remains live on node 1 until it receives the winner second.
        assert net.chain(1)['tip']==loser[-1].hash
        second_start=time.perf_counter(); net.allowed_edges={(1,0)}
        until(lambda:compared(1,loser,winner))
        second_elapsed=time.perf_counter()-second_start
        net.allowed_edges=None
        convergence_start=time.perf_counter()
        until(lambda:net.same() and all(net.chain(i)['tip']==winner[-1].hash for i in range(3)))
        convergence_elapsed=time.perf_counter()-convergence_start
        net.checkpoint('02-opposite-arrival-full-chain-convergence')
        orders={'0':compared(0,winner,loser)[0],'1':compared(1,loser,winner)[0],
                '2':compared(2,winner,loser)[0]}
        assert all(d['selected_tip']==winner[-1].hash and d['rule']=='lexicographic_tip' for d in orders.values())
        assert all(net.chain(i)['blocks']==[b.to_dict() for b in winner] for i in range(3))
        write('fork-choice-decisions.json',{str(i):decisions(i) for i in range(3)})
        write('arrival-orders.json',orders); verify_originals()
        write('assertions.json',{'scenario':'B','status':'PASS','real_processes':3,
             'equal_work':validate_chain(winner,net.config).cumulative_work,
             'winner_tip':winner[-1].hash,'loser_tip':loser[-1].hash,'full_chains_equal':True,
             'arrival_orders_verified':True,'winner_first_observed_seconds':first_elapsed,
             'loser_first_observed_seconds':second_elapsed,'after_healing_observed_seconds':convergence_elapsed,
             'polling_interval_seconds':0.1,'limitation':'Controlled directed-link schedule; not an exhaustive message-order proof'})
    finally:
        net.close()
