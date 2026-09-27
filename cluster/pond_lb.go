// pond_lb — Layer-7 load balancer for the Pond Catchment service (Phase 3).
//
// Runs on Sys1 and spreads requests over the gunicorn workers on Sys1–Sys4.
//   - Routing   : least outstanding requests, ties broken by EWMA latency.
//   - Admission : each backend accepts at most -max-inflight concurrent requests
//     (≈ its CPU cores, because terrain analysis is CPU-bound). Extra
//     requests wait in a bounded queue for up to -queue-timeout and
//     are then shed with HTTP 503 + Retry-After (protects the cluster
//     from overload instead of letting latency grow without bound).
//   - Health    : active GET /health every -health-interval; passive ejection
//     after connection errors; automatic re-admission.
//   - Retry     : request bodies are buffered (≤ -max-body MB) so a request that
//     fails to connect is retried once on another healthy backend.
//   - Stats     : GET /lb/stats (JSON) — per-backend traffic share, latency, errors.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

type Backend struct {
	URL      *url.URL
	Proxy    *httputil.ReverseProxy
	inflight int64
	served   int64
	errors   int64
	shed     int64
	healthy  atomic.Bool
	mu       sync.Mutex
	ewmaMs   float64
	lastErr  string
}

func (b *Backend) observe(ms float64) {
	b.mu.Lock()
	if b.ewmaMs == 0 {
		b.ewmaMs = ms
	} else {
		b.ewmaMs = 0.3*ms + 0.7*b.ewmaMs
	}
	b.mu.Unlock()
}

func (b *Backend) latency() float64 { b.mu.Lock(); defer b.mu.Unlock(); return b.ewmaMs }

type LB struct {
	backends     []*Backend
	maxInflight  int64
	queueTimeout time.Duration
	maxBody      int64
	slotFreed    chan struct{}
	total, shed  int64
	queued       int64
	rr           uint64
	started      time.Time
}

// pick returns the healthy backend with the fewest in-flight requests that is
// below its concurrency cap, or nil when every backend is saturated.
func (lb *LB) pick(exclude *Backend) *Backend {
	var best *Backend
	n := len(lb.backends)
	start := int(atomic.AddUint64(&lb.rr, 1) % uint64(n)) // rotate the scan start → round-robin among equals
	for i := 0; i < n; i++ {
		b := lb.backends[(start+i)%n]
		if b == exclude || !b.healthy.Load() {
			continue
		}
		in := atomic.LoadInt64(&b.inflight)
		if in >= lb.maxInflight {
			continue
		}
		if best == nil {
			best = b
			continue
		}
		bi := atomic.LoadInt64(&best.inflight)
		// fewest in-flight wins; on a tie, only switch if clearly faster (EWMA < 2/3 and > 50 ms better)
		if in < bi || (in == bi && b.latency() > 0 && b.latency() < 0.67*best.latency() && best.latency()-b.latency() > 50) {
			best = b
		}
	}
	if best != nil {
		atomic.AddInt64(&best.inflight, 1)
	}
	return best
}

func (lb *LB) release(b *Backend) {
	atomic.AddInt64(&b.inflight, -1)
	select {
	case lb.slotFreed <- struct{}{}:
	default:
	}
}

// acquire waits (bounded) for a free backend slot.
func (lb *LB) acquire(ctx context.Context, exclude *Backend) *Backend {
	if b := lb.pick(exclude); b != nil {
		return b
	}
	atomic.AddInt64(&lb.queued, 1)
	defer atomic.AddInt64(&lb.queued, -1)
	deadline := time.NewTimer(lb.queueTimeout)
	defer deadline.Stop()
	tick := time.NewTicker(25 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-deadline.C:
			return nil
		case <-lb.slotFreed:
		case <-tick.C:
		}
		if b := lb.pick(exclude); b != nil {
			return b
		}
	}
}

type statusRecorder struct {
	http.ResponseWriter
	status int
}

func (s *statusRecorder) WriteHeader(c int) { s.status = c; s.ResponseWriter.WriteHeader(c) }

func (lb *LB) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	switch r.URL.Path {
	case "/lb/stats":
		lb.stats(w)
		return
	case "/lb/health":
		w.Header().Set("Content-Type", "application/json")
		fmt.Fprintf(w, `{"status":"ok","healthy_backends":%d}`, lb.healthyCount())
		return
	}
	atomic.AddInt64(&lb.total, 1)

	var body []byte
	if r.Body != nil {
		var err error
		body, err = io.ReadAll(io.LimitReader(r.Body, lb.maxBody+1))
		if err != nil {
			http.Error(w, `{"success":false,"error":"could not read request body"}`, http.StatusBadRequest)
			return
		}
		if int64(len(body)) > lb.maxBody {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusRequestEntityTooLarge)
			fmt.Fprintf(w, `{"success":false,"error":"request larger than %d MB"}`, lb.maxBody>>20)
			return
		}
	}

	var tried *Backend
	for attempt := 0; attempt < 2; attempt++ {
		b := lb.acquire(r.Context(), tried)
		if b == nil {
			atomic.AddInt64(&lb.shed, 1)
			w.Header().Set("Content-Type", "application/json")
			w.Header().Set("Retry-After", "2")
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, `{"success":false,"error":"All analysis workers are busy — request shed to protect the cluster. Please retry in a few seconds."}`)
			return
		}
		r2 := r.Clone(r.Context())
		r2.Body = io.NopCloser(bytes.NewReader(body))
		r2.ContentLength = int64(len(body))
		failed := false
		ctx := context.WithValue(r2.Context(), ctxKey{}, &failed)
		r2 = r2.WithContext(ctx)

		rec := &statusRecorder{ResponseWriter: w, status: 200}
		t0 := time.Now()
		if attempt == 0 {
			b.Proxy.ServeHTTP(&noWriteOnFail{rec: rec, failed: &failed}, r2)
		} else {
			b.Proxy.ServeHTTP(rec, r2)
		}
		ms := float64(time.Since(t0).Microseconds()) / 1000
		lb.release(b)
		if failed && attempt == 0 {
			tried = b
			continue // connection-level failure → retry once elsewhere
		}
		atomic.AddInt64(&b.served, 1)
		if rec.status >= 500 {
			atomic.AddInt64(&b.errors, 1)
		} else {
			b.observe(ms)
		}
		return
	}
}

type ctxKey struct{}

// noWriteOnFail swallows the proxy's own 502 page on the first attempt so we can retry.
type noWriteOnFail struct {
	rec    *statusRecorder
	failed *bool
}

func (n *noWriteOnFail) Header() http.Header { return n.rec.Header() }
func (n *noWriteOnFail) Write(p []byte) (int, error) {
	if *n.failed {
		return len(p), nil
	}
	return n.rec.Write(p)
}
func (n *noWriteOnFail) WriteHeader(c int) {
	if *n.failed {
		return
	}
	n.rec.WriteHeader(c)
}
func (n *noWriteOnFail) Flush() {
	if f, ok := n.rec.ResponseWriter.(http.Flusher); ok && !*n.failed {
		f.Flush()
	}
}

func (lb *LB) healthyCount() int {
	n := 0
	for _, b := range lb.backends {
		if b.healthy.Load() {
			n++
		}
	}
	return n
}

func (lb *LB) healthLoop(interval time.Duration) {
	client := &http.Client{Timeout: 3 * time.Second}
	for {
		for _, b := range lb.backends {
			go func(b *Backend) {
				resp, err := client.Get(b.URL.String() + "/health")
				ok := err == nil && resp.StatusCode == 200
				if resp != nil {
					io.Copy(io.Discard, resp.Body)
					resp.Body.Close()
				}
				was := b.healthy.Swap(ok)
				if was != ok {
					log.Printf("backend %s healthy=%v", b.URL, ok)
				}
				if ok {
					b.mu.Lock()
					b.lastErr = ""
					b.mu.Unlock()
				} else if err != nil {
					b.mu.Lock()
					b.lastErr = err.Error()
					b.mu.Unlock()
				}
			}(b)
		}
		time.Sleep(interval)
	}
}

func (lb *LB) stats(w http.ResponseWriter) {
	type bs struct {
		Healthy       bool    `json:"healthy"`
		Inflight      int64   `json:"inflight"`
		Served        int64   `json:"served"`
		Errors        int64   `json:"errors_5xx"`
		EwmaLatencyMs float64 `json:"ewma_latency_ms"`
		SharePct      float64 `json:"traffic_share_pct"`
		LastError     string  `json:"last_health_error,omitempty"`
	}
	var sum int64
	for _, b := range lb.backends {
		sum += atomic.LoadInt64(&b.served)
	}
	out := map[string]bs{}
	for _, b := range lb.backends {
		s := atomic.LoadInt64(&b.served)
		share := 0.0
		if sum > 0 {
			share = 100 * float64(s) / float64(sum)
		}
		b.mu.Lock()
		le := b.lastErr
		b.mu.Unlock()
		out[b.URL.String()] = bs{b.healthy.Load(), atomic.LoadInt64(&b.inflight), s,
			atomic.LoadInt64(&b.errors), float64(int(b.latency()*10)) / 10, float64(int(share*10)) / 10, le}
	}
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]interface{}{
		"uptime_s":              int(time.Since(lb.started).Seconds()),
		"total_requests":        atomic.LoadInt64(&lb.total),
		"shed_503":              atomic.LoadInt64(&lb.shed),
		"queued_now":            atomic.LoadInt64(&lb.queued),
		"max_inflight_per_node": lb.maxInflight,
		"healthy_backends":      lb.healthyCount(),
		"backends":              out,
	})
}

func main() {
	port := flag.Int("port", 5000, "listen port on Sys1")
	backendStr := flag.String("backends", "http://127.0.0.1:5002,http://172.17.0.39:5002,http://172.17.0.40:5002,http://172.17.0.41:5002", "comma-separated worker URLs")
	maxInflight := flag.Int("max-inflight", 4, "max concurrent requests per backend (≈ worker processes)")
	queueTimeout := flag.Duration("queue-timeout", 15*time.Second, "max time a request waits for a free worker before 503")
	healthInterval := flag.Duration("health-interval", 2*time.Second, "active health-check interval")
	maxBodyMB := flag.Int64("max-body", 26, "max request body in MB (KML/KMZ uploads)")
	flag.Parse()

	lb := &LB{maxInflight: int64(*maxInflight), queueTimeout: *queueTimeout,
		maxBody: *maxBodyMB << 20, slotFreed: make(chan struct{}, 1024), started: time.Now()}

	transport := &http.Transport{
		DialContext:           (&net.Dialer{Timeout: 3 * time.Second, KeepAlive: 30 * time.Second}).DialContext,
		MaxIdleConns:          512,
		MaxIdleConnsPerHost:   128,
		IdleConnTimeout:       90 * time.Second,
		ResponseHeaderTimeout: 120 * time.Second,
	}
	for _, s := range strings.Split(*backendStr, ",") {
		s = strings.TrimSpace(s)
		if s == "" {
			continue
		}
		u, err := url.Parse(s)
		if err != nil {
			log.Fatalf("bad backend %q: %v", s, err)
		}
		b := &Backend{URL: u}
		p := httputil.NewSingleHostReverseProxy(u)
		p.Transport = transport
		bb := b
		p.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			if f, ok := r.Context().Value(ctxKey{}).(*bool); ok {
				*f = true
			}
			bb.healthy.Store(false) // passive ejection; health loop re-admits
			bb.mu.Lock()
			bb.lastErr = err.Error()
			bb.mu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			fmt.Fprint(w, `{"success":false,"error":"analysis worker unavailable"}`)
		}
		b.Proxy = p
		b.healthy.Store(true)
		lb.backends = append(lb.backends, b)
	}
	go lb.healthLoop(*healthInterval)

	log.Printf("pond_lb listening on :%d → %d backends (max %d in-flight each, queue %s)",
		*port, len(lb.backends), *maxInflight, *queueTimeout)
	srv := &http.Server{Addr: fmt.Sprintf(":%d", *port), Handler: lb,
		ReadHeaderTimeout: 10 * time.Second, IdleTimeout: 120 * time.Second}
	log.Fatal(srv.ListenAndServe())
}
