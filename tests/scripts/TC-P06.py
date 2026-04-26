"""
TC-P06 -- Performance: 100-message burst covering all system features

Tests:
  1. POST /v1/messages  -- per-message insert latency (P50 / P95 / P99 / max)
  2. POST /v1/context   -- cold latency (immediately after insert, before worker)
  3. Worker pipeline    -- when does each feature first appear?
                          (entity_facts, semantic_messages, upcoming_events,
                           persona_context, experiences)
  4. POST /v1/context   -- warm latency (after worker settled)
  5. Token counts       -- total_tokens from context + LLM usage from DB

Coverage -- 100 messages (50 user + 50 assistant) across:
  Block 1 (msgs  1-10):  Personal identity (name, email, phone, address, job)
  Block 2 (msgs 11-20):  Professional info, birthday, hobbies, life plans
  Block 3 (msgs 21-30):  Entity updates / supersede (email, company, address)
  Block 4 (msgs 31-40):  Upcoming life events (thesis, wedding, IELTS)
  Block 5 (msgs 41-56):  Experience triggers (correction, nho la, lan sau,
                          from now on, next time, going forward)
  Block 6 (msgs 57-72):  Long technical messages for vector embedding
  Block 7 (msgs 73-84):  Persona / personality traits
  Block 8 (msgs 85-96):  Multi-entity / team members
  Block 9 (msgs 97-100): Conversational wrap-up / re-affirmation

PASS criteria:
  - All 100 inserts return HTTP 200
  - Insert P99 latency < 1000 ms
  - Cold context latency < 500 ms (Redis path)
  - entity_facts populated within 300 s (cognitive worker)
  - semantic_messages populated within 300 s (embedder worker)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
import time
import subprocess
import statistics
from test_utils import APIClient, ExperienceClient

TENANT_ID  = str(uuid.uuid4())
USER_ID    = str(uuid.uuid4())
SESSION_ID = str(uuid.uuid4())

MESSAGES = [
    # Block 1: Personal identity (msgs 1-10)
    ("user",      "Chao, toi ten la Nguyen Minh Duc"),
    ("assistant", "Chao Duc! Rat vui duoc gap ban."),
    ("user",      "Email cua toi la duc.nguyen@company.com"),
    ("assistant", "Da ghi nhan email cua ban."),
    ("user",      "So dien thoai cua toi la 0912345678"),
    ("assistant", "Cam on, da luu so dien thoai."),
    ("user",      "Toi dang song o Ha Noi, quan Cau Giay"),
    ("assistant", "Ban o Cau Giay, Ha Noi. Khu vuc sam uat do."),
    ("user",      "Toi lam viec tai Viettel, vi tri Senior Software Engineer"),
    ("assistant", "Ban la Senior Software Engineer tai Viettel, thu vi do!"),
    # Block 2: Professional info + birthday + hobbies (msgs 11-20)
    ("user",      "Toi co kinh nghiem 8 nam lam ve backend Go va microservices"),
    ("assistant", "8 nam kinh nghiem Go va microservices - rat an tuong!"),
    ("user",      "Sinh nhat cua toi la ngay 15 thang 8"),
    ("assistant", "Sinh nhat 15/8 - sap den roi nhi!"),
    ("user",      "Toi thich hoc cac cong nghe moi, dac biet la AI va ML"),
    ("assistant", "Dam me AI/ML - linh vuc dang bung no hien nay."),
    ("user",      "Cuoi thang 5 nay toi co ke hoach di du lich Nhat Ban"),
    ("assistant", "Chuyen di Nhat thang 5 nghe rat thu vi!"),
    ("user",      "Toi hay uong ca phe moi sang va tap gym 3 lan moi tuan"),
    ("assistant", "Thoi quen tot - ca phe va gym giup ban nang dong ca ngay."),
    # Block 3: Entity updates / supersede (msgs 21-30)
    ("user",      "A quen, toi vua doi email roi. Email moi la duc.nguyen@newcompany.vn"),
    ("assistant", "Da cap nhat email moi cho ban."),
    ("user",      "Toi cung vua chuyen sang lam tai FPT Software, tu thang 4 nay"),
    ("assistant", "Chuc mung ban voi cong viec moi tai FPT Software!"),
    ("user",      "Muc luong hien tai cua toi la 3000 USD moi thang"),
    ("assistant", "Muc thu nhap tot cho vi tri senior."),
    ("user",      "Toi cung vua chuyen nha ve quan Dong Da"),
    ("assistant", "Dong Da cung la khu vuc tien loi."),
    ("user",      "So dien thoai cong ty cua toi la 024 3869 1234"),
    ("assistant", "Da ghi nhan so dien thoai cong ty."),
    # Block 4: Upcoming life events (msgs 31-40)
    ("user",      "Ngay 20 thang 6 nam 2026 toi se bao ve luan van thac si"),
    ("assistant", "Chuc mung! Bao ve luan van thac si 20/6/2026 la mot cot moc lon."),
    ("user",      "Toi du dinh ket hon vao thang 12 nam nay"),
    ("assistant", "Tuyet voi! Dam cuoi thang 12 - mua dong lang man."),
    ("user",      "Ngay 01/05/2026 toi se nhan job offer tu cong ty moi"),
    ("assistant", "Job offer 1/5 - chuc mung buoc tien moi trong su nghiep!"),
    ("user",      "Toi dang chuan bi thi IELTS vao thang 7"),
    ("assistant", "Thi IELTS thang 7 - chuc ban dat band cao!"),
    ("user",      "Sinh nhat me toi la ngay 10 thang 9"),
    ("assistant", "Sinh nhat me 10/9 - nho chuan bi qua nhe!"),
    # Block 5: Experience triggers (msgs 41-56)
    ("user",      "Khi toi hoi ve Go code review, hay luon bat dau bang error handling truoc"),
    ("assistant", "Hieu roi, toi se luon kiem tra error handling truoc khi review Go code."),
    ("user",      "Khong dung. Lan sau khi toi hoi ve code review, nho la phai check security issues truoc, sau do moi den error handling"),
    ("assistant", "Duoc roi, toi se nho: voi code review check security truoc, roi error handling."),
    ("user",      "Dung vay, cam on"),
    ("assistant", "Toi da ghi nho uu tien cua ban."),
    ("user",      "Tu nay khi toi hoi ve database, hay luon de xuat index optimization dau tien"),
    ("assistant", "Da hieu, index optimization se luon la de xuat dau tien cho database."),
    ("user",      "Khi giai thich technical concepts, toi thich vi du thuc te hon la ly thuyet"),
    ("assistant", "Toi se luon dung vi du thuc te khi giai thich ky thuat cho ban."),
    ("user",      "Lan sau khi toi hoi ve architecture, always start with the trade-offs"),
    ("assistant", "Understood, I will always start with trade-offs when discussing architecture."),
    ("user",      "Going forward, khi review code cua toi, hay uu tien performance truoc"),
    ("assistant", "Da ghi nhan: performance la uu tien khi review code."),
    ("user",      "Toi khong thich giai thich qua dai dong. Next time hay ngan gon va di thang vao van de"),
    ("assistant", "Hieu roi, toi se tra loi ngan gon va suc tich hon."),
    # Block 6: Long technical content for vector embedding (msgs 57-72)
    ("user",
        "Toi can tu van ve thiet ke he thong phan tan. Cong ty dang xay dung"
        " platform xu ly real-time data voi yeu cau: 1) Throughput 100k events/second,"
        " 2) Latency P99 duoi 10ms, 3) High availability 99.99%, 4) Horizontal scalability."
        " Can nhac: Kafka + Flink vs Pulsar + Spark Streaming."
        " Stack la Go microservices voi PostgreSQL va Redis. Phan tich pros/cons?"),
    ("assistant",
        "Voi yeu cau 100k events/s va P99 < 10ms, Kafka + Flink la lua chon phu hop hon:"
        " Kafka throughput cao, Flink latency thap hon Spark. Pulsar co multi-tenancy tot"
        " hon nhung ecosystem nho hon va operational complexity cao."),
    ("user",
        "Ve database scaling, gap bottleneck o PostgreSQL voi 50M records."
        " Query phuc tap nhat la join 5 tables voi full-text search."
        " Da them read replicas nhung write throughput van la van de."
        " Giai phap: 1) Citus sharding, 2) CockroachDB, 3) CQRS, 4) Combination?"),
    ("assistant",
        "CQRS la approach pragmatic nhat: tach write model PostgreSQL + pgpartman va"
        " read model Elasticsearch cho full-text search."
        " Citus them complexity, CockroachDB migration cost cao."),
    ("user",
        "Implement rate limiting cho API gateway: per-user 1000 req/min,"
        " per-tenant 10000 req/min, burst allowance 2x trong 10s, distributed state"
        " across 3 data centers, latency overhead < 1ms."
        " Can nhac Token Bucket vs Sliding Window vs Fixed Window."
        " Redis Cluster voi Lua script la approach hien tai. Suggest?"),
    ("assistant",
        "Sliding Window Counter voi Redis Lua la best approach: low memory,"
        " distributed-safe, < 0.5ms overhead. Dung 2 keys per user"
        " (current + previous window), tinh approximate rate. Dap ung burst va multi-DC."),
    ("user",
        "Refactor legacy monolith sang microservices: 500k LOC Java Spring Boot,"
        " 200 REST endpoints, shared PostgreSQL, tight coupling, 20 engineers."
        " Cau hoi: 1) Strangler Fig hay Big Bang? 2) Identify bounded contexts the nao?"
        " 3) Database-per-service hay shared DB giai doan dau? 4) Service mesh can ngay?"),
    ("assistant",
        "Strangler Fig an toan hon cho 500k LOC. Identify bounded contexts qua team"
        " ownership + data coupling. Database-per-service tu dau tranh technical debt."
        " Service mesh defer den khi co 10+ services."),
    ("user",
        "Build ML pipeline cho recommendation system: 10M users, 1M items, 500M interactions,"
        " real-time serving < 20ms. Can nhac: Matrix factorization ALS, Two-tower model,"
        " GraphSAGE. Feature store: Feast vs Tecton. Online serving: FAISS vs ScaNN."
        " Batch training moi 6h. Recommend stack?"),
    ("assistant",
        "Two-tower model + FAISS la stack production-proven cho scale nay."
        " Feast cho feature store open source mature. Batch voi Spark + delta lake."
        " Online: candidate generation FAISS, re-ranking XGBoost."),
    ("user",
        "Security review JWT authentication: token expiry 15 phut, refresh token 7 ngay."
        " Store refresh tokens trong Redis blacklist approach. Van de:"
        " 1) Token rotation on refresh, 2) Revocation khi logout all devices,"
        " 3) Detect token theft qua refresh token reuse. Feedback ve design?"),
    ("assistant",
        "Design tot. Token rotation: issue new refresh token on each use, invalidate old."
        " Logout all devices: store device_id, revoke by user_id prefix."
        " Detect reuse: blacklisted token dung lai thi revoke tat ca tokens cua user do."),
    ("user",
        "Observability strategy cho microservices: 15 services, 3 data centers."
        " Can: distributed tracing, centralized logging, metrics alerting."
        " Danh gia: OpenTelemetry + Jaeger vs Datadog vs AWS X-Ray."
        " Log aggregation: ELK Stack vs Loki + Grafana. Metrics: Prometheus + Grafana."
        " Budget: duoi 2000 USD moi thang. Recommendation?"),
    ("assistant",
        "OpenTelemetry + Jaeger self-hosted + Loki + Prometheus + Grafana la stack"
        " phu hop voi budget. Tat ca open-source, Grafana lam unified dashboard."
        " Datadog manh hon nhung dat hon nhieu o scale 15 services."),
    ("user",
        "Caching strategy cho distributed system: L1 cache in-memory, L2 cache Redis,"
        " CDN cho static assets. Cache invalidation strategies: TTL, event-driven, write-through."
        " Cache stampede prevention: probabilistic early expiration, request coalescing."
        " Suggest best practices cho Go microservices architecture?"),
    ("assistant",
        "TTL + event-driven invalidation la combination tot nhat. Write-through cho consistency."
        " Probabilistic early expiration chong stampede hieu qua. Dung singleflight trong Go"
        " de coalesce concurrent cache misses ve cung 1 key."),
    # Block 7: Persona / personality traits (msgs 73-84)
    ("user",      "Toi la nguoi huong noi, thich lam viec mot minh hon la team work"),
    ("assistant", "Dac diem introvert - nhieu engineer gioi co tinh cach nay."),
    ("user",      "Toi co xu huong cau toan, hay bi stuck voi perfectionism"),
    ("assistant", "Perfectionism co the la diem manh neu biet balance voi delivery."),
    ("user",      "Toi hoc tot nhat qua viec tu lam, khong phai doc docs hay xem video"),
    ("assistant", "Hands-on learning - build something to learn it, classic approach."),
    ("user",      "Toi hay bi overwhelmed khi co qua nhieu task cung luc"),
    ("assistant", "Overwhelm voi multitasking rat pho bien - single-tasking focus se giup ban."),
    ("user",      "Diem yeu cua toi la procrastination voi cac task khong thu vi"),
    ("assistant", "Procrastination thuong do task qua lon - break it down thanh 15 phut chunks."),
    ("user",      "Toi thich deep work va can it nhat 2 tieng lien tuc de focused coding"),
    ("assistant", "Deep work 2h+ la ly tuong cho complex coding. Block calendar de protect time."),
    # Block 8: Multi-entity / team members (msgs 85-96)
    ("user",      "Trong team toi co Tran Van Binh lam DevOps va Le Thi Hoa lam QA"),
    ("assistant", "Team co Binh DevOps va Hoa QA - doi hinh kha can bang."),
    ("user",      "Anh Binh email la binh.tran@fpt.com, chi Hoa la hoa.le@fpt.com"),
    ("assistant", "Da luu email cua Binh va Hoa."),
    ("user",      "Sep cua toi la Nguyen Van Khoa, Director of Engineering tai FPT"),
    ("assistant", "Director Khoa - nguoi co anh huong lon den career path cua ban."),
    ("user",      "Mentor cua toi la anh Pham Hoang Long, hien o Singapore lam CTO"),
    ("assistant", "Mentor CTO o Singapore - network tot do!"),
    ("user",      "Dong nghiep cu Nguyen Thi Thu dang lam tai Google Vietnam"),
    ("assistant", "Thu o Google Vietnam - mang luoi cu dong nghiep dang gia."),
    ("user",      "Ban than Dang Quoc Hung, nguoi Phu Quoc, dang lam startup fintech"),
    ("assistant", "Hung lam fintech startup o Phu Quoc - sounds interesting!"),
    # Block 9: Wrap-up / re-affirmation (msgs 97-100)
    ("user",      "Ban co the tom tat nhung gi ban biet ve toi khong?"),
    ("assistant", "Ban la Nguyen Minh Duc, Senior SE tai FPT Software, Ha Noi. 8 nam Go/microservices."),
    ("user",      "Tot lam. Nho la toi thich duoc goi la Duc thoi, khong can ho ten day du"),
    ("assistant", "Da ghi nhan - se goi ban la Duc tu nay."),
]

assert len(MESSAGES) == 100, "Expected 100, got %d" % len(MESSAGES)


def pct(data, p):
    s = sorted(data)
    if not s:
        return 0.0
    k = (len(s) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def poll_features(timeout_sec=300, poll_interval=2.0):
    """Poll /context + /experiences until required features appear or timeout."""
    features_seen = {}
    required = {"entity_facts", "semantic_messages"}
    start = time.time()
    while time.time() - start < timeout_sec:
        elapsed = time.time() - start
        ok, data, _ = APIClient.get_context(
            TENANT_ID, USER_ID, SESSION_ID,
            query="Duc lam o dau, sinh nhat khi nao",
        )
        if ok:
            for feat in ("entity_facts", "semantic_messages", "upcoming_events", "persona_context"):
                if feat not in features_seen and data.get(feat):
                    features_seen[feat] = round(elapsed, 1)
        exp_ok, exp_data, _ = ExperienceClient.list_experiences(TENANT_ID, USER_ID)
        if exp_ok and "experiences" not in features_seen and exp_data.get("experiences"):
            features_seen["experiences"] = round(elapsed, 1)
        if len(features_seen) >= 5 and elapsed > 10:
            break
        time.sleep(poll_interval)
    return features_seen


def query_llm_usage():
    """Query llm_usage table for this tenant via psql."""
    try:
        sql = (
            "SELECT feature, model, SUM(total_tokens) AS tokens, COUNT(*) AS calls "
            "FROM llm_usage WHERE tenant_id = '" + TENANT_ID + "' "
            "GROUP BY feature, model ORDER BY feature;"
        )
        result = subprocess.run(
            ["psql", "-h", "localhost", "-p", "5433", "-U", "postgres", "-d", "cortexa",
             "-c", sql, "-t"],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PGPASSWORD": "postgres"},
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "(psql error: " + result.stderr.strip()[:80] + ")"
    except Exception as e:
        return "(psql unavailable: " + str(e) + ")"


def run_tests():
    results = []
    print()
    print("=" * 70)
    print("TC-P06 -- Performance: 100-message burst (all system features)")
    print("  Tenant : " + TENANT_ID)
    print("  User   : " + USER_ID)
    print("  Session: " + SESSION_ID)
    print("=" * 70)

    # ---- Phase 1: Sequential insert ------------------------------------------
    print()
    print("[Phase 1] Inserting 100 messages sequentially ...")
    insert_latencies = []
    failed_inserts = []
    phase1_start = time.time()
    for idx, (role, content) in enumerate(MESSAGES, start=1):
        ok, resp, lat = APIClient.append_message(TENANT_ID, USER_ID, SESSION_ID, role, content)
        insert_latencies.append(lat)
        if not ok:
            failed_inserts.append((idx, role, lat))
        if idx % 10 == 0:
            batch = insert_latencies[-10:]
            print("  msgs %3d-%3d | avg %.1f ms | max %.1f ms" % (
                idx - 9, idx, statistics.mean(batch), max(batch)))
    phase1_elapsed = time.time() - phase1_start
    p50  = pct(insert_latencies, 50)
    p95  = pct(insert_latencies, 95)
    p99  = pct(insert_latencies, 99)
    p_max = max(insert_latencies)
    avg  = statistics.mean(insert_latencies)
    print("  Total: %.2f s  |  Throughput: %.1f msg/s" % (phase1_elapsed, 100 / phase1_elapsed))
    print("  P50=%.1fms  P95=%.1fms  P99=%.1fms  MAX=%.1fms  AVG=%.1fms" % (p50, p95, p99, p_max, avg))
    print("  Failed: %d/100" % len(failed_inserts))
    results.append({
        "id": "TC-P06-01", "name": "All 100 inserts return HTTP 200",
        "passed": len(failed_inserts) == 0,
        "details": "all OK" if not failed_inserts else str([f[0] for f in failed_inserts]),
        "duration_ms": phase1_elapsed * 1000,
    })
    results.append({
        "id": "TC-P06-02", "name": "Insert P99 latency < 1000 ms",
        "passed": p99 < 1000,
        "details": "P99=%.1fms P95=%.1fms P50=%.1fms AVG=%.1fms" % (p99, p95, p50, avg),
        "duration_ms": 0,
    })

    # ---- Phase 2: Cold context -----------------------------------------------
    print()
    print("[Phase 2] Cold GET /context (before worker) ...")
    cold_ok, cold_data, cold_lat = APIClient.get_context(
        TENANT_ID, USER_ID, SESSION_ID, query="Duc lam o dau, sinh nhat khi nao")
    cold_recent   = len(cold_data.get("recent_messages", []))
    cold_entities = len(cold_data.get("entity_facts", []))
    cold_semantic = len(cold_data.get("semantic_messages", []))
    cold_tokens   = cold_data.get("total_tokens", 0)
    cold_svc_ms   = cold_data.get("latency_ms", 0)
    print("  HTTP ok           : " + str(cold_ok))
    print("  recent_messages   : %d  <- Redis newest-first, expect up to 20" % cold_recent)
    print("  entity_facts      : %d  <- 0 expected (worker not done)" % cold_entities)
    print("  semantic_messages : %d  <- 0 expected (embedder not done)" % cold_semantic)
    print("  total_tokens      : %d" % cold_tokens)
    print("  svc latency_ms    : %.1f" % cold_svc_ms)
    print("  round-trip ms     : %.1f" % cold_lat)
    results.append({
        "id": "TC-P06-03", "name": "Cold context latency < 1500 ms (incl. embed call)",
        "passed": cold_lat < 1500,
        "details": "round-trip=%.1fms svc=%.1fms" % (cold_lat, cold_svc_ms),
        "duration_ms": cold_lat,
    })
    results.append({
        "id": "TC-P06-04", "name": "Cold context has recent_messages from Redis",
        "passed": cold_recent > 0,
        "details": "count=%d (capped at RECENT_MESSAGES_LIMIT=20)" % cold_recent,
        "duration_ms": 0,
    })

    # ---- Phase 3: Wait for workers -------------------------------------------
    print()
    print("[Phase 3] Waiting for worker pipeline (max 300 s) ...")
    poll_start = time.time()
    features_seen = poll_features(timeout_sec=300, poll_interval=2.0)
    poll_elapsed  = time.time() - poll_start
    print("  Poll finished in %.1f s" % poll_elapsed)
    for feat in ["entity_facts", "semantic_messages", "upcoming_events", "persona_context", "experiences"]:
        if feat in features_seen:
            print("  OK  %-24s: appeared at %.1f s" % (feat, features_seen[feat]))
        else:
            print("  --  %-24s: NOT seen within timeout" % feat)

    # Drain: wait for the cognitive worker to finish processing ALL remaining
    # batch events that were queued by this test run (100 msgs → 100 batches).
    # Without this wait, subsequent tests (e.g. TC-E11) are starved of worker
    # capacity and time out waiting for their own extractions.
    drain_wait = max(0.0, 100 - poll_elapsed)
    if drain_wait > 0:
        print("  Draining worker queue (%.0f s) ..." % drain_wait)
        time.sleep(drain_wait)

    # ---- Phase 4: Warm context -----------------------------------------------
    print()
    print("[Phase 4] Warm GET /context (after workers) ...")
    warm_ok, warm_data, warm_lat = APIClient.get_context(
        TENANT_ID, USER_ID, SESSION_ID,
        query="Duc lam o dau, sinh nhat khi nao, uu tien code review")
    warm_recent   = len(warm_data.get("recent_messages", []))
    warm_entities = len(warm_data.get("entity_facts", []))
    warm_semantic = len(warm_data.get("semantic_messages", []))
    warm_events   = len(warm_data.get("upcoming_events", []))
    warm_persona  = warm_data.get("persona_context", "")
    warm_tokens   = warm_data.get("total_tokens", 0)
    warm_svc_ms   = warm_data.get("latency_ms", 0)
    print("  HTTP ok           : " + str(warm_ok))
    print("  recent_messages   : %d" % warm_recent)
    print("  entity_facts      : %d" % warm_entities)
    print("  semantic_messages : %d" % warm_semantic)
    print("  upcoming_events   : %d" % warm_events)
    persona_preview = str(warm_persona)[:80] if warm_persona else "(empty)"
    print("  persona_context   : " + persona_preview)
    print("  total_tokens      : %d  <- context window cost" % warm_tokens)
    print("  svc latency_ms    : %.1f" % warm_svc_ms)
    print("  round-trip ms     : %.1f" % warm_lat)
    if warm_entities > 0:
        print("  entity_facts (first 8):")
        for ef in warm_data["entity_facts"][:8]:
            print("    " + str(ef))
    if warm_semantic > 0:
        print("  semantic_messages (first 3):")
        for sm in warm_data.get("semantic_messages", [])[:3]:
            preview = (sm.get("content") or "")[:90]
            print("    [" + sm.get("role", "?") + "] " + preview + "...")
    results.append({
        "id": "TC-P06-05", "name": "Warm context latency < 500 ms",
        "passed": warm_lat < 500,
        "details": "round-trip=%.1fms svc=%.1fms" % (warm_lat, warm_svc_ms),
        "duration_ms": warm_lat,
    })
    entity_ok = "entity_facts" in features_seen
    results.append({
        "id": "TC-P06-06", "name": "entity_facts populated (cognitive worker)",
        "passed": entity_ok,
        "details": ("appeared at %.1fs count=%d" % (features_seen["entity_facts"], warm_entities)
                    if entity_ok else "NOT populated within 300 s"),
        "duration_ms": features_seen.get("entity_facts", 300) * 1000,
    })
    semantic_ok = "semantic_messages" in features_seen
    results.append({
        "id": "TC-P06-07", "name": "semantic_messages populated (embedder worker)",
        "passed": semantic_ok,
        "details": ("appeared at %.1fs count=%d" % (features_seen["semantic_messages"], warm_semantic)
                    if semantic_ok else "NOT populated within 300 s"),
        "duration_ms": features_seen.get("semantic_messages", 300) * 1000,
    })
    results.append({
        "id": "TC-P06-08", "name": "upcoming_events populated (life event extraction)",
        "passed": "upcoming_events" in features_seen,
        "details": ("appeared at %.1fs count=%d" % (features_seen["upcoming_events"], warm_events)
                    if "upcoming_events" in features_seen else "NOT populated"),
        "duration_ms": features_seen.get("upcoming_events", 300) * 1000,
    })
    results.append({
        "id": "TC-P06-09", "name": "experiences populated (experience/pref worker)",
        "passed": "experiences" in features_seen,
        "details": ("appeared at %.1fs" % features_seen["experiences"]
                    if "experiences" in features_seen else "NOT populated"),
        "duration_ms": features_seen.get("experiences", 300) * 1000,
    })

    # ---- Phase 5: LLM token usage from DB ------------------------------------
    print()
    print("[Phase 5] LLM token usage from llm_usage table ...")
    llm_usage = query_llm_usage()
    print("  " + (llm_usage if llm_usage else "(no records for this tenant)"))

    # ---- Final summary -------------------------------------------------------
    print()
    print("=" * 70)
    print("PERFORMANCE SUMMARY")
    print("=" * 70)
    print("  Insert 100 msgs   : %.2f s  (%.1f msg/s)" % (phase1_elapsed, 100 / phase1_elapsed))
    print("  Insert latency    : P50=%.1fms P95=%.1fms P99=%.1fms MAX=%.1fms" % (p50, p95, p99, p_max))
    print("  Cold GET /context : %.1f ms  (recent_msgs=%d tokens=%d)" % (cold_lat, cold_recent, cold_tokens))
    print("  Worker pipeline   : settled in %.1f s" % poll_elapsed)
    print("  Warm GET /context : %.1f ms  (tokens=%d)" % (warm_lat, warm_tokens))
    print("  Features seen     : " + str(sorted(features_seen.keys())))
    print()
    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print("  [%s] %s -- %s" % (status, r["id"], r["name"]))
        if r["details"]:
            print("         " + r["details"])
    print("\n  Result: %d PASS / %d FAIL / %d total" % (len(passed), len(failed), len(results)))
    print("=" * 70)
    print()
    return results


if __name__ == "__main__":
    results = run_tests()
    failed = [r for r in results if not r["passed"]]
    sys.exit(1 if failed else 0)
