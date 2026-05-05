#!/usr/bin/env python3
"""Generate sample conversation CSV files for testing under tests/data/."""
import csv, io, pathlib, textwrap

TENANT = "a1b2c3d4-0000-4000-8000-100000000001"
USER_MINH = "b1000001-0000-4000-8000-200000000001"
USER_LAN  = "b2000002-0000-4000-8000-200000000002"
USER_HUNG = "b3000003-0000-4000-8000-200000000003"

def mkcsv(turns):
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(["role", "content"])
    for role, content in turns:
        w.writerow([role, textwrap.dedent(content).strip()])
    return buf.getvalue()


# ── USER 1: Minh, 28, software engineer @ Grab, Hà Nội ────────────────────

minh_s1 = mkcsv([
    ("user", "Chào bạn! Tôi tên là Minh, năm nay 28 tuổi, tôi đang làm kỹ sư phần mềm ở Grab Việt Nam."),
    ("assistant", "Chào Minh! Rất vui được gặp bạn. Bạn đang làm mảng nào ở Grab vậy — backend, mobile hay data?"),
    ("user", "Tôi làm backend, chủ yếu dùng Go và Kafka. Team tôi phụ trách phần real-time tracking của driver."),
    ("assistant", "Thú vị đấy! Real-time tracking đòi hỏi latency rất thấp. Bạn đang dùng kiến trúc gì — event-driven hoàn toàn hay vẫn có REST?"),
    ("user", "Hầu hết event-driven qua Kafka, REST chỉ dùng cho admin API. Tôi đang sống ở Hà Nội, quận Đống Đa, gần Văn Miếu."),
    ("assistant", "Hà Nội đẹp lắm, nhất là khu Văn Miếu. Ngoài công việc bạn có sở thích gì không?"),
    ("user", "Tôi hay chơi cầu lông cuối tuần, và đam mê đọc sách — chủ yếu sách kỹ thuật và tâm lý học. Đang đọc 'Thinking Fast and Slow'."),
    ("assistant", "Kahneman! Cuốn đó rất hay đặc biệt phần cognitive bias. Bạn có anh chị em không?"),
    ("user", "Có, tôi có một em gái tên Hà, 24 tuổi, đang học y khoa năm 4 ở Đại học Y Hà Nội. Bố mẹ tôi ở Hải Phòng."),
    ("assistant", "Gia đình bạn đa dạng — tech và y khoa! Bố mẹ bạn làm nghề gì?"),
    ("user", "Bố tôi là kỹ sư xây dựng về hưu. Mẹ tôi mở tiệm bánh nhỏ ở Hải Phòng, bánh rất ngon. Tôi hay về thăm cuối tháng."),
    ("assistant", "Nghe ấm cúng lắm. Lương tháng của bạn khoảng bao nhiêu vậy, nếu không ngại hỏi?"),
    ("user", "Lương tôi khoảng 45 triệu/tháng, đang để dành mua chung cư. Budget khoảng 2-2.5 tỷ, đang xem khu Cầu Giấy."),
    ("assistant", "45 triệu ở Hà Nội là tốt lắm. Bạn đã xem dự án nào chưa?"),
    ("user", "Đang xem Vinhomes Smart City. Tôi không lái xe nên ưu tiên gần metro và siêu thị."),
    ("assistant", "Vinhomes Smart City gần ga Metro Nam Từ Liêm — tiện lợi. Bạn nên compare thêm The Zei hoặc Imperia Smart City cùng tầm giá."),
    ("user", "Cảm ơn! Hôm nay tôi muốn hỏi kỹ thuật — team đang migrate Kafka 2.8 lên 3.6, bạn có tips gì không?"),
    ("assistant", "Kafka 2.8 → 3.6 lưu ý: (1) KRaft mode stable từ 3.3 nếu muốn bỏ ZooKeeper. (2) Consumer group rebalance protocol mới cần test kỹ. (3) Log compaction behavior thay đổi. Bạn đang dùng ZooKeeper hay KRaft?"),
    ("user", "Đang ZooKeeper. Tôi muốn migrate sang KRaft nhân dịp này luôn. Có rủi ro gì không?"),
    ("assistant", "KRaft migration path từ ZooKeeper: Kafka 3.6 hỗ trợ migration tool kafka-storage.sh. Rủi ro chính là downtime trong quá trình migration — plan cho maintenance window 2-4 tiếng. Test kỹ trên staging trước. Đọc KIP-833 để hiểu full process."),
])

minh_s2 = mkcsv([
    ("user", "Minh đây. Tôi đang bị bug với Go Kafka consumer — message đôi khi bị process 2 lần khi restart service."),
    ("assistant", "Classic at-least-once delivery issue! Bạn đang dùng auto-commit offset hay manual commit?"),
    ("user", "Auto-commit. Code tôi dùng goroutine để handleMessage mà không commit sau khi xong."),
    ("assistant", "Đó là vấn đề rồi. Auto-commit chạy theo interval (default 5s), không theo completion của handleMessage. Giải pháp: switch sang FetchMessage + manual CommitMessages sau khi xử lý thành công."),
    ("user", "Bạn có thể viết example code không?"),
    ("assistant", "Đây:\n```go\nfunc (c *Consumer) processMessages(ctx context.Context) {\n    sem := make(chan struct{}, 10)\n    var wg sync.WaitGroup\n    for {\n        msg, err := c.reader.FetchMessage(ctx)\n        if err != nil { break }\n        sem <- struct{}{}; wg.Add(1)\n        go func(m kafka.Message) {\n            defer wg.Done()\n            defer func() { <-sem }()\n            if err := c.handleMessage(m); err == nil {\n                c.reader.CommitMessages(ctx, m)\n            }\n        }(msg)\n    }\n    wg.Wait()\n}\n```"),
    ("user", "Rất tốt! Bạn giải thích step-by-step như này tôi rất dễ hiểu. Tôi thích kiểu giải thích có reasoning kèm code."),
    ("assistant", "Ghi nhận! Tôi sẽ luôn giải thích reasoning trước, rồi mới đến code với bạn."),
    ("user", "handleMessage gọi external API, đôi khi timeout. Nên dùng context như thế nào?"),
    ("assistant", "Dùng context.Background() cho external call, không inherit từ parent Kafka context:\n```go\nextCtx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)\ndefer cancel()\nresult, err := c.externalAPI.Call(extCtx, data)\n```\nLý do: cancel parent context không nên kill in-flight API calls."),
    ("user", "Ah hiểu rồi — parent context scope là Kafka loop, không nên leak vào external calls. Cảm ơn! Tuần tới tôi có tech talk về Kafka best practices, bạn giúp outline không?"),
    ("assistant", "Outline 45 phút:\n1. Kafka fundamentals (5 min)\n2. Production pitfalls — offset, rebalance, consumer lag (15 min)\n3. Performance tuning — batch size, linger.ms, compression (10 min)\n4. Observability — metrics, alerting (10 min)\n5. Q&A (5 min)\n\nBạn muốn expand phần nào?"),
    ("user", "Phần observability. Tôi muốn nói về consumer lag monitoring cụ thể."),
    ("assistant", "Consumer lag monitoring:\n- Metric cốt lõi: kafka_consumer_group_lag per topic-partition\n- Tool: Kafka Lag Exporter (Prometheus), Burrow\n- Alert threshold: lag > 10k messages và tăng liên tục 5 phút = có vấn đề\n- Lag spike pattern: đột ngột = processing slowdown; steady increase = under-provisioned consumers\n- Dashboard: Grafana template cho Kafka consumer lag"),
    ("user", "Hay lắm! Một câu nữa: tôi cần viết benchmark test để measure throughput của consumer. Template Go benchmark?"),
    ("assistant", "```go\nfunc BenchmarkConsumerProcessing(b *testing.B) {\n    consumer := setupTestConsumer(b)\n    messages := generateTestMessages(b.N)\n    b.ResetTimer()\n    b.RunParallel(func(pb *testing.PB) {\n        for pb.Next() {\n            msg := messages[rand.Intn(len(messages))]\n            consumer.handleMessage(msg)\n        }\n    })\n}\n```\nChạy: go test -bench=. -benchmem -count=5 -benchtime=10s"),
    ("user", "Perfect! Bạn có recommend tài liệu về Go performance không?"),
    ("assistant", "Theo thứ tự học:\n1. 'High Performance Go' — Dave Cheney blog\n2. 'Profiling Go Programs' — official Go blog\n3. pprof tool — bắt đầu với go tool pprof -http=:8080 cpu.prof\n4. 'Systems Performance' by Brendan Gregg — nặng nhưng rất deep\n\nVới Kafka: Confluent engineering blog có nhiều posts Go client tuning."),
    ("user", "Cảm ơn bạn rất nhiều! Bạn trả lời rất chi tiết và thực tế, tôi học được nhiều."),
    ("assistant", "Vui vì giúp được Minh! Lần sau có issue Go/Kafka hay cần chuẩn bị talks gì cứ hỏi nhé."),
])

minh_s3 = mkcsv([
    ("user", "Minh đây. Tôi cần nhắc về một số sự kiện tháng này."),
    ("assistant", "Chắc chắn rồi! Bạn có những sự kiện nào?"),
    ("user", "Ngày 15 tháng này deadline nộp technical design doc cho feature mới. Cả team đang chờ tôi."),
    ("assistant", "Deadline technical design doc ngày 15. Bạn đã bắt đầu draft chưa?"),
    ("user", "Mới bắt đầu. Ngày 20 là sinh nhật em gái tôi — Hà, 25 tuổi. Tôi chưa mua quà."),
    ("assistant", "Sinh nhật Hà ngày 20! Hà học y khoa — tặng gì liên quan công việc hay personal? Budget bao nhiêu?"),
    ("user", "Budget 500k-1 triệu. Tuần trước Hà nói muốn có đồng hồ Daniel Wellington nhưng hơi đắt."),
    ("assistant", "DW trong tầm đó hơi khó — thường 1.5-2 triệu chính hãng. Thay vào đó có thể xem Fossil hoặc voucher Tiki 800k để Hà tự chọn."),
    ("user", "Tôi sẽ tặng voucher Tiki 800k, tiện hơn. Ngày 25 team tôi có team building ở Đà Nẵng, 2 ngày 1 đêm."),
    ("assistant", "Tháng này bận: deadline 15, sinh nhật Hà 20, team building Đà Nẵng 25-26. Công ty lo vé máy bay chưa?"),
    ("user", "Công ty lo hết. Cuối tháng ngày 30 tôi về Hải Phòng thăm bố mẹ, thường lệ hàng tháng."),
    ("assistant", "Summary:\n- 15/05: Deadline tech design doc\n- 20/05: Sinh nhật Hà (voucher Tiki 800k)\n- 25-26/05: Team building Đà Nẵng\n- 30/05: Về Hải Phòng"),
    ("user", "Cảm ơn! À tôi đang plan đi Nhật tháng 8 với bạn bè — Tuấn và Quân. 7 ngày, Tokyo và Osaka."),
    ("assistant", "Nhật tháng 8 là peak season (Obon). Apply visa sớm — ít nhất 2 tháng trước. Passport hạn không?"),
    ("user", "Passport hạn đến 2028. Visa chưa làm. Budget nhóm tôi khoảng 30-35 triệu/người bao gồm vé máy bay."),
    ("assistant", "Budget 30-35 triệu 7 ngày Nhật là vừa đủ. Vé khứ hồi VN-Tokyo tầm 8-12 triệu nếu book sớm. JR Pass 7 ngày khoảng 5 triệu — rất đáng cho Tokyo + Osaka. Apply visa tháng 6, cần bank statement 3 tháng."),
    ("user", "Tôi sẽ để Tuấn lo visa vì Tuấn cẩn thận hơn tôi. Bạn có gợi ý itinerary Nhật 7 ngày không?"),
    ("assistant", "7 ngày Tokyo-Kyoto-Osaka:\n- Ngày 1-3: Tokyo (Shinjuku, Shibuya, Asakusa, Akihabara)\n- Ngày 4: Kamakura day trip\n- Ngày 5: Shinkansen đến Kyoto (Fushimi Inari, Kinkakuji)\n- Ngày 6: Nara day trip + Osaka\n- Ngày 7: Osaka (Dotonbori, mua sắm Shinsaibashi)\n\nBudget ăn uống ~1-1.5 triệu VND/ngày là comfortable."),
    ("user", "Perfect! Tôi sẽ share itinerary này với Tuấn và Quân. Cảm ơn bạn."),
    ("assistant", "Chúc chuyến đi Nhật vui vẻ! Đặt vé sớm nhất có thể để có giá tốt."),
])


# ── USER 2: Lan, 23, HUST student, Federated Learning research ────────────

lan_s1 = mkcsv([
    ("user", "Xin chào! Tôi tên là Lan, 23 tuổi, sinh viên năm cuối Khoa học Máy tính tại Đại học Bách khoa Hà Nội."),
    ("assistant", "Chào Lan! Bách khoa là trường kỹ thuật hàng đầu. Bạn đang làm luận văn tốt nghiệp chủ đề gì?"),
    ("user", "Luận văn về Federated Learning cho phát hiện gian lận thanh toán. GVHD là GS. Nguyễn Thanh Hải. Deadline nộp 30/06."),
    ("assistant", "FL for fraud detection — rất thực tiễn! FL giúp train model mà không cần share raw data. Bạn dùng framework nào — Flower, PySyft hay TensorFlow Federated?"),
    ("user", "Tôi dùng Flower (flwr) vì documentation tốt và flexible hơn TFF."),
    ("assistant", "Flower rất clean! Với fraud detection, bạn giải quyết class imbalance như thế nào? Fraud thường <1% data."),
    ("user", "Đang thử SMOTE trước khi train local model. Kết quả không ổn định: precision cao nhưng recall thấp."),
    ("assistant", "High precision, low recall = model conservative, miss nhiều fraud cases. Thử: (1) Focal Loss thay BCE, (2) FedProx thay FedAvg, (3) Weighted aggregation theo fraud sample count. Bạn đã có centralized baseline chưa?"),
    ("user", "Chưa, cần làm baseline comparison. Tôi học tốt nhất khi có ví dụ cụ thể và so sánh — bạn giải thích kiểu đó rất phù hợp với tôi."),
    ("assistant", "Ghi nhận! Tôi sẽ luôn kèm ví dụ và comparison. Bạn đang train trên dataset nào?"),
    ("user", "PaySim synthetic và một phần data thật từ fintech Việt Nam qua GVHD. Data anonymized kỹ. Lab có 4 GPU RTX 3090."),
    ("assistant", "4x RTX 3090 là tốt cho research! PaySim là standard benchmark. Với data thật, đã kiểm tra differential privacy requirements chưa?"),
    ("user", "GVHD nói DP là nice-to-have, không bắt buộc. Tôi viết thesis bằng LaTeX trên VSCode với LaTeX Workshop extension, MacBook M2 14-inch."),
    ("assistant", "M2 Pro chạy PyTorch MPS rất nhanh! Remote SSH vào lab GPU để train nặng là setup tốt. Tips: dùng tmux trên server để session persist. Và Weights & Biases để track experiments."),
    ("user", "Tôi chưa dùng wandb. Bạn có thể guide cách setup không?"),
    ("assistant", "Setup wandb:\n```python\nimport wandb\nwandb.init(project='federated-fraud', name='fedprox-run1')\nwandb.log({'loss': loss, 'accuracy': acc, 'round': round_num})\n```\nĐăng ký free tại wandb.ai, pip install wandb, wandb login. Dashboard tự tạo."),
    ("user", "Hay! Tôi sẽ setup ngay hôm nay. Bạn biết papers hay về federated learning for imbalanced data không?"),
    ("assistant", "Papers hay:\n1. 'SCAFFOLD: Stochastic Controlled Averaging for Federated Learning'\n2. 'Tackling the Objective Inconsistency Problem' (FedNova)\n3. 'Federated Learning on Non-IID Data Silos' (survey)\n\nArXiv search 'federated learning imbalanced fraud' ra nhiều kết quả 2023-2024."),
    ("user", "Cảm ơn! Tôi thấy FL thực sự là hướng đi hay cho privacy-preserving AI."),
    ("assistant", "Đúng vậy! FL là enabling technology cho AI trong healthcare, finance — những domain mà data nhạy cảm và không thể tập trung. Luận văn của bạn rất đúng thời điểm."),
])

lan_s2 = mkcsv([
    ("user", "Chào! Hôm nay tôi muốn nói về chuyện cá nhân. Tôi đang có người yêu tên Tuấn, 25 tuổi, làm data engineer ở VNG."),
    ("assistant", "Cả hai đều làm tech, chắc có nhiều chủ đề chung! Bạn và Tuấn quen nhau như thế nào?"),
    ("user", "Quen qua câu lạc bộ AI của trường. Tuấn học Bách khoa nhưng khóa trước tôi 2 năm. Yêu nhau 1 năm rưỡi rồi."),
    ("assistant", "1 năm rưỡi — đủ lâu để hiểu nhau! Nhóm bạn thân của bạn thế nào?"),
    ("user", "Nhóm bạn thân 4 người: tôi, Tuấn, Hương (cùng lớp, làm computer vision research), và Khánh (học NEU, làm tài chính). Hay ăn tối thứ 6 khu Trần Đại Nghĩa."),
    ("assistant", "Nhóm đa dạng field! Gia đình bạn ở Hà Nội không?"),
    ("user", "Đúng, tôi là người Hà Nội gốc, quận Hai Bà Trưng. Bố tôi là bác sĩ tại Bệnh viện Bạch Mai, mẹ dạy toán cấp 3 trường Trần Phú. Tôi là con một."),
    ("assistant", "Gia đình trí thức cả. Bố mẹ có ủng hộ bạn làm AI research không?"),
    ("user", "Rất ủng hộ, chỉ mẹ hay hỏi 'bao giờ đi làm'. Tôi đang phân vân giữa đi làm và học PhD."),
    ("assistant", "PhD vs industry! Bạn đang xem xét PhD ở đâu?"),
    ("user", "NUS Singapore và Đức (RWTH Aachen, TU Munich). Tuấn nói sẽ ủng hộ dù tôi chọn hướng nào."),
    ("assistant", "NUS CS PhD funding tốt (~2800 SGD/tháng stipend). GVHD có kết nối với NUS không? Warm introduction từ GVHD quan trọng hơn cold email nhiều."),
    ("user", "GVHD có collaboration với một GS ở NUS, có thể giới thiệu. Tuần tới tôi gặp GVHD để bàn."),
    ("assistant", "Tốt lắm! Trước khi gặp GVHD, chuẩn bị: (1) Research statement draft 1 trang, (2) List 3 GS ở NUS phù hợp research interest, (3) Câu hỏi về timeline apply."),
    ("user", "Cảm ơn checklist! Ngày mai là sinh nhật Hương, nhóm tôi tổ chức surprise party. Có ý tưởng quà không?"),
    ("assistant", "Hương làm CV research — tặng tech hoặc creative:\n- Gift card Shopee 500-700k để tự chọn\n- Khóa học online Coursera\n\nBudget group hay individual?"),
    ("user", "Individual, budget tôi khoảng 400-500k. Tôi nghĩ sách thì Hương không có thời gian đọc vì bận thesis."),
    ("assistant", "Gift card Shopee 500k là safe bet — tiện, Hương tự chọn thứ cần. Gói đẹp một chút là xong."),
    ("user", "Quyết định rồi! Khánh bạn tôi vừa được thăng chức manager ở công ty tài chính. Chắc tôi sẽ rủ cả nhóm đi ăn mừng cuối tuần này."),
    ("assistant", "Khánh thăng chức — vui quá! Cuối tuần nhóm hay ăn ở đâu? Khu Trần Đại Nghĩa như thường lệ hay đổi địa điểm đặc biệt?"),
    ("user", "Tôi nghĩ lần này đổi địa điểm, ăn nhà hàng ngon hơn một chút để celebrate. Có thể mỗi người góp 200-300k."),
    ("assistant", "200-300k/người — tầm mid-range, thoải mái. Khu Tây Hồ hoặc Tràng Tiền Plaza có nhiều options đẹp."),
])

lan_s3 = mkcsv([
    ("user", "Lan đây. Tôi cần plan timeline 2 tháng còn lại trước khi nộp luận văn. Deadline 30/06."),
    ("assistant", "Deadline 30/06, hiện tại tháng 5. Bạn đã hoàn thành được bao nhiêu phần rồi?"),
    ("user", "Literature review 80%, system design xong, implementation 70% (còn aggregation server), experiments mới có baseline chưa có federated results."),
    ("assistant", "Timeline gợi ý:\n\nTháng 5:\n- Week 1-2: Hoàn thiện aggregation server\n- Week 3: Run federated experiments\n- Week 4: Analysis + plots\n\nTháng 6:\n- Week 1-2: Viết chapter 4-5\n- Week 3: Hoàn thiện thesis\n- Week 4: Buffer + nộp"),
    ("user", "Tight nhưng feasible. Tuần này tôi phải dự RIVF 2026 ở Hải Phòng — hội thảo AI, 3 ngày 16-18/05. GVHD có invited talk ở đó."),
    ("assistant", "RIVF là networking tốt! Sau RIVF còn 6 tuần đến deadline. Bạn cần bao lâu để run experiments?"),
    ("user", "Một run mất 6-8 tiếng trên lab GPU. Cần 5 configurations cho ablation study. Có thể chạy 2 experiments song song với 4 GPU."),
    ("assistant", "Parallel experiments → ~2 ngày. Sau đó 3-4 ngày analyze và vẽ plots. Timeline sau RIVF:\n- 19-20/05: Run experiments\n- 21-23/05: Analysis + plots\n- 24/05-7/06: Viết chapter 4-5\n- 8-21/06: Hoàn thiện\n- 22-30/06: Buffer + nộp"),
    ("user", "Perfect! Tôi cũng cần chuẩn bị presentation cho defense khoảng 15-20/07."),
    ("assistant", "Defense 20-25 phút:\n1. Title + motivation (2 min)\n2. Problem statement (3 min)\n3. Related work (2 min)\n4. Proposed method (5 min)\n5. Experiments + results (5 min)\n6. Conclusion (2 min)\n7. Q&A (10-15 min)\n\nDùng Beamer LaTeX để consistent với thesis."),
    ("user", "Tôi sẽ dùng Beamer. Một vấn đề kỹ thuật: tôi cần implement REST API cho FL coordinator. Bạn có thể guide không?"),
    ("assistant", "FL coordinator API cần: POST /round/start, GET /round/{id}/status, POST /client/update, GET /model/global. Dùng FastAPI? Authentication: API key per client đơn giản hơn JWT cho research prototype."),
    ("user", "FastAPI với Python trên Docker. API key là đủ rồi. Bạn có thể viết middleware authentication không?"),
    ("assistant", "```python\nfrom fastapi import Security, HTTPException\nfrom fastapi.security import APIKeyHeader\n\napi_key_header = APIKeyHeader(name='X-API-Key')\n\nasync def verify_api_key(key: str = Security(api_key_header)):\n    client = await db.clients.find_one({'api_key': key})\n    if not client:\n        raise HTTPException(403, 'Invalid API key')\n    return client\n```"),
    ("user", "Rõ ràng và practical! Tôi implement được rồi. Bạn có recommend podcast về AI/ML để nghe khi đi bộ sáng không?"),
    ("assistant", "Podcasts tốt:\n1. Lex Fridman — interviews sâu với researchers\n2. TWIML AI Podcast — technical, focused\n3. Privacy Please — privacy-preserving ML, liên quan trực tiếp FL research"),
    ("user", "Tôi sẽ bắt đầu với Lex Fridman tập LeCun. Bạn thấy quan điểm LeCun về AGI thế nào?"),
    ("assistant", "LeCun skeptical về LLMs reaching AGI, argue cần world models và JEPA architecture. Hinton lo existential risk nhiều hơn. Cuộc debate rất thú vị!\n\nRelevant với research bạn: FL có thể unlock diverse real-world data mà centralized training không thể touch — compelling motivation cho thesis."),
    ("user", "Tôi sẽ đưa argument đó vào motivation section. Cảm ơn bạn rất nhiều!"),
    ("assistant", "Vui vì giúp được Lan! Chúc bạn thành công với thesis!"),
])

lan_s4 = mkcsv([
    ("user", "Lan đây. Tôi vừa nhận offer từ DataMind — AI startup healthcare ở HCM. 18 triệu/tháng + 0.5% stock option. VinAI cũng offer 22 triệu ở Hà Nội. Phải chọn như thế nào?"),
    ("assistant", "Quan trọng nhất: bạn muốn làm research hay applied AI? VinAI = research publications. DataMind = product + real-world impact. Budget-wise VinAI cao hơn base, DataMind có equity upside."),
    ("user", "Tôi thích applied AI — tác động thực tế cao hơn. Healthcare AI nghe hay. Nhưng DataMind ở HCM, xa gia đình và xa Tuấn."),
    ("assistant", "Long-distance relationship là điểm trừ lớn. Đã nói với Tuấn chưa?"),
    ("user", "Rồi, Tuấn nói ủng hộ nhưng thích tôi ở Hà Nội hơn. Thực ra Tuấn cũng đang xem cơ hội ở HCM, nếu tôi đi thì anh ấy có thể chuyển theo."),
    ("assistant", "Nếu cả hai cùng move HCM thì picture khác hẳn! HCM có startup tech ecosystem tốt hơn. Bạn đã visit DataMind office chưa?"),
    ("user", "Chưa, họ invite onsite tuần sau, cover vé máy bay. Tôi chưa bao giờ vào HCM."),
    ("assistant", "Chắc chắn nên đi onsite! Cơ hội xem văn hóa công ty thực tế và lần đầu trải nghiệm HCM. Khi onsite hỏi về: tech stack, tốc độ ship, growth path, team size."),
    ("user", "Tôi sẽ đăng ký. Nếu không đi PhD và không vào 2 offer này, tôi còn option nào khác không?"),
    ("assistant", "Options khác:\n1. Research intern ở Vingroup AI Lab hoặc FPT AI Center (6-12 tháng)\n2. Làm 1-2 năm industry rồi apply PhD\n3. Remote work cho startup nước ngoài từ Hà Nội\n\nVới profile của bạn, cả VinAI lẫn DataMind đều là excellent choices."),
    ("user", "Cảm ơn! Tôi nghĩ tôi sẽ đi onsite DataMind xem thực tế rồi quyết định. Tips gì cho buổi onsite không?"),
    ("assistant", "Onsite tips:\n- Observe không khí văn phòng\n- Talk 1:1 với engineer (không phải HR) về daily workflow\n- Hỏi: 'Điều gì bạn thích nhất và ít thích nhất khi làm ở đây?'\n- Trust your gut feeling sau khi gặp team"),
    ("user", "Ghi nhận! Tuần sau tôi sẽ update bạn. Tôi vừa hoàn thành aggregation server — FL experiments đang chạy. Đang hồi hộp chờ results!"),
    ("assistant", "Exciting! Đây là moment quan trọng trong thesis journey. Bạn theo dõi qua wandb dashboard chứ? Metrics nào bạn expect sẽ cải thiện?"),
    ("user", "Theo dõi qua wandb! Tôi expect recall cải thiện với FedProx + weighted aggregation. Nếu recall tăng >10% so với baseline mà giữ được precision thì đó là contribution tốt."),
    ("assistant", "10% recall improvement trong fraud detection là significant — có thể là several million dollars fraud prevented per year. Đưa số này vào thesis với business impact framing sẽ rất powerful."),
    ("user", "Ý hay! Tôi sẽ thêm section về business impact estimation. Bạn có biết fraud detection accuracy translates to business value như thế nào không?"),
    ("assistant", "Framework đơn giản:\n- Average fraud transaction value × False Negatives prevented per day × 365 = Annual prevented loss\n- Ví dụ: avg fraud = 2 triệu VND, model catch thêm 10 frauds/ngày = 7.3 tỷ VND/năm\n\nCite số từ NHNN hoặc Napas để ground the estimate."),
    ("user", "Cực hay! Tôi sẽ tìm data từ NHNN. Cảm ơn bạn đã luôn có những góc nhìn practical và deep!"),
    ("assistant", "Bạn đang làm rất tốt Lan — từ technical đến career planning đều rõ ràng và thoughtful. Chúc experiments ra kết quả tốt!"),
])


# ── USER 3: Hùng, 35, owner of 'Phở Bắc' restaurant chain ─────────────────

hung_s1 = mkcsv([
    ("user", "Chào! Tôi tên là Hùng, 35 tuổi. Tôi điều hành chuỗi nhà hàng phở 'Phở Bắc' với 3 cơ sở tại Hà Nội."),
    ("assistant", "Chào anh Hùng! 3 cơ sở ở Hà Nội — anh đang mở rộng hay optimize hiện tại?"),
    ("user", "Ba cơ sở: Hoàn Kiếm (flagship, mở 2018), Cầu Giấy (2021), Hoàng Mai (2023). Tổng doanh thu tháng trước 380 triệu đồng."),
    ("assistant", "380 triệu/tháng — trung bình 127 triệu/cơ sở. Cơ sở nào perform tốt nhất?"),
    ("user", "Hoàn Kiếm 180 triệu — nhiều khách du lịch nước ngoài. Cầu Giấy 130 triệu — dân văn phòng. Hoàng Mai mới nhất chỉ 70 triệu."),
    ("assistant", "Hoàng Mai 70 triệu sau 1.5 năm hơi chậm. Cạnh tranh ở đó thế nào?"),
    ("user", "Nhiều quán phở local giá rẻ. Tôi đang dùng Facebook, GrabFood, ShopeeFood. Google Ads chưa làm. Có thuê 1 bạn part-time lo social media nhưng không ổn định."),
    ("assistant", "Anh đang bỏ sót kênh quan trọng — người tìm 'phở Hà Nội' đều search Google. Anh có Google My Business listing chưa?"),
    ("user", "Có nhưng ít review lắm — 15-20 review mỗi cơ sở. Tôi biết quan trọng nhưng không biết cách tăng."),
    ("assistant", "Chiến lược tăng Google Reviews:\n1. QR code dẫn đến trang review tại bàn và trên bill\n2. Nhân viên nhắc nhở khách satisfied\n3. Reply TẤT CẢ reviews (cả xấu) — cho thấy chủ active\n\nTarget: 50+ reviews, 4.5+ stars trong 3 tháng."),
    ("user", "Sẽ làm ngay. Team tôi: bếp trưởng Hoàng (10 năm kinh nghiệm), quản lý Linh (em gái tôi), 15 nhân viên chia đều cho 3 cơ sở."),
    ("assistant", "Hoàng 10 năm là asset quan trọng. Anh có kế hoạch giữ chân Hoàng không? Bếp trưởng giỏi hay bị offer cao hơn."),
    ("user", "Hoàng được 18 triệu/tháng cộng 3% revenue Hoàn Kiếm (~5.4 triệu thêm). Tổng ~23-24 triệu."),
    ("assistant", "Package tốt! Recommend formalize thỏa thuận bằng văn bản để tránh misunderstanding. Vợ anh có tham gia business không?"),
    ("user", "Vợ tôi Thảo, 33 tuổi, có background kế toán — giúp quản lý tài chính. Chúng tôi có 2 con: bé Khoa 7 tuổi và bé An 4 tuổi."),
    ("assistant", "Thảo làm kế toán là lý tưởng! Family business với vợ là CFO — trust và alignment cao. Anh có balance được time giữa gia đình và nhà hàng không?"),
    ("user", "Khó, nhà hàng tối rất bận. Tôi cố sáng thứ 7 và chủ nhật cho con. Thảo nhiều lúc phàn nàn tôi về nhà muộn."),
    ("assistant", "Vấn đề phổ biến với F&B — peak hours trùng với family time. Anh có thể delegate nhiều hơn cho Linh và shift managers để step away sau 8pm một vài ngày/tuần không?"),
    ("user", "Tôi cần build trust với Linh hơn. Hiện tại tôi vẫn micromanage quá nhiều. Đó là điều tôi cần cải thiện."),
    ("assistant", "Self-awareness đó là bước đầu tiên! Micromanagement cản trở cả team lẫn anh. Thử bắt đầu với 1-2 decisions nhỏ mỗi tuần hoàn toàn giao cho Linh, observe kết quả."),
])

hung_s2 = mkcsv([
    ("user", "Hùng đây. Tôi đang lên menu mùa hè, muốn thêm món mới thu hút khách trẻ. Đang nghĩ đến phở cuộn — đang trendy trên TikTok."),
    ("assistant", "Phở cuộn rất hot trên social! Instagrammable, food cost thấp. Anh Hoàng nghĩ sao?"),
    ("user", "Hoàng hơi ngại vì sợ ảnh hưởng brand phở truyền thống. Tôi nghĩ làm separate menu 'Phở Bắc Hiện Đại'. Hoàng sẽ test recipe tuần này."),
    ("assistant", "'Phở Bắc Hiện Đại' là smart branding — separate identity, không cannibalize brand gốc. Khi test, internal tasting trước, rồi soft launch với 10-15 khách regular."),
    ("user", "Tôi muốn launch trước 1/6 — còn 2.5 tuần. Bạn bè tôi Dũng là food TikToker, 80k followers, đồng ý review đổi lấy bữa ăn miễn phí."),
    ("assistant", "Micro-influencer marketing tốt hơn macro cho F&B! Dũng 80k food-focused followers rất valuable. Tips: shoot tối ở Hoàn Kiếm (atmosphere đẹp nhất), để Dũng tự viết script (authentic > scripted)."),
    ("user", "Tôi chưa có TikTok account. Anh Hoàng không biết TikTok. Nhưng nhân viên trẻ chắc có người giỏi."),
    ("assistant", "Offer nhân viên 22-25 tuổi thêm 500k-1 triệu/tháng để run TikTok. Họ tự film, edit, post — anh approve content. Win-win."),
    ("user", "Tôi nghĩ sẽ hỏi Trang — nhân viên Hoàn Kiếm, 22 tuổi, hay quay video. Lương hiện 6 triệu, tôi sẽ tăng lên 7 triệu nếu nhận thêm TikTok."),
    ("assistant", "7 triệu cho Trang + TikTok presence — investment nhỏ, potential return lớn. Khi nói chuyện với Trang: clear về 3-4 posts/tuần, Phở Bắc owns videos, trial 1 tháng."),
    ("user", "Sẽ làm hôm nay. Tôi cũng đang nghĩ loyalty program. Bạn recommend giải pháp nào cho nhà hàng vừa?"),
    ("assistant", "Options:\n- Stamp card giấy: cost gần 0, không cần tech (bắt đầu test behavior)\n- Beep app: free tier, QR-based, tốt cho F&B Việt Nam\n- Momo Business: nhiều người dùng, tích hợp Momo payment\n\nSuggest bắt đầu stamp card 2 tháng → rồi mới invest vào app solution."),
    ("user", "Hợp lý. Bắt đầu simple rồi scale. Checklist launch phở cuộn cho tôi được không?"),
    ("assistant", "Checklist launch phở cuộn:\n- Recipe finalized + documented\n- Giá xác nhận (recommend 55k/set 2 người)\n- Photo shoot cho menu + social\n- Training nhân viên 3 cơ sở\n- In menu mới hoặc insert\n- 5-7 posts/reels chuẩn bị trước\n- Tạo TikTok @phobachanoi\n- Brief Dũng về video shoot\n- Tasting session VIP cuối tuần trước launch"),
    ("user", "Perfect checklist! Tôi sẽ in ra và track. Cảm ơn bạn!"),
    ("assistant", "Chúc launch thành công anh Hùng! Nhớ collect feedback từ tasting session."),
])

hung_s3 = mkcsv([
    ("user", "Hùng đây. Tôi có vấn đề nhân sự: nhân viên Bình ở Cầu Giấy hay đi muộn và thái độ với khách không tốt. Đã nhắc 2 lần miệng, vẫn tái phạm."),
    ("assistant", "Đã nhắc 2 lần miệng mà vẫn tái phạm — cần escalate lên cảnh báo văn bản. Anh có biết nguyên nhân Bình đi muộn không?"),
    ("user", "Chưa hỏi. Quản lý nói Bình mất hứng, hay nhìn điện thoại. Tôi sẽ gặp Bình trực tiếp ngày mai."),
    ("assistant", "Gợi ý cho buổi gặp: mở đầu bằng 'tôi muốn hiểu tình hình', hỏi về khó khăn cá nhân, nêu facts cụ thể (đi muộn X lần, khách complain ngày Y), rồi state expectations rõ ràng. Outcome: cảnh báo văn bản + commitment từ Bình."),
    ("user", "Tôi không giỏi HR, hay tránh xung đột. Nhưng tôi hiểu phải làm. Bên cạnh đó, Linh em gái tôi đang có xung đột với quản lý Hoàng Mai tên Phương về giờ mở cửa."),
    ("assistant", "Giờ mở cửa — operational decision. Phương muốn thay đổi gì?"),
    ("user", "Phương muốn dời từ 6h lên 7h vì ít khách sáng sớm. Linh không đồng ý, sợ mất khách đi làm sớm. Hai người cãi nhau."),
    ("assistant", "Hai vấn đề: (1) Quyết định giờ mở cửa — cần data revenue 6-7h. (2) Nhận xét inappropriate của Phương về family dynamics — cần address riêng. Anh là người quyết định, không phải Linh hay Phương."),
    ("user", "Tôi sẽ check data doanh thu 6-7h trong 3 tháng. Nếu <5% doanh thu ngày, tôi đồng ý với Phương nhưng yêu cầu Phương xin lỗi Linh."),
    ("assistant", "Data-driven và fair! Khi communicate: frame là 'quyết định của anh dựa trên data', không phải 'Linh đúng/sai'. Giữ face cho cả hai."),
    ("user", "Đúng. Tôi cũng cần viết rõ role & responsibility — hiện tại informal quá. Bạn có template RACI không?"),
    ("assistant", "RACI matrix cho chuỗi 3 cơ sở:\n| Decision | Owner (Hùng) | GM (Linh) | Quản lý cơ sở | Head Chef |\n|---|---|---|---|---|\n| Menu changes | A | C | I | R |\n| Staff hire/fire | A | R | C | I |\n| Daily operations | I | C | R | - |\n| Pricing | A | R | C | C |\n| Hours | A | C | R | I |"),
    ("user", "Rất hữu ích! Cuối tháng này là kỷ niệm 5 năm mở Hoàn Kiếm — 1/6/2018. Tôi muốn celebrate với staff và khách VIP."),
    ("assistant", "5 năm anniversary! Ideas:\n\nStaff: team dinner sau giờ, recognize early employees, gift áo đồng phục mới\n\nKhách VIP: special menu 'original recipes from 2018', discount 18% ngày 1/6\n\nPR: Dũng làm mini-documentary về hành trình 5 năm\n\nBudget anh dự kiến bao nhiêu?"),
    ("user", "Budget khoảng 30-40 triệu cho toàn bộ event. Tôi muốn đây là event ý nghĩa với team, không chỉ về marketing."),
    ("assistant", "Điều quan trọng nhất: recognize và thank những người đã gắn bó từ đầu — Hoàng, Linh. Kể câu chuyện hành trình 5 năm với những khó khăn và milestone — authentic hơn nhiều so với event thuần marketing."),
    ("user", "Tôi sẽ viết letter của founder chia sẻ với toàn team về hành trình. Cảm ơn bạn!"),
    ("assistant", "Founder's letter — cảm động và memorable! Năm 5 là cột mốc quan trọng để reflect và reset direction. Chúc anh Hùng và Phở Bắc tiếp tục phát triển!"),
])

hung_s4 = mkcsv([
    ("user", "Hùng đây. POS Cukcuk của tôi hay bị chậm lúc peak hours 11h-1h trưa và 6h-8h tối. Nhân viên phải viết tay order, rất loạn."),
    ("assistant", "7 POS total, bottleneck peak hours — thường do server sync hoặc DB locking. Anh dùng cloud hay local server? Đã liên hệ Cukcuk support chưa?"),
    ("user", "Cloud, gói Standard. Chưa gọi support vì ngại. Bạn recommend alternatives không?"),
    ("assistant", "Trước khi switch (tốn kém + disruptive), thử gọi Cukcuk hotline báo lỗi cụ thể. Nếu vẫn không fix:\n- KiotViet: phổ biến nhất VN, nhiều features F&B, ~500k/tháng/cơ sở\n- Sapo POS: UI tốt, tích hợp GrabFood/ShopeeFood native"),
    ("user", "Tôi sẽ gọi Cukcuk và book demo KiotViet + Sapo tuần sau. Tôi muốn dùng AI để phân tích POS data tối ưu menu. Có thực tế không?"),
    ("assistant", "Short-term khả thi ngay:\n- Phân tích doanh thu theo giờ, ngày, món\n- Happy hour pricing giờ thấp điểm\n- Cắt món bán <5% trong 3 tháng\n\nAI/ML phức tạp: cần nhiều data + tech. Bắt đầu với basic analytics từ POS export trước."),
    ("user", "Tôi chưa bao giờ analyze POS data seriously. Chỉ xem tổng doanh thu. Bạn guide basic analytics không?"),
    ("assistant", "5 metrics cần pull hàng tuần:\n1. Revenue by hour\n2. Revenue by day of week\n3. Top/bottom 10 items sold\n4. Average check size per location\n5. Table turnover rate\n\nPull 3 tháng gần nhất từ Cukcuk export → Google Sheets."),
    ("user", "Vợ Thảo giỏi Sheets hơn nhiều vì background kế toán. Thảo hay nói muốn contribute nhiều hơn nhưng không muốn full-time vì bé Khoa và bé An còn nhỏ."),
    ("assistant", "Giải pháp win-win: Thảo làm CFO part-time 2-3 tiếng/ngày, flexible hours. Analytics + finance. Title 'Co-founder & CFO' cũng hay cho family business brand."),
    ("user", "Tôi thích idea đó! Sẽ nói với Thảo tối nay. Ngày 20/6 là sinh nhật bé Khoa tròn 8 tuổi. Thảo muốn tổ chức tiệc ở Hoàn Kiếm sau giờ đóng cửa."),
    ("assistant", "Sinh nhật Khoa tại Hoàn Kiếm sau 10pm — private space hoàn toàn! Khoa thích chủ đề gì?"),
    ("user", "Khoa đang mê khủng long — dinosaur! An thì mê Doraemon."),
    ("assistant", "Tiệc dinosaur cho Khoa:\n- Decor: balloons xanh lá + banner 'Roar! Khoa 8 tuổi'\n- Bánh: đặt bánh kem hình T-Rex\n- Menu: phở yêu thích Khoa + pizza/gà rán cho bạn bè\n- Games: dinosaur egg hunt\n\nBé An có thể có Doraemon mini cake riêng để không tủi!"),
    ("user", "Ý tưởng tuyệt vời! Bé An sẽ rất vui có bánh Doraemon riêng. Cảm ơn bạn rất nhiều!"),
    ("assistant", "Phở Bắc và gia đình anh đều đang phát triển tốt! Tiếp tục vừa xây business vừa dành thời gian cho gia đình nhé anh Hùng."),
])

hung_s5 = mkcsv([
    ("user", "Chào! Tôi nhận được cơ hội từ investor tên Khoa, 42 tuổi, quản lý quỹ F&B. Muốn rót 2 tỷ đồng cho 20% equity Phở Bắc. Buổi gặp thứ 5 tuần sau."),
    ("assistant", "2 tỷ cho 20% → valuation 10 tỷ. Với doanh thu 4.56 tỷ/năm, P/Revenue ~2.2x — reasonable cho F&B chain có growth potential. Anh cần chuẩn bị gì?"),
    ("user", "Tôi không biết EBITDA là gì. Profit hàng tháng khoảng 50-60 triệu. Thảo quản lý tài chính nhưng chưa present kiểu investor-ready."),
    ("assistant", "EBITDA = operating profit trước adjustments tài chính. Với 380 triệu doanh thu và 50-60 triệu profit, EBITDA margin ~13-16% — khá tốt cho F&B.\n\nThảo cần chuẩn bị: P&L statement 12 tháng monthly, balance sheet, cash flow statement."),
    ("user", "Sẽ nhờ Thảo làm ngay. Tôi lo vì đây là lần đầu deal với investor. Bạn có thể roleplay buổi gặp không?"),
    ("assistant", "Tôi đóng vai investor Khoa:\n\nKhoa: Chào anh Hùng! Anh có thể pitch Phở Bắc cho tôi — tại sao khác với hàng trăm quán phở khác ở Hà Nội?"),
    ("user", "Phở Bắc khác vì tập trung authentic Bắc kỳ recipe. Bếp trưởng Hoàng 10 năm học từ các cụ bà Hà Nội gốc. Nước dùng ninh 18 tiếng, không dùng bột ngọt. Quy trình chuẩn hóa để consistent across 3 cơ sở."),
    ("assistant", "Khoa: Standardization là key để scale — tốt! Với 2 tỷ, anh plan mở bao nhiêu cơ sở? Timeline?"),
    ("user", "2 cơ sở trong 18 tháng — Tây Hồ và Long Biên. Chi phí mỗi cơ sở 600-700 triệu. Còn lại cho marketing và technology upgrade."),
    ("assistant", "Khoa: 'Technology upgrade' — cụ thể là gì? Và quality control khi scale — Hoàng có đảm đương được không?"),
    ("user", "Technology: POS mới và đặt bàn online. Quality: Hoàng train bếp trưởng mới mỗi cơ sở, checklist kiểm tra hàng tuần."),
    ("assistant", "Khoa: Honest answer — good! Câu khó: exit strategy của anh trong 5 năm tới là gì?\n\n(Pause roleplay — đây là câu investor hay hỏi làm founder lúng túng. Anh đã nghĩ về exit chưa?)"),
    ("user", "Thực ra chưa nghĩ đến exit. Tôi chỉ muốn grow business. Phải trả lời thế nào?"),
    ("assistant", "Answer honest và reasonable:\n\n'Tôi tập trung organic growth — mục tiêu 5 năm là 8-10 cơ sở, EBITDA 18-20%, xem xét acquisition bởi F&B group lớn hoặc franchise model. Về dilution: tôi cam kết không raise thêm trong 24 tháng, và offer right of first refusal cho anh trước mọi vòng sau.'"),
    ("user", "20% equity có nhiều quá không? Tôi muốn negotiate xuống 15%."),
    ("assistant", "2 tỷ/15% → valuation 13.3 tỷ (~2.9x revenue) — aggressive cho F&B VN.\n\nStrategy: Counter với 17-18% (không nhảy thẳng xuống 15%). Justify bằng: growth trajectory, brand value, standardization đã build. Add milestone-based vesting nếu muốn."),
    ("user", "Cảm ơn! Tôi tự tin hơn rất nhiều. Thứ 5 sau buổi gặp tôi sẽ update kết quả."),
    ("assistant", "Chúc anh Hùng thành công! Mang theo: financial summary, photos 3 cơ sở, menu + USPs, growth plan 5-7 slides. Và nhớ: anh cũng đang evaluate investor — hỏi về track record và value-add của họ. Good luck!"),
])


FILES = {
    f"tests/data/{TENANT}/{USER_MINH}/c1100001-0000-4000-8000-300000000001.csv": minh_s1,
    f"tests/data/{TENANT}/{USER_MINH}/c1100001-0000-4000-8000-300000000002.csv": minh_s2,
    f"tests/data/{TENANT}/{USER_MINH}/c1100001-0000-4000-8000-300000000003.csv": minh_s3,
    f"tests/data/{TENANT}/{USER_LAN}/c2200002-0000-4000-8000-300000000001.csv":  lan_s1,
    f"tests/data/{TENANT}/{USER_LAN}/c2200002-0000-4000-8000-300000000002.csv":  lan_s2,
    f"tests/data/{TENANT}/{USER_LAN}/c2200002-0000-4000-8000-300000000003.csv":  lan_s3,
    f"tests/data/{TENANT}/{USER_LAN}/c2200002-0000-4000-8000-300000000004.csv":  lan_s4,
    f"tests/data/{TENANT}/{USER_HUNG}/c3300003-0000-4000-8000-300000000001.csv": hung_s1,
    f"tests/data/{TENANT}/{USER_HUNG}/c3300003-0000-4000-8000-300000000002.csv": hung_s2,
    f"tests/data/{TENANT}/{USER_HUNG}/c3300003-0000-4000-8000-300000000003.csv": hung_s3,
    f"tests/data/{TENANT}/{USER_HUNG}/c3300003-0000-4000-8000-300000000004.csv": hung_s4,
    f"tests/data/{TENANT}/{USER_HUNG}/c3300003-0000-4000-8000-300000000005.csv": hung_s5,
}

base = pathlib.Path(".")
for rel, content in FILES.items():
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    rows = content.count("\n") - 1
    print(f"  {rel.replace('tests/data/', '')}  ({rows} turns)")

print(f"\nTotal: {len(FILES)} files")
