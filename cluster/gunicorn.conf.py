# Gunicorn settings for one analysis worker node (Sys1..Sys4).
import multiprocessing, os

bind = f"0.0.0.0:{os.environ.get('WORKER_PORT', '5002')}"
# Terrain analysis is CPU-bound (numpy/scipy) → one process per core.
workers = int(os.environ.get('WORKERS', max(2, multiprocessing.cpu_count())))
worker_class = 'sync'
preload_app = True          # parse + model the sample map once, share copy-on-write
timeout = 120               # uploads of large KML files can take a few seconds
graceful_timeout = 30
keepalive = 5
max_requests = 2000         # recycle workers to bound memory growth
max_requests_jitter = 200
limit_request_line = 8190
accesslog = os.environ.get('ACCESS_LOG', '-')
errorlog = '-'
loglevel = 'info'
