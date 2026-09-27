#!/usr/bin/env python3
"""
Deploy the Pond Catchment service on the four lab systems (run from your PC).

  Sys1 : pond_lb load balancer (public entry)  +  analysis worker
  Sys2 : analysis worker
  Sys3 : analysis worker
  Sys4 : analysis worker

Usage
  pip install paramiko
  python cluster/deploy_cluster.py            # deploy everything
  python cluster/deploy_cluster.py --status   # only print LB stats

Edit CONFIG below if your ports / IPs differ. The SSH password is read from the
POND_SSH_PASS environment variable, or asked for interactively.
"""
import argparse
import getpass
import io
import json
import os
import sys
import tarfile
import time
import urllib.request

import paramiko

CONFIG = {
    'host': '10.1.75.51',
    'user': 'student',
    # SSH port of each system (same allotment as Lab 6)
    'ssh_ports': {'sys1': 2237, 'sys2': 2238, 'sys3': 2239, 'sys4': 2240},
    # private IP of each worker as seen from Sys1 (Sys1 reaches its own worker on loopback)
    'worker_ips': {'sys1': '127.0.0.1', 'sys2': '172.17.0.39', 'sys3': '172.17.0.40', 'sys4': '172.17.0.41'},
    'worker_port': 5002,
    # Port the LB listens on inside Sys1. It must be the port that the campus NAT
    # publishes as the public URL (Phase 1 used http://10.1.75.51:5237).
    'lb_port': 5000,
    'public_url': 'http://10.1.75.51:5237',
}

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ['app.py', 'kml_parser.py', 'terrain_analyzer.py', 'requirements.txt', 'contours_1m.kml',
         'templates', 'static', 'cluster/gunicorn.conf.py', 'cluster/start_worker.sh',
         'cluster/start_lb.sh', 'cluster/locustfile.py']


def bundle():
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as tar:
        for f in FILES:
            tar.add(os.path.join(ROOT, f), arcname=f)
    return buf.getvalue()


def ssh(port, password):
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(CONFIG['host'], port=port, username=CONFIG['user'], password=password, timeout=15)
    return c


def run(c, cmd, tag):
    _, out, err = c.exec_command(cmd, get_pty=True)
    for line in iter(out.readline, ''):
        print(f'  [{tag}] {line.rstrip()}')
    return out.channel.recv_exit_status()


def deploy_node(name, password, tarball):
    print(f'=== {name} (ssh :{CONFIG["ssh_ports"][name]}) ===')
    c = ssh(CONFIG['ssh_ports'][name], password)
    sftp = c.open_sftp()
    sftp.putfo(io.BytesIO(tarball), 'pond_app.tar.gz')
    if name == 'sys1':
        sftp.put(os.path.join(ROOT, 'cluster', 'pond_lb'), 'pond_lb.bin')
    sftp.close()
    run(c, 'mkdir -p ~/pond && tar xzf ~/pond_app.tar.gz -C ~/pond && '
           'chmod +x ~/pond/cluster/*.sh && '
           + ('mv -f ~/pond_lb.bin ~/pond/cluster/pond_lb && ' if name == 'sys1' else '')
           + 'echo cores=$(nproc)', name)
    _, out, _ = c.exec_command('nproc')
    cores = int(out.read().decode().strip() or 1)
    # Sys1 also runs the LB → keep one core free for it
    workers = max(1, cores - 1) if name == 'sys1' else max(1, cores)
    code = run(c, f'WORKER_PORT={CONFIG["worker_port"]} bash ~/pond/cluster/start_worker.sh {name} {workers}', name)
    c.close()
    return code == 0, workers


def start_lb(password, max_inflight):
    print('=== Sys1 load balancer ===')
    backends = ','.join(f'http://{ip}:{CONFIG["worker_port"]}' for ip in CONFIG['worker_ips'].values())
    c = ssh(CONFIG['ssh_ports']['sys1'], password)
    code = run(c, f'bash ~/pond/cluster/start_lb.sh {CONFIG["lb_port"]} {backends} {max_inflight}', 'sys1-lb')
    c.close()
    return code == 0


def status():
    url = CONFIG['public_url'] + '/lb/stats'
    try:
        d = json.load(urllib.request.urlopen(url, timeout=5))
        print(f'LB {url}: healthy backends {d["healthy_backends"]}/{len(d["backends"])}, '
              f'requests {d["total_requests"]}, shed {d["shed_503"]}')
        for k, v in d['backends'].items():
            print(f'   {k:32s} healthy={v["healthy"]} served={v["served"]} ewma={v["ewma_latency_ms"]}ms')
    except Exception as e:
        print(f'Could not reach {url}: {e}\n'
              f'  → if the LB started fine on Sys1, the public port may map to a different internal port; '
              f'set CONFIG["lb_port"] accordingly.')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--status', action='store_true')
    ap.add_argument('--nodes', nargs='+', default=['sys1', 'sys2', 'sys3', 'sys4'])
    a = ap.parse_args()
    if a.status:
        return status()
    if not os.path.exists(os.path.join(ROOT, 'cluster', 'pond_lb')):
        sys.exit('cluster/pond_lb binary missing — build it: cd cluster && GOOS=linux GOARCH=amd64 go build -o pond_lb .')
    pw = os.environ.get('POND_SSH_PASS') or getpass.getpass('SSH password: ')
    tarball = bundle()
    print(f'bundle: {len(tarball)/1e6:.1f} MB')
    ok_workers = []
    for n in a.nodes:
        try:
            ok, w = deploy_node(n, pw, tarball)
            if ok:
                ok_workers.append(w)
        except Exception as e:
            print(f'  [{n}] deploy failed: {e}')
    if not ok_workers:
        sys.exit('no worker started')
    if 'sys1' in a.nodes:
        start_lb(pw, max_inflight=min(ok_workers))
    time.sleep(4)
    status()
    print(f'\nFront-end URL: {CONFIG["public_url"]}/')


if __name__ == '__main__':
    main()
