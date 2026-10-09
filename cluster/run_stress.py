#!/usr/bin/env python3
"""
Step-load stress test: runs Locust headless at increasing user counts against
one or more targets and writes a summary CSV + plot for the report.

Examples
  # 4-node cluster (through the load balancer) vs a single node
  python3 cluster/run_stress.py \
      --target cluster=http://10.1.75.51:5237 \
      --target single=http://172.17.0.39:5002 \
      --users 10 25 50 100 200 --duration 60

Outputs  results/stress_summary.csv, results/stress_plot.png
"""
import argparse
import csv
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), 'results')


def run_level(name, host, users, duration):
    prefix = os.path.join(OUT, f'{name}_u{users}')
    def to_float(v, default=0.0):
        try:
            return float(v)
        except (ValueError, TypeError):
            return default

    cmd = [sys.executable, '-m', 'locust', '-f', os.path.join(HERE, 'locustfile.py'),
           '--host', host, '--headless', '-u', str(users), '-r', str(max(20, users)),
           '-t', f'{duration}s', '--csv', prefix, '--only-summary']
    print(f'[{name}] {users} users for {duration}s …', flush=True)
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with open(prefix + '_stats.csv') as f:
        rows = {r['Name']: r for r in csv.DictReader(f)}
    agg = rows['Aggregated']
    area = rows.get('/api/analyzeArea [new]', agg)
    n = int(agg['Request Count']) or 1
    return {
        'target': name, 'users': users,
        'requests': int(agg['Request Count']),
        'failures': int(agg['Failure Count']),
        'error_pct': round(100 * int(agg['Failure Count']) / n, 2),
        'throughput_rps': round(to_float(agg.get('Requests/s')), 2),
        'p50_ms': to_float(agg.get('50%')), 'p95_ms': to_float(agg.get('95%')), 'p99_ms': to_float(agg.get('99%')),
        'area_p50_ms': to_float(area.get('50%')), 'area_p95_ms': to_float(area.get('95%')),
    }


def plot(results, path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.2))
    for name in sorted({r['target'] for r in results}):
        rs = [r for r in results if r['target'] == name]
        u = [r['users'] for r in rs]
        ax[0].plot(u, [r['throughput_rps'] for r in rs], 'o-', label=name)
        ax[1].plot(u, [r['p95_ms'] for r in rs], 'o-', label=name)
        ax[2].plot(u, [r['error_pct'] for r in rs], 'o-', label=name)
    for a, t, y in zip(ax, ['Throughput', 'p95 latency', 'Errors / shed'],
                       ['requests / s', 'ms', '% of requests']):
        a.set_title(t, fontweight='bold'); a.set_xlabel('concurrent users'); a.set_ylabel(y)
        a.grid(alpha=0.3); a.legend()
    fig.tight_layout(); fig.savefig(path, dpi=130)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', action='append', required=True, help='name=url')
    ap.add_argument('--users', type=int, nargs='+', default=[10, 25, 50, 100, 200])
    ap.add_argument('--duration', type=int, default=60)
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    results = []
    for t in a.target:
        name, url = t.split('=', 1)
        for u in a.users:
            results.append(run_level(name, url, u, a.duration))
            print('   ', results[-1], flush=True)
            time.sleep(3)
    path = os.path.join(OUT, 'stress_summary.csv')
    with open(path, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader(); w.writerows(results)
    plot_path = os.path.join(OUT, 'stress_plot.png')
    plot(results, plot_path)
    import shutil
    shutil.copy(plot_path, os.path.join(os.path.dirname(OUT), 'report', 'stress_plot.png'))
    print('wrote', path, 'and', plot_path)


if __name__ == '__main__':
    main()
