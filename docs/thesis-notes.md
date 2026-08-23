# Sổ tay khóa luận

Ghi lại mọi thứ cần cho chương kết quả. Ghi ngay lúc làm, đừng để cuối kỳ nhớ lại.

## Trạng thái nền của hệ thống

Dùng để đối chiếu mỗi lần tiêm lỗi và mỗi lần dựng twin.

- Ngày đo: 2026-08-09, sau bước 0.3
- Cluster: kind `boutique`, 1 node, Kubernetes v1.36.1
- Đang chạy: 12 pod Online Boutique, có loadgenerator bơm traffic, chưa có tracing và chưa có Prometheus
- **Tổng CPU: 98m** (khoảng 0.1 lõi)
- **Tổng RAM: 341Mi**

RAM từng pod (`kubectl top pods`):

```
NAME                      CPU(cores)   MEMORY(bytes)
adservice                 5m           86Miâucartservice               10m          51Mi
checkoutservice           2m           6Mi
currencyservice           12m          33Mi
emailservice              4m           36Mi
frontend                  27m          11Mi
loadgenerator             6m           47Mi
paymentservice            2m           21Mi
productcatalogservice     14m          8Mi
recommendationservice     10m          31Mi
redis-cart                4m           5Mi
shippingservice           2m           6Mi
```

Nhận xét: 341Mi thấp hơn nhiều so với 2.5GB dự trù cho Online Boutique ở mục 2 KLTN.md. Đây là RAM *đang dùng*, chưa tính phần Java và .NET giữ sẵn trong heap, nhưng vẫn cho thấy ngân sách RAM rộng hơn dự kiến. Chỉ số này chỉ có ý nghĩa khi so với lần đo sau khi đã bật đủ tracing và Prometheus (bước 0.6) — đó mới là con số nền thật để trừ ra phần còn lại cho twin.

`adservice` chiếm 86Mi, nhiều nhất, đúng như dự đoán vì nó chạy JVM. Đây là một lý do nữa để loại nó khỏi twin (mục 4 KLTN.md).

- p95 latency luồng đặt hàng khi khỏe mạnh: chưa đo được, chờ bước 0.5
- Error rate khi khỏe mạnh: chưa đo được, chờ bước 0.5

## Nhật ký từng phase

Mỗi mục ghi: làm gì, tắc ở đâu, sửa thế nào, mất bao lâu.

### Phase 0 — Hạ tầng

**0.4 xong ngày 2026-08-09.** Jaeger nhận trace từ 7 service. Ô Service trong Jaeger hiện 8 mục vì Jaeger tự ghi trace về chính nó.

Kiểm chứng được cạnh tới `cartservice` qua span client của `frontend`. Tag thật của span đó:

```
rpc.method               hipstershop.CartService/GetCart
rpc.system.name          grpc
rpc.response.status_code OK
server.address           10.96.119.247
server.port              7070
span.kind                client
otel.scope.name          go.opentelemetry.io/contrib/instrumentation/google.golang.org/grpc/otelgrpc
otel.scope.version       0.69.0
```

Hai điều khác dự đoán ban đầu, đã sửa lại trong KLTN.md mục 4:

- Không có tag `rpc.service`. Tên gRPC nằm trong `rpc.method`, dạng `package.Service/Method`.
- `server.address` là ClusterIP, không phải tên service. Đối chiếu `kubectl get svc` xác nhận `10.96.119.247:7070` đúng là `cartservice`.

Hệ quả cho phase 1: `runtime_graph.py` phải dựng bảng tra ClusterIP → tên service ở mỗi lần snapshot, không được hardcode IP, vì IP đổi khi Service bị tạo lại và namespace `twin` có dải IP riêng.

**0.5 xong ngày 2026-08-09.** spanmetrics chạy, endpoint `localhost:8889/metrics` cho 629 dòng, trong đó 464 dòng có nhãn `server_address`.

Ví dụ đã kiểm chứng, span client của checkoutservice gọi sang cartservice:

```
traces_span_metrics_calls_total{job="checkoutservice", rpc_method="hipstershop.CartService/EmptyCart",
  server_address="10.96.119.247", server_port="7070", service_name="checkoutservice",
  span_kind="SPAN_KIND_CLIENT", status_code="STATUS_CODE_UNSET"} 19
```

Đây là bằng chứng đo được `cartservice` dù nó không phát trace.

**Nhưng độ phủ nhãn không đồng đều giữa các ngôn ngữ.** Span client của `recommendationservice` (Python) **không có** `server_address`, chỉ có `span_name="/hipstershop.ProductCatalogService/ListProducts"`:

```
traces_span_metrics_calls_total{job="recommendationservice", rpc_method="ListProducts",
  service_name="recommendationservice", span_kind="SPAN_KIND_CLIENT",
  span_name="/hipstershop.ProductCatalogService/ListProducts", ...} 471
```

Các service Go dùng semconv mới nên có `server_address`; thư viện Python dùng quy ước cũ nên không. Nghĩa là **bắt buộc phải có cả hai quy tắc** đã ghi ở mục 4 KLTN.md: tra IP là chính, tách tên gRPC từ `rpc_method` hoặc `span_name` là dự phòng. Không được chỉ làm một cái.

Chi tiết nhỏ cần nhớ khi viết truy vấn PromQL: nhãn `rpc_method` không đồng nhất — service Go ghi cả đường dẫn `hipstershop.CartService/EmptyCart`, service Node.js và Python chỉ ghi tên hàm `Convert`, `ListProducts`. Muốn nhóm theo service đích thì dựa vào `server_address` trước, `span_name` sau.

**0.6 xong ngày 2026-08-23.** Cài `kube-prometheus-stack` chart 88.5.3 (Prometheus operator v0.93.1) bằng Helm 4.2.4, vào namespace riêng `monitoring`, cấu hình ở `infra/prometheus-values.yaml`.

13/13 mục tiêu scrape đều UP, trong đó có `opentelemetrycollector` tại `10.244.0.15:8889` — đây là đường RED metrics chảy từ trace vào Prometheus.

RAM của bộ giám sát (`kubectl top pods -n monitoring`), tổng khoảng 0.71 GB:

```
mon-grafana                           524Mi
prometheus-...-prometheus-0           105Mi
mon-kube-state-metrics                 42Mi
mon-kube-prometheus-stack-operator     40Mi
mon-prometheus-node-exporter            3Mi
```

Kiểm chứng truy vấn: `traces_span_metrics_calls_total` cho 6 rồi 7 service, `container_memory_working_set_bytes{namespace="default"}` cho 42 chuỗi.

**Một bài học quan trọng cho phase 3.** Lần đo đầu tiên chỉ thấy 6 service, thiếu `emailservice`. Không phải lỗi cấu hình: `emailservice` chỉ được gọi khi một đơn hàng hoàn tất, mà loadgenerator đặt đơn thưa, nên sau mỗi lần collector khởi động lại phải chờ vài phút mới có chuỗi metric đầu tiên. Jaeger vẫn liệt kê đủ 7 service suốt thời gian đó.

Hệ quả: **vắng metric không có nghĩa là service đã chết.** Prompt của XAI ở phase 3 bắt buộc phải phân biệt hai trường hợp "service không có lưu lượng" và "service ngừng phục vụ", nếu không LLM sẽ kết luận sai ngay ở những ca dễ nhất. Cách phân biệt: đối chiếu với `kube_deployment_status_replicas_available` từ kube-state-metrics, và với danh sách pod lấy qua `k8s_client.py`.

**0.7 xong ngày 2026-08-23. PHASE 0 KẾT THÚC.**

`src_thesis/k8s_client.py` chạy được trên môi trường ảo `.venv`, thư viện `kubernetes` 36.0.3. `scripts/smoke_k8s.py` tắt `cartservice` xuống 0 rồi bật lại về 1 thành công, cluster trở về nguyên trạng.

Một tác dụng phụ có ích: lúc `cartservice` tắt, spanmetrics sinh ra chuỗi `status_code="STATUS_CODE_ERROR"` cho span client của `checkoutservice` gọi `hipstershop.CartService/GetCart`. Đây là bằng chứng **đo được lỗi của service không phát trace**, qua đúng con đường đã thiết kế. Ghi lại vì phase 2 sẽ dựa vào tín hiệu này để chấm điểm F2.

Tên metric chính xác để viết PromQL ở phase 1:

```
traces_span_metrics_calls_total                     (counter)
traces_span_metrics_duration_milliseconds_bucket    (histogram)
traces_span_metrics_duration_milliseconds_sum
traces_span_metrics_duration_milliseconds_count
```

Nhãn `status_code` chỉ có hai giá trị: `STATUS_CODE_UNSET` khi bình thường và `STATUS_CODE_ERROR` khi lỗi. Không có `STATUS_CODE_OK`, nên công thức tỉ lệ lỗi phải lấy `ERROR` chia cho tổng, đừng lọc theo `OK`.

### Phase 1 — Quan sát và mô hình hóa

**Ngày 2026-08-23 — xong 2/8 việc: `prometheus_client.py` và `jaeger_client.py`.**

Đo thử trên hệ thống khỏe mạnh, `scripts/smoke_telemetry.py` cho kết quả:

```
RED phia server        RED phia client (do gian tiep)
productcatalogservice  13.7/s   productcatalogservice  13.8/s
currencyservice         7.5/s   currencyservice         7.6/s
frontend                2.8/s   cartservice             2.5/s
recommendationservice   1.8/s   adservice               1.4/s
checkoutservice         0.11/s  shippingservice         0.81/s
```

Đủ 10 service có số liệu. Ba service không phát trace là `cartservice`, `shippingservice`, `adservice` đều đo được qua span client của người gọi, đúng như thiết kế ở mục 4 KLTN.md. `redis-cart` vẫn là điểm mù duy nhất.

`jaeger_client.py` lấy 266 span từ 20 trace: 180 span client (166 có `server.address`, 14 không — toàn bộ của `recommendationservice` viết bằng Python) và 86 span server. Tỉ lệ này xác nhận phải giữ cả hai quy tắc dựng cạnh.

**Ba lỗi đã vấp, ghi lại để khỏi vấp lại.**

1. *Mốc chia histogram quá thô.* Ban đầu mốc nhỏ nhất là 5ms, trong khi hầu hết service trả lời dưới 5ms, nên mọi service đều ra `p50=2.5ms, p95=4.75ms` giống hệt nhau — con số vô dụng để so sánh trước và sau khi tiêm lỗi. Đã thêm mốc 0.5ms, 1ms, 2ms, 3ms vào `infra/tracing-local/otel-collector.yaml`. Sửa xong p50 phân hóa thành 3.3 đến 19.1ms.
2. *Nhiễu làm sai lưu lượng.* Lệnh kiểm tra sức khỏe `grpc.health.v1.Health/Check` chạy vài giây một lần và span `opentelemetry.proto...TraceService/Export` do chính SDK sinh ra khi gửi telemetry, cả hai đều bị đếm thành lưu lượng nghiệp vụ. Riêng cái thứ hai còn làm `opentelemetrycollector` hiện ra như một service của hệ thống. Đã lọc bằng hằng số `NOISE` trong `prometheus_client.py`.
3. *Cú pháp PromQL.* Viết `span_name!~".*grpc\.health\..*"` làm Prometheus trả lỗi 400 `unknown escape sequence U+002E '.'` — trong chuỗi nháy kép của PromQL, `\.` không phải chuỗi thoát hợp lệ. Cách gọn nhất là để dấu chấm trần, vì `.` khớp mọi ký tự nên vẫn đúng mục đích.

**Cảnh báo RAM cần theo dõi.** Pod `jaeger` đã lên 477Mi và còn tăng, vì Jaeger all-in-one giữ trace trong RAM với hạn mức `MEMORY_MAX_TRACES=50000`. Với ngân sách 6GB thì trước khi vào phase 4 nên hạ xuống 20000 trong `infra/jaeger-all-in-one.yaml`.

**PHASE 1 XONG ngày 2026-08-23.** Đủ 8 file: `prometheus_client.py`, `jaeger_client.py`, `naming.py`, `graph/model.py`, `runtime_graph.py`, `logical_graph.py`, `diff.py`, `serialize.py`, `snapshot.py`.

**Cổng chặn đã đạt.** Chạy `scripts/smoke_snapshot.py` trên hệ thống khỏe mạnh: dựng được 14 cạnh, khớp đúng sơ đồ thiết kế, `DEVIATIONS = none`. Không có cạnh thừa, không có cạnh thiếu, không báo nhầm.

Cách dựng 14 cạnh đó: 6 cạnh từ span server (chắc chắn nhất), 8 cạnh từ tra ClusterIP. Nghĩa là **hơn một nửa graph phụ thuộc vào quy tắc tra IP** — bỏ quy tắc này thì mất `cartservice`, `shippingservice`, `adservice` và cả vài cạnh của `checkoutservice`.

Đoạn text đưa cho LLM dài 4343 ký tự, khoảng 1085 token. Nhân với trần 3 vòng lặp mỗi ca là khoảng 3300 token đầu vào mỗi ca — con số này dùng để ước tính chi phí ở mục 7.5 KLTN.md.

**Phát hiện đáng viết vào báo cáo: Online Boutique có lỗi đứt ngữ cảnh trace.**

Ban đầu diff báo thiếu đúng một cạnh `checkoutservice -> currencyservice`. Truy ra nguyên nhân ở `src/checkoutservice/main.go` dòng 360: hàm `convertCurrency` gọi `Convert(context.TODO(), ...)` thay vì truyền `ctx` nhận được từ request. `context.TODO()` là ngữ cảnh rỗng, không mang theo mã trace, nên span đó không nối vào trace của đơn hàng mà trở thành một trace mồ côi riêng lẻ.

Hệ quả về cách lấy dữ liệu: **không được chỉ lấy trace theo đường vào từ `frontend`**. Phải gọi `recent_spans_all()` để gom từ mọi service rồi khử trùng theo cặp (trace_id, span_id). Sau khi sửa, cạnh xuất hiện với 31 lần gọi.

Đây là ví dụ thật rất hợp để đưa vào báo cáo: chính phép so lệch thiết kế với thực tế đã phát hiện ra một khiếm khuyết quan sát trong hệ thống nghiên cứu, đúng loại tín hiệu mà XAI được thiết kế để dùng.

**Hai lỗi hạ tầng đã vấp.**

1. *Jaeger bị OOMKilled 7 lần.* `MEMORY_MAX_TRACES=50000` với trần RAM 512Mi là quá tay — mỗi trace hơn 20 span. RAM leo tới 477Mi rồi pod chết, script Python đang chạy thì nhận `RemoteDisconnected`. Đã hạ xuống 10000 trong `infra/jaeger-all-in-one.yaml`; sau khi sửa Jaeger đứng ở 173Mi.
2. *Số lần khởi động lại là con số cộng dồn.* Ban đầu `describe_pods` liệt kê pod bất thường theo điều kiện `restarts > 0`, kết quả là cả 11 pod đều bị báo bất thường vì số này tích lũy qua mỗi lần tắt mở cluster. XAI đọc vào sẽ thấy đâu cũng có lỗi. Đã thêm trường `last_restart_age_s` vào `PodInfo` và chỉ báo pod vừa khởi động lại trong 10 phút gần đây — đó mới là chữ ký của lỗi F3.

**Nhiễu lỗi nền của luồng thanh toán — quyết định về phương pháp thí nghiệm.**

Cổng chặn phase 1 thoạt đầu báo đỏ với `checkoutservice -> paymentservice` lỗi 2/21 lần gọi. Không phải lỗi code. Log `paymentservice` ghi:

```
UnacceptedCreditCard [Error]: Sorry, we cannot process visa_electron credit cards.
Only VISA or MasterCard is accepted.
```

`loadgenerator` sinh số thẻ ngẫu nhiên bằng `fake.credit_card_number(card_type="visa")` ([src/loadgenerator/locustfile.py:68](../src/loadgenerator/locustfile.py#L68)). Thư viện Faker đôi khi sinh số rơi vào dải Visa Electron, mà `paymentservice` chỉ nhận VISA và MasterCard. Vậy hệ thống có tỉ lệ đơn hàng thất bại **nền** ngay cả khi hoàn toàn khỏe mạnh.

Đo được: 3.64% trên cửa sổ 10 phút, 1.27% trên 30 phút, 0.60% trên 1 giờ, và 9.5% trong một mẫu 5 phút cụ thể. Dao động lớn vì lưu lượng đặt hàng chỉ khoảng 4 đơn mỗi phút.

Một chi tiết kỹ thuật đáng nhớ: lỗi này **chỉ thấy được ở span client** của `checkoutservice`. Span server của `paymentservice` (viết bằng Node.js) không đặt trạng thái lỗi, nên đo theo phía server sẽ ra tỉ lệ lỗi gần bằng 0 và bỏ sót hoàn toàn.

*Quyết định: loại nhiễu tại nguồn.* Ghi đè `/loadgen/locustfile.py` bằng ConfigMap (`infra/loadgenerator-locustfile.yaml` gắn qua `subPath`), thay số thẻ ngẫu nhiên bằng một số VISA cố định hợp lệ `4432801561520454` — chính là số mặc định trên form thanh toán của web. Không đụng vào 11 service, không dựng lại image.

Lý do chọn cách này thay vì chấp nhận nhiễu: chỉ số 4 ở mục 8 KLTN.md là **harmful action count**, tức đếm hành động của agent làm hệ thống xấu đi. Với nền dao động từ 0 tới 9.5%, muốn khẳng định "hệ thống xấu đi" phải chạy rất nhiều lần lặp mới tách được tín hiệu khỏi nhiễu. Đưa nền về 0 thì mọi lỗi quan sát được đều do mình tiêm hoặc do agent gây ra.

**Phải ghi rõ trong báo cáo** rằng bộ sinh tải đã được sửa, kèm lý do trên. Đây là can thiệp vào thiết lập thí nghiệm, không phải vào hệ thống nghiên cứu, nhưng vẫn phải khai báo.

**Sửa kèm theo trong `diff.py`:** thêm `MIN_ERRORS = 2` và so sánh tương đối với baseline. Một lỗi lẻ trong cửa sổ 5 phút không còn đủ để báo động, vì mẫu quá nhỏ khiến một lỗi đã thành 5%.

**Cổng chặn phase 1 đạt hai lần liên tiếp** (`data/runs/20260823-112036_baseline-clean.json` và `20260823-112419_baseline-clean.json`), cách nhau vài phút, sau khi đã bỏ nhiễu số thẻ. Chạy hai lần là có chủ đích: lần đầu đạt có thể chỉ vì rơi trúng cửa sổ sạch, đúng như chuyện đã xảy ra trước đó.

Trạng thái nền sạch để đối chiếu suốt phase 2:

```
14 canh, 6 tu span server + 8 tu tra ClusterIP
0% loi tren moi canh
p95: productcatalog 0.48ms, currency 0.48ms, frontend ~92ms, checkout ~45ms
snapshot dai ~900 token
```

### Phase 2 — Tiêm lỗi

**Ngày 2026-08-23 — dựng xong bộ tiêm lỗi và kiểm chứng kịch bản S2.**

Ba file: `src_thesis/faults/injectors.py` (4 injector F1-F4), `src_thesis/faults/scenarios.yaml` (6 kịch bản), `scripts/inject.py` (công cụ dòng lệnh).

Cơ chế an toàn: trạng thái cũ ghi ra `data/runs/active_fault.json` **trước** khi phá, nên hoàn tác được cả sau khi đóng terminal hay khởi động lại máy. Đã kiểm chứng trọn vòng tiêm rồi hoàn tác, `currencyservice` trở về 1 bản chạy và snapshot sạch trở lại.

**Phát hiện 1: F2 KHÔNG tạo ra `missing_edges` như dự đoán ban đầu, mà tạo ra `error_edges`.**

Đo thật khi tắt `currencyservice`:

```
checkoutservice -> currencyservice: 58.8% loi (10/17), luc khoe manh 0.0%
frontend -> checkoutservice:        58.8% loi (10/17), luc khoe manh 0.0%  [ON CRITICAL PATH]
frontend -> currencyservice:        26.5% loi (52/196), luc khoe manh 0.0%
```

Lý do: cạnh trong runtime graph dựng từ span **phía người gọi**. Service đích chết thì người gọi vẫn tạo span, chỉ là span mang trạng thái lỗi. Cạnh vẫn tồn tại nên không bị coi là mất.

`missing_edges` thật ra là chữ ký của một loại hỏng khác: người gọi **ngừng gọi hẳn**, ví dụ chính người gọi chết, hoặc một nhánh nghiệp vụ không còn được kích hoạt. Đã sửa lại `expected_symptom` của S2 và S6 trong `scenarios.yaml`.

Chi tiết đẹp để đưa vào báo cáo: tỉ lệ lỗi của `frontend -> checkoutservice` **bằng đúng** tỉ lệ của `checkoutservice -> currencyservice` (cùng 10/17). Đường lan truyền lỗi hiện ra bằng con số, không phải suy đoán — đúng thứ `propagation_path` ở mục 7.2 cần.

**Phát hiện 2: phải chờ LÂU HƠN cửa sổ quan sát, không phải ngắn hơn.**

Chờ 180 giây rồi đo thì cửa sổ 5 phút vẫn chứa 120 giây dữ liệu lúc hệ thống còn khỏe. Hậu quả: `currencyservice` vẫn hiện `2.66 req/s, 0.0% errors` trong bảng metric dù đã tắt hẳn 3 phút — nhìn vào dễ tưởng nó còn sống. Đã nâng `wait_after_inject_s` lên 330 giây cho các kịch bản lỗi kéo dài, giữ 120 giây cho S3 vì lỗi đó chỉ kéo dài 30 giây rồi tự khỏi.

**Hệ quả cho kế hoạch phase 6:** 3 chế độ x 5 kịch bản x 5 lần x khoảng 6 phút mỗi ca là **khoảng 7 tiếng rưỡi chạy liên tục**. Phải tính vào lịch, không để sát hạn nộp.

**Lỗi lặt vặt đã sửa:** console Windows dùng bảng mã cp1252 nên `print` tiếng Việt làm script chết với `UnicodeEncodeError`. Đã thêm `sys.stdout.reconfigure(encoding="utf-8")` vào đầu mọi script trong `scripts/`.

**Kịch bản S3 lần chạy đầu — THẤT BẠI, không tạo ra một triệu chứng nào.**

Cả hai snapshot `20260823-150504_S3-truoc.json` và `20260823-150741_S3-sau.json` đều có phần diff rỗng hoàn toàn. Cạnh `frontend -> checkoutservice` cho 0 lỗi trên 18 lần gọi.

Hai nguyên nhân độc lập, cả hai đều là lỗi thiết kế chứ không phải của hệ thống:

*Nguyên nhân 1 — xóa pod KHÔNG tạo ra "khởi động lại".* Nó tạo ra một **pod mới hoàn toàn**: tên đổi từ `checkoutservice-777dff667-z29h8` sang `checkoutservice-777dff667-rtpn4`, `restarts: 0`, `last_restart_age_s: None`. Trường `last_restart_age_s` đọc từ `lastState.terminated`, mà pod mới sinh thì không có `lastState`. Nghĩa là cách phát hiện dựng ở phase 1 **không bao giờ nhìn thấy được F3**.

Sửa: thêm trường `age_s` (tuổi pod, đọc từ `creationTimestamp`) vào `PodInfo`, và `describe_pods` báo `pod was RECREATED ... ago` cho pod trẻ hơn 10 phút. Tuổi pod mới là chữ ký đúng của F3.

*Nguyên nhân 2 — xóa pod mặc định là xóa NHẸ NHÀNG.* Kubernetes cho 30 giây ân hạn để service đóng kết nối gọn gàng. Mục 6 KLTN.md ghi F3 là "pod chết đột ngột", nên phải truyền `grace_period_seconds=0`. Đã sửa trong `k8s_client.delete_pod`.

*Một điều không sửa được và phải chấp nhận:* `checkoutservice` chỉ được gọi khoảng 4 lần mỗi phút, nên khoảng trống 30 giây rất dễ rơi vào lúc không có đơn hàng nào. Tỉ lệ lỗi bằng 0 là chuyện bình thường với kịch bản này, không phải dấu hiệu injector hỏng. Tín hiệu đáng tin duy nhất của S3 là tuổi pod.

**Bài học chung, đáng viết vào báo cáo:** một lỗi có thể hoàn toàn vô hình với hệ thống quan sát nếu chọn sai đại lượng để đo. Ở đây đo số lần khởi động lại thay vì tuổi pod là đủ để bỏ sót trọn vẹn một loại sự cố. Đây chính là lý do phase 2 phải chạy tay từng kịch bản và đối chiếu với triệu chứng mong đợi trước khi tin vào bất cứ số liệu nào của phase 6.

**S3 chạy lại sau khi sửa — ĐẠT.** `20260823-152522_S3-sau.json`.

```
POD HEALTH:
  checkoutservice-777dff667-m4v87: pod was RECREATED 156s ago (previous pod is gone)
DEVIATIONS: 1 slow_edge, 0 error_edge
frontend -> checkoutservice: 0/15 loi
```

Tuổi pod bắt được sự cố, đúng như dự đoán sau khi sửa. Tỉ lệ lỗi vẫn bằng 0 — khẳng định lại rằng với `checkoutservice` chỉ 4 lần gọi mỗi phút thì khoảng trống 30 giây thường không trúng đơn nào. **Tín hiệu duy nhất đáng tin của S3 là tuổi pod.**

**Jaeger OOMKilled lần thứ ba, phải hạ tới 3000 trace.** Chuỗi hạ dần: 50000 → 10000 → 3000. Tính ngược từ lần chết thứ hai thì mỗi trace tốn khoảng 50KB, nên 10000 trace vẫn vượt trần 512Mi. 3000 trace chứa được 17 phút lưu lượng, thừa cho cửa sổ đo 5 phút.

Kèm theo, `JaegerClient` giờ thử lại 3 lần cách nhau 5 giây khi mất kết nối. Pod tự sống lại sau vài giây nên thử lại là qua được. Bắt buộc phải có trước phase 6: lượt chạy 7 tiếng không được phép chết vì một cú chớp.

**Một điểm nhiễu cần biết:** `POD HEALTH` cũng báo pod `jaeger` vừa được tạo lại, vì vừa khởi động lại nó. Các pod hạ tầng (`jaeger`, `opentelemetrycollector`) không thuộc hệ thống nghiên cứu, nhưng vẫn lọt vào đoạn text đưa cho LLM. Nếu ở phase 3 thấy XAI đổ lỗi cho hạ tầng thì đây là chỗ phải lọc.

**S1 (F1, độ trễ 6s vào productcatalogservice) — ĐẠT, khớp hoàn toàn triệu chứng mong đợi.**

```
SLOW calls:
  checkoutservice -> productcatalogservice: 6002.58ms, nen 0.83ms  (gap 7232 lan) [CRITICAL]
  frontend -> productcatalogservice:        6001.19ms, nen 1.24ms  (gap 4840 lan) [CRITICAL]
  frontend -> checkoutservice:              6020.67ms, nen 84.62ms (gap 71 lan)   [CRITICAL]
  frontend -> recommendationservice:        6005.64ms, nen 5.16ms  (gap 1164 lan)
  recommendationservice -> productcatalogservice: 6002.4ms, nen 2.08ms (gap 2886 lan)
p95 frontend: 30000ms (cham tran do)
```

Con số "chậm gấp bao nhiêu lần" chỉ có được nhờ truyền ảnh nền vào làm baseline. Không có baseline thì chỉ biết 6002ms là vượt ngưỡng 500ms, mất hẳn thông tin service này vốn trả lời trong 0.83ms.

**Hiệu ứng phụ quan trọng: lỗi độ trễ làm sinh ra `missing_edges` giả.**

Lưu lượng sụp từ 13.7 xuống 1.47 request mỗi giây. Diff báo thêm `MISSING calls: checkoutservice -> currencyservice`. Cạnh đó không mất thật — chỉ là hệ thống chậm tới mức gần như không đơn hàng nào hoàn tất trong cửa sổ 5 phút, nên cạnh không xuất hiện.

Hệ quả cho phase 3: prompt phải nói rõ cho LLM rằng **khi thông lượng sụp thì cạnh vắng mặt không đồng nghĩa với cạnh hỏng**. Nếu không, XAI sẽ báo hai nguyên nhân gốc cho một lỗi duy nhất, làm hỏng chỉ số root cause accuracy.

**Lỗi nghiêm trọng đã phát hiện và sửa: `unset_env` không hoàn tác được.**

Hoàn tác S1 thất bại với lỗi 422:

```
Deployment.apps "productcatalogservice" is invalid:
spec.template.spec.containers[0].image: Required value
```

Nguyên nhân: `unset_env` dùng `application/merge-patch+json`, mà kiểu vá đó **thay nguyên mảng** `containers` bằng đúng thứ mình gửi lên. Mảng gửi lên chỉ có `name` và `env`, nên container mất trường `image` và Kubernetes từ chối.

Hậu quả nguy hiểm hơn nhiều so với một lỗi cú pháp thông thường: **lỗi vẫn nằm nguyên trên hệ thống trong khi mình tưởng đã hoàn tác xong.** Nếu không đọc kỹ dòng lỗi mà cứ chạy tiếp kịch bản sau thì mọi số liệu từ đó về sau đều sai.

Sửa: dùng JSON Patch (RFC 6902) với thao tác `replace` nhắm đúng đường dẫn `/spec/template/spec/containers/{idx}/env`. JSON Patch chỉ đụng đúng chỗ được chỉ định, phần còn lại giữ nguyên. Đã kiểm chứng: sau khi hoàn tác, `EXTRA_LATENCY` biến mất và bốn biến môi trường còn lại vẫn nguyên vẹn.

Bài học: **hàm hoàn tác phải được kiểm chứng riêng, không được tin là nó chạy đúng chỉ vì hàm tiêm lỗi chạy đúng.** Mục 5 KLTN.md yêu cầu mọi hành động có hàm nghịch đảo, nhưng viết ra chưa đủ — phải chạy thử từng cái.

**S5 (F4, nghẹt CPU 10m vào productcatalogservice) — ĐẠT, và cho ra dấu hiệu phân biệt quan trọng nhất của phase 2.**

So sánh trực tiếp hai kịch bản cùng nhắm một service:

```
                canh cham (phia goi)  thong luong        p95 phia server
S1 do tre 6s    ~6002ms               sup 13.7 -> 1.47/s  9750ms
S5 nghen CPU    ~90-102ms             giu nguyen 13.56/s  0.48ms
```

**Điểm phân biệt nằm ở p95 phía server.** Ở S5, `productcatalogservice` báo `p95 0.48ms`, tức xử lý vẫn nhanh như lúc khỏe mạnh, trong khi cạnh nhìn từ người gọi là 90ms. Chênh lệch đó là thời gian request **nằm chờ trong hàng đợi** trước khi được cấp CPU — span phía server không đo được vì nó chỉ tính từ lúc bắt đầu xử lý.

Ở S1 thì cả hai phía đều chậm, vì service thật sự ngủ 6 giây ngay trong lúc xử lý.

Đây là dấu hiệu để XAI phân biệt "service chậm do chính nó" với "service chậm do thiếu tài nguyên". Prompt ở phase 3 **phải** đưa cả hai con số và giải thích ý nghĩa chênh lệch, nếu không thì hai kịch bản này không thể phân biệt được và root cause accuracy sẽ mất một nửa số ca.

**Hai thiếu sót của snapshot lộ ra ở kịch bản này, phải sửa trong phase 3.**

1. *Bằng chứng nghẹt CPU không có trong prompt.* `describe_resources` sắp xếp theo RAM và chỉ in 8 pod nhiều nhất, nên `productcatalogservice` không lọt vào. Đoạn text đưa cho LLM hoàn toàn không có thông tin CPU của service đang bị nghi ngờ, cũng không có trần CPU để so. Phải bổ sung: với mỗi service bị đánh dấu chậm, in kèm CPU đang dùng và trần CPU.
2. *"Pod vừa được tạo lại" KHÔNG phải chữ ký riêng của F3.* S5 cũng làm pod được tạo lại (`pod was RECREATED 367s ago`), vì đổi trần CPU buộc Kubernetes thay pod. S1 cũng vậy khi đổi biến môi trường. Nghĩa là tuổi pod chỉ nói "có gì đó vừa thay đổi", không nói được thay đổi gì. XAI phải kết hợp nó với các dấu hiệu khác chứ không được kết luận F3 chỉ từ tuổi pod.

**Lỗi thứ hai của F4 đã sửa: không tiêm được vì ràng buộc CPU.**

Lần chạy đầu hỏng ngay ở bước tiêm:

```
spec.template.spec.containers[0].resources.requests:
Invalid value: "100m": must be less than or equal to cpu limit of 10m
```

Kubernetes bắt buộc lượng CPU xin trước phải nhỏ hơn hoặc bằng trần. Hạ trần xuống 10m mà để nguyên `requests: 100m` thì bị từ chối. Sửa: `set_cpu_limit` hạ cả hai trong **cùng một lần vá** (vá riêng lẻ cũng vi phạm ở bước trung gian), và thêm hàm `restore_cpu` trả cả hai về giá trị cũ. Đã kiểm chứng sau khi hoàn tác: `limits cpu 200m`, `requests cpu 100m`, phần memory không bị đụng tới.

**S4 (F4, nghẹt CPU vào frontend) — ĐẠT, cho ra dấu hiệu hình học ngược với S1 và S5.**

```
FAILING calls:
  frontend -> adservice: 48.8% loi (21/43)
SLOW calls: TAT CA 6 canh xuat phat tu frontend
  adservice 213ms | cartservice 183ms | currencyservice 245ms
  productcatalogservice 157ms | recommendationservice 255ms | shippingservice 158ms
p95 frontend: 4617ms
p95 phia server cua cac dich: productcatalog 0.48ms, currency 0.48ms, recommendation 5.67ms
```

**Quy tắc hình học rút ra, dùng được cho XAI:**

- Cạnh chậm **tụ về** một đỉnh (S1, S5: mọi cạnh đi tới `productcatalogservice`) → đỉnh đích là nguyên nhân.
- Cạnh chậm **tỏa ra** từ một đỉnh (S4: mọi cạnh đi ra từ `frontend`) → chính đỉnh nguồn là nguyên nhân.

Dấu hiệu phụ trợ giống S5: p95 phía server của các service đích vẫn nhanh, chứng tỏ chúng không có lỗi gì.

`frontend -> adservice` có thêm 48.8% lỗi vì frontend đặt hạn chờ ngắn cho quảng cáo, nghẹt CPU làm nó vượt hạn.

**Lỗi thứ ba đã phát hiện và sửa: kịch bản kép chỉ hoàn tác được một nửa.**

Phát hiện khi đọc lại code trước khi chạy S6, chưa kịp gây hậu quả. `ActiveFault.save()` ghi đè một object duy nhất vào `active_fault.json`. Kịch bản kép S6 tiêm hai lỗi liên tiếp, nên lỗi thứ hai **xóa mất dấu vết của lỗi thứ nhất**, và `--revert` chỉ gỡ được lỗi thứ hai. Lỗi F1 sẽ nằm im trên hệ thống trong khi script báo đã hoàn tác xong.

Sửa: `active_fault.json` giờ chứa một **danh sách**, `--revert` gỡ theo thứ tự ngược lại với lúc tiêm, và nếu một mục gỡ thất bại thì nó vẫn nằm lại trong file để thử lại. `--status` liệt kê tất cả.

Đây là lỗi thứ ba liên tiếp nằm ở phần hoàn tác, sau `unset_env` và `set_cpu_limit`. Ba lần đều chỉ lộ ra khi chạy thật.

**S6 (kép: F1 độ trễ + F2 tắt service) — ĐẠT, và hoàn tác đúng hai lỗi theo thứ tự ngược.**

```
DANG CO 2 LOI CHUA HOAN TAC:
  F1-productcatalogservice-latency
  F2-currencyservice-crash
-> go F2 truoc, roi F1. Da hoan tac xong tat ca.
```

Cả hai nguyên nhân đều hiện ra rõ ràng và không lẫn vào nhau:

```
FAILING calls (dau hieu cua F2):
  frontend -> currencyservice:        100% loi (39/39)
  checkoutservice -> currencyservice: 100% loi (7/7)
  frontend -> checkoutservice:        100% loi (8/8)  [CRITICAL]
SLOW calls (dau hieu cua F1):
  checkoutservice -> productcatalogservice: 6002ms, nen 0.8ms   (gap 7503 lan) [CRITICAL]
  frontend -> productcatalogservice:        6001ms, nen 14.38ms (gap 417 lan)  [CRITICAL]
  frontend -> checkoutservice:              6005ms, nen 85.25ms (gap 70 lan)   [CRITICAL]
```

**Nhưng lộ ra vấn đề nghiêm trọng nhất của cả phase 2: 7 cạnh bị báo mất một cách sai lệch.**

```
MISSING calls:
  checkoutservice -> emailservice, -> paymentservice [CRITICAL], -> shippingservice
  frontend -> adservice, -> recommendationservice, -> shippingservice
  recommendationservice -> productcatalogservice
```

Không cạnh nào trong số đó hỏng. Chúng vắng mặt vì thông lượng sụp: hệ thống chậm tới mức rất ít request hoàn tất trong cửa sổ 5 phút. Đưa nguyên xi cho LLM thì nó sẽ báo **bảy nguyên nhân gốc cho hai lỗi**, phá hỏng chỉ số root cause accuracy ở mục 8.

Hiện tượng này đã manh nha ở S1 với một cạnh, tới S6 thì thành bảy. Kịch bản càng nặng, báo động giả càng nhiều.

*Cách xử lý đã cài đặt:* `diff.py` tính thêm `throughput_ratio` — tổng số lần gọi hiện tại chia cho lúc khỏe mạnh. Dưới 0.5 thì mọi `missing_edges` được gắn nhãn KÉM TIN CẬY kèm con số phần trăm cụ thể, và đoạn text cho LLM có thêm một dòng cảnh báo ở đầu mục.

Cố ý **không bỏ hẳn** các cạnh này: bỏ hẳn thì mất luôn trường hợp service chết thật trong lúc hệ thống đang chậm. Để LLM tự cân nhắc với thông tin đầy đủ thì đúng tinh thần XAI hơn.

---

## PHASE 2 KẾT THÚC — tổng kết

Cả 6 kịch bản đều tạo ra dấu hiệu quan sát được và khớp với triệu chứng đã ghi trong `scenarios.yaml`.

| Kịch bản                   | Dấu hiệu nhận dạng đặc trưng                                                              |
| ---------------------------- | ------------------------------------------------------------------------------------------------ |
| S1 độ trễ 6s              | cạnh chậm**tụ về** productcatalog, p95 phía server cũng chậm, thông lượng sụp   |
| S2 tắt service              | cạnh**lỗi**, không phải cạnh mất; tỉ lệ lỗi lan truyền bằng nhau qua các tầng |
| S3 xóa pod                  | **chỉ có** tuổi pod; tỉ lệ lỗi thường bằng 0 vì lưu lượng checkout quá thưa |
| S4 nghẹt CPU frontend       | cạnh chậm**tỏa ra** từ frontend, các service đích vẫn nhanh                        |
| S5 nghẹt CPU productcatalog | cạnh chậm tụ về, nhưng**p95 phía server vẫn nhanh** — khác hẳn S1                |
| S6 kép                      | hai nhóm dấu hiệu tách bạch, kèm 7 cạnh mất giả                                         |

**Bốn lỗi đã phát hiện và sửa, ba trong số đó nằm ở phần hoàn tác:**

1. `unset_env` dùng merge patch làm mất trường `image` → lỗi 422, và lỗi vẫn nằm nguyên trên hệ thống trong khi script tưởng đã gỡ xong. Sửa bằng JSON Patch.
2. `set_cpu_limit` không hạ `requests` cùng lúc → Kubernetes từ chối vì `requests` phải nhỏ hơn hoặc bằng `limits`.
3. `active_fault.json` ghi đè một mục → kịch bản kép chỉ hoàn tác được một nửa. Sửa thành danh sách, gỡ theo thứ tự ngược.
4. F3 dò sai đại lượng: xóa pod tạo ra **pod mới** chứ không phải khởi động lại. Sửa bằng cách đo tuổi pod.

Bài học chung để viết vào báo cáo: **hàm hoàn tác phải được kiểm chứng riêng bằng cách chạy thật.** Ba lỗi loại này không phát hiện được bằng đọc code, và cả ba đều có chung một kiểu nguy hiểm — hệ thống vẫn hỏng trong khi công cụ báo đã sạch.

**Việc phải làm ở phase 3, rút ra từ phase 2:**

- Prompt phải có p95 **phía server** bên cạnh độ trễ **phía người gọi**, vì chênh lệch giữa hai con số là cách duy nhất phân biệt S1 với S5.
- Prompt phải có CPU đang dùng và trần CPU của các service bị đánh dấu chậm. Hiện `describe_resources` sắp theo RAM nên service đang nghẹt CPU không lọt vào danh sách.
- Prompt phải nói rõ: thông lượng sụp thì cạnh vắng mặt không đồng nghĩa cạnh hỏng, và tuổi pod chỉ nói "vừa có thay đổi" chứ không nói thay đổi gì.
- Cân nhắc lọc pod hạ tầng (`jaeger`, `opentelemetrycollector`) khỏi phần POD HEALTH để LLM không đổ lỗi nhầm.

### Phase 3 — XAI

### Phase 4 — Digital Twin

### Phase 5 — ReAct loop

### Phase 6 — Thí nghiệm

## Hạn chế đã biết (đưa vào báo cáo)

- Ba service không phát span server: `cartservice`, `shippingservice`, `adservice`. `redis-cart` hoàn toàn không nhìn thấy. Cạnh tới `cartservice` và `shippingservice` suy ra từ span client của `frontend` và `checkoutservice`.
- Online Boutique kiến trúc phẳng, lỗi ít lan nhiều tầng.
- Twin và production không chạy song song, nên MTTR của chế độ twin-verified có cộng thêm thời gian dựng twin.

## Số liệu cuối
