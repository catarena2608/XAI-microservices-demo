# KLTN-PLAN.md — Kế hoạch thực hiện theo phase

Bản dịch KLTN.md thành việc làm được. Mỗi phase có: mục tiêu, các bước nhỏ, dấu hiệu thành công, cổng chặn (không qua cổng thì không sang phase sau).

---

## 3 sự thật về repo phải biết trước

Ba chỗ này ban đầu KLTN.md ghi khác với code thật. **KLTN.md đã được sửa lại theo đúng những gì viết dưới đây**, nên hai file không còn mâu thuẫn. Phần này giữ lại vì nó giải thích *vì sao* phase 0 và phase 4 làm như vậy.

**Sự thật 1 — `release/kubernetes-manifests.yaml` không hề có `ENABLE_TRACING`.**
Tracing nằm ở chỗ khác: [kustomize/components/google-cloud-operations/kustomization.yaml](kustomize/components/google-cloud-operations/kustomization.yaml) — file này vá biến env `ENABLE_TRACING=1` và `COLLECTOR_SERVICE_ADDR=opentelemetrycollector:4317` vào 8 deployment. Kèm theo nó là [otel-collector.yaml](kustomize/components/google-cloud-operations/otel-collector.yaml), và file này **không chạy được trên kind**: nó có initContainer gọi `metadata.google.internal` để lấy project id của Google Cloud, trên máy cậu địa chỉ đó không tồn tại nên pod sẽ treo ở `Init:0/1`. Exporter của nó cũng là `googlecloud`, tức đẩy trace lên GCP.
Cách xử lý: giữ nguyên phần vá env, chỉ thay file collector bằng bản tự viết. Vì service collector của mình cũng đặt tên `opentelemetrycollector` cổng `4317` nên phần vá env dùng lại được y nguyên, không phải sửa gì.

**Sự thật 2 — chỉ 7 trong 11 service phát trace.**
Có trace: `frontend`, `productcatalogservice`, `currencyservice`, `recommendationservice`, `checkoutservice`, `paymentservice`, `emailservice`.
Không có: `cartservice` (C#, code không import OpenTelemetry), `shippingservice` (Go, cũng không import và không đọc `ENABLE_TRACING`), `adservice` (Java, hàm `initTracing()` chỉ in `Tracing enabled but temporarily unavailable` rồi thôi — [AdService.java:214](src/adservice/src/main/java/hipstershop/AdService.java#L214)).
Hệ quả: tiêu chí 0.4 ban đầu ("thấy trace đi qua frontend → cartservice → checkoutservice → paymentservice") không xảy ra đúng như vậy, vì `cartservice` không có span của chính nó.
Nhưng vẫn cứu được: `frontend` ([main.go:231](src/frontend/main.go#L231)) và `checkoutservice` ([main.go:216](src/checkoutservice/main.go#L216)) đều bọc kết nối gRPC bằng `otelgrpc.NewClientHandler()`, nên **span phía người gọi** vẫn có. Các cạnh tới `cartservice` và `shippingservice` dựng từ span client, không phải từ span server. `redis-cart` thì hoàn toàn không nhìn thấy — điểm mù, ghi vào phần hạn chế của báo cáo.
Span client **không có tag `rpc.service`** (đã kiểm chứng trên Jaeger ở bước 0.4). Nó có `rpc.method = hipstershop.CartService/GetCart` và `server.address` là **ClusterIP** chứ không phải tên service. Cách xác định đích: tra `server.address` + `server.port` vào bảng ClusterIP dựng lại mỗi lần snapshot. Chi tiết ở mục 4 KLTN.md.
Thêm một chi tiết dễ sập: các service Go không đặt tên service trong code, chúng lấy từ biến `OTEL_SERVICE_NAME`. Thiếu biến này thì trace hiện `unknown_service` và graph vô dụng.

**Sự thật 3 — danh sách service của twin ban đầu sẽ làm checkout gãy.**
`checkoutservice` bắt buộc có 6 địa chỉ: productcatalog, shipping, payment, email, currency, cart (xem env trong [release/kubernetes-manifests.yaml](release/kubernetes-manifests.yaml)). KLTN.md bảo bỏ `currencyservice`, `shippingservice`, `emailservice` khỏi twin — bỏ xong thì đặt hàng trong twin sẽ lỗi, mà luồng đặt hàng chính là thứ cần đo.
Cách xử lý: twin bỏ đúng 3 thứ là `adservice`, `recommendationservice`, `loadgenerator`. Ba cái bị bỏ trong KLTN.md thì giữ lại — chúng đều nhẹ (currency và email dưới 100MB mỗi cái).

---

## Quy ước làm việc

**Nhánh git.** Repo này là fork của Google, `main` phải để dành cho việc kéo code gốc về sau này. Code khóa luận làm trên nhánh riêng:

```powershell
git checkout -b thesis/main
```

Sau này mỗi phase một nhánh con `thesis/phase-1-observe`, làm xong merge vào `thesis/main`. Làm một mình nên không cần pull request, nhưng mỗi phase xong thì commit và gắn tag `phase-1-done` để lúc gãy còn chỗ lùi về.

**Thư mục.** Code khóa luận nằm ở `infra/`, `src_thesis/`, `data/`, `docs/`. Lưu ý: repo đã có sẵn thư mục `src/` chứa 11 service của Google — đừng đổ code Python vào đó, đặt tên khác là `src_thesis/` để khỏi lẫn.

Repo đã dọn sạch phần thừa của Google (terraform, helm-chart, istio, CI, docs gốc, các bản sao manifest trùng lặp). Còn lại đúng những thứ dùng đến: `release/kubernetes-manifests.yaml`, `kustomize/components/google-cloud-operations/`, `src/`, `protos/`.

**File không commit.** `.gitignore` đã bổ sung `.env`, `data/runs/`, `__pycache__/`; `.venv/` vốn đã có sẵn.

**Chỗ chạy lệnh.** Mặc định mọi lệnh trong file này chạy ở PowerShell trên Windows, tại thư mục `d:\KLTN\XAI-microservices-demo`. Chỗ nào phải vào Ubuntu/WSL tớ ghi rõ.

---

## Phase 0 — Hạ tầng chạy được (1 tuần, làm ngay)

Mục tiêu: một cluster kind có Online Boutique chạy, trace chảy vào Jaeger, metric RED chảy vào Prometheus, và một hàm Python bật/tắt được service.

### 0.1 — Docker + WSL2 + giới hạn RAM

1. PowerShell quyền admin: `wsl --install`, khởi động lại máy.
2. Cài Docker Desktop, vào Settings > Resources bật WSL2 backend.
3. Tạo file `C:\Users\TIEN\.wslconfig` với nội dung `memory=10GB`, `processors=6`, `swap=8GB` như mục 2 của KLTN.md.
4. `wsl --shutdown` rồi mở lại Docker Desktop.

Thành công khi: `docker run hello-world` in ra dòng chào, và Task Manager thấy `Vmmem`/`vmmemWSL` không vượt quá 10GB.

### 0.2 — kind + kubectl

1. `winget install Kubernetes.kind` và `winget install Kubernetes.kubectl`.
2. Viết `infra/kind-cluster.yaml`: một node control-plane, mở sẵn `extraPortMappings` cổng 8080 để khỏi phải port-forward suốt.
3. `kind create cluster --name boutique --config infra/kind-cluster.yaml`.

Thành công khi: `kubectl get nodes` in ra một dòng, cột STATUS là `Ready`.

### 0.3 — Cài Online Boutique bản gốc

1. `kubectl apply -f release/kubernetes-manifests.yaml`.
2. Chờ 3–5 phút, theo dõi bằng `kubectl get pods -w`.
3. `kubectl port-forward deployment/frontend 8080:8080`, mở `localhost:8080`, đặt thử một đơn hàng cho tới màn hình "Your order is complete".

Thành công khi: 12 pod đều `Running` và đơn hàng đặt xong. Nếu pod nào `Pending` vì thiếu RAM thì dừng lại xử lý ngay, đừng đi tiếp.

Ghi lại: chạy `kubectl top pods` (cần metrics-server, nếu chưa có thì cài sau ở 0.6) và lưu con số RAM nền vào `docs/thesis-notes.md`. Con số này dùng để đối chiếu ở phase 4 khi dựng twin.

### 0.4 — Tracing về Jaeger nội bộ (bước dễ vỡ nhất)

Đây là chỗ chiếm nhiều thời gian nhất phase 0. Làm theo đúng thứ tự, mỗi bước kiểm tra xong mới sang bước sau.

1. Viết `infra/jaeger-all-in-one.yaml`: Deployment `jaeger` dùng image `jaegertracing/all-in-one`, đặt env `COLLECTOR_OTLP_ENABLED=true`, kèm Service mở cổng `16686` (giao diện web) và `4317` (nhận OTLP).
2. `kubectl apply -f infra/jaeger-all-in-one.yaml`, rồi `kubectl port-forward svc/jaeger 16686:16686` và mở `localhost:16686`. Giao diện Jaeger hiện lên là được, lúc này chưa có trace nào cả.
3. Copy thư mục `kustomize/components/google-cloud-operations` thành `infra/tracing-local`. Xóa file `otel-collector.yaml` trong bản copy, viết lại `infra/tracing-local/otel-collector.yaml` của mình: bỏ initContainer, bỏ exporter `googlecloud`, thay bằng exporter `otlp` trỏ tới `jaeger:4317`. Giữ nguyên tên Service là `opentelemetrycollector` và cổng `4317` — giữ nguyên thì phần vá env trong `kustomization.yaml` dùng lại được, không phải sửa dòng nào.
4. Viết `infra/kustomization.yaml` gồm `resources` trỏ tới `../release/kubernetes-manifests.yaml` và `components` trỏ tới `./tracing-local`.
5. `kubectl apply -k infra/`. Các pod sẽ khởi động lại vì env đổi.
6. Đặt lại một đơn hàng trên `localhost:8080`, rồi vào Jaeger UI, chọn service `frontend`, bấm Find Traces.

Thành công khi: thấy trace của `frontend` có span con sang `productcatalogservice`, `currencyservice`, `checkoutservice`, và trong `checkoutservice` có span sang `paymentservice`. Nhớ điểm lệch 2 ở trên: sẽ **không** có span mang tên service `cartservice` — thay vào đó là span client nằm trong `frontend` với thuộc tính `rpc.service = hipstershop.CartService`. Nhìn thấy span client đó là đạt.

Nếu quá 1 tuần vẫn không có trace: dừng, hỏi lại, theo mục 10 của KLTN.md.

### 0.5 — spanmetrics: có RED metrics mà không sửa code service

1. Sửa `infra/tracing-local/otel-collector.yaml`: thêm mục `connectors` với `spanmetrics`, thêm exporter `prometheus` mở cổng `8889`.
2. Pipeline `traces` có exporter là `[otlp, spanmetrics]`; thêm pipeline `metrics` nhận từ `[spanmetrics]` và xuất ra `[prometheus]`.
3. Mở thêm cổng `8889` trong Service `opentelemetrycollector`.
4. `kubectl apply -k infra/`, rồi `kubectl port-forward svc/opentelemetrycollector 8889:8889` và mở `localhost:8889/metrics`.

Thành công khi: trang metrics có các dòng bắt đầu bằng `traces_span_metrics_duration` và `traces_span_metrics_calls_total`, kèm nhãn `service_name` mang tên các service của Boutique. Đây chính là ba chỉ số RED (số request, tỉ lệ lỗi, độ trễ) mà mục 7.1 cần.

### 0.6 — Metric hạ tầng

1. Thêm repo helm: `helm repo add prometheus-community https://prometheus-community.github.io/helm-charts` rồi `helm repo update`.
2. Cài bản đã cắt bớt cho nhẹ:

```powershell
helm install mon prometheus-community/kube-prometheus-stack --set alertmanager.enabled=false --set prometheus.prometheusSpec.retention=2d
```

3. Cho Prometheus đọc luôn cổng 8889 của collector: viết `infra/collector-servicemonitor.yaml` (một đối tượng `ServiceMonitor` trỏ vào Service `opentelemetrycollector`, cổng tên `prometheus`), rồi apply.
4. `kubectl port-forward svc/mon-kube-prometheus-stack-prometheus 9090:9090`, mở `localhost:9090`, chạy thử hai câu truy vấn: `traces_span_metrics_calls_total` và `container_memory_working_set_bytes`.

Thành công khi: cả hai câu đều trả về dữ liệu. Câu đầu là metric RED từ trace, câu sau là RAM từng container.

Cảnh báo RAM: đây là lúc dễ hết RAM nhất trong phase 0. Nếu máy lag nặng hoặc pod bị `OOMKilled`, tắt Grafana bằng `--set grafana.enabled=false` (đồ thị cho báo cáo có thể vẽ bằng Python ở phase 6, không nhất thiết phải có Grafana).

### 0.7 — Viên gạch Python đầu tiên

1. Tạo môi trường ảo: `python -m venv .venv` rồi `.\.venv\Scripts\Activate.ps1`.
2. `pip install kubernetes prometheus-api-client requests pydantic python-dotenv`, rồi `pip freeze > requirements.txt`.
3. Viết `src_thesis/k8s_client.py` bọc thư viện `kubernetes`, cung cấp: `list_pods`, `get_logs`, `scale_deployment`, `set_env`, `set_cpu_limit`, `delete_pod`. Mỗi hàm đổi trạng thái phải trả về giá trị cũ để hoàn tác được — đây là yêu cầu của mục 5 và checklist mục 12.
4. Viết `scripts/smoke_k8s.py` gọi thử: hạ `cartservice` xuống 0 replica, chờ, rồi đưa về 1.

Thành công khi: chạy script, `kubectl get pods` thấy pod cartservice biến mất rồi hiện lại.

**Cổng chặn phase 0:** trace vào Jaeger, spanmetrics vào Prometheus, hàm Python scale được deployment. Thiếu một trong ba thì không sang phase 1.

---

## Phase 1 — Quan sát và mô hình hóa (1,5 tuần)

Mục tiêu: từ cluster đang chạy, lấy ra được một object Python mô tả đầy đủ "hệ thống lúc này đang thế nào", và một đoạn text mô tả graph để nhồi cho LLM.

1. `src_thesis/telemetry/prometheus_client.py` — hàm `get_red_metrics(window)` trả về dict `{service: {rate, error_rate, p95_latency}}`, dựng từ `traces_span_metrics_*`. Thêm `get_resource_metrics()` lấy CPU/RAM từng pod.
2. `src_thesis/telemetry/jaeger_client.py` — gọi API `/api/traces` của Jaeger, lấy N trace gần nhất, trả về danh sách span đã chuẩn hóa.
3. `src_thesis/graph/runtime_graph.py` — từ danh sách span dựng graph có hướng. Hai quy tắc cạnh:
   - Span server: cạnh từ service cha sang service con theo quan hệ span.
   - Span client không có span server đối ứng: tra `server.address` + `server.port` vào bảng ClusterIP (lấy từ `k8s_client.list_services()`, dựng lại mỗi lần snapshot vì IP đổi khi Service tạo lại), đối chiếu chéo với phần trước dấu `/` của `rpc.method`.

   Quy tắc thứ hai là chỗ vớt lại `cartservice` và `shippingservice` (sự thật 2).
4. `data/logical_topology.yaml` — viết tay sơ đồ thiết kế 11 service theo đúng phần "Các service và quan hệ" ở mục 4 KLTN.md.
5. `src_thesis/graph/logical_graph.py` — đọc file YAML trên thành cùng kiểu dữ liệu graph với bước 3.
6. `src_thesis/graph/diff.py` — so hai graph, trả về: cạnh có trong thiết kế mà runtime không thấy (dấu hiệu service chết), cạnh runtime có mà thiết kế không có (gọi sai chỗ), cạnh có nhưng latency vọt bất thường.
7. `src_thesis/graph/serialize.py` — biến graph + diff + metric thành đoạn text tiếng Anh gọn cho LLM đọc. Giới hạn độ dài, vì text này đi vào prompt và tính tiền theo token.
8. `src_thesis/telemetry/snapshot.py` — gom tất cả ở trên thành một object `SystemSnapshot`, có hàm `to_json()` để lưu vào `data/runs/`.

Thành công khi: chạy một lệnh, in ra file JSON snapshot đầy đủ, và đoạn text mô tả graph đọc vào thấy hiểu được hệ thống đang chạy bình thường.

**Cổng chặn:** `diff.py` chạy trên hệ thống khỏe mạnh phải cho ra kết quả gần như rỗng. Nếu lúc bình thường mà diff đã báo đầy lỗi thì tín hiệu này vô dụng cho XAI, phải sửa trước khi đi tiếp.

---

## Phase 2 — Tiêm lỗi (1 tuần)

Mục tiêu: bốn cách phá hệ thống, mỗi cách có nút hoàn tác và một file ground truth.

1. `src_thesis/faults/injectors.py` — bốn hàm theo mục 6 KLTN.md: F1 đặt env `EXTRA_LATENCY=6s` cho `productcatalogservice` (biến này có thật, xem [server.go:88](src/productcatalogservice/server.go#L88)); F2 scale về 0; F3 xóa pod; F4 hạ `resources.limits.cpu`. Mọi hàm gọi qua `k8s_client.py`, mỗi hàm có hàm nghịch đảo tương ứng.
2. Mỗi injector khi chạy ghi file JSON ground truth đúng cấu trúc ở mục 6 (có `expected_propagation` và `correct_action_class`).
3. `src_thesis/faults/scenarios.yaml` — 6 kịch bản: S1 (F1 trên productcatalog), S2 (F2 trên currencyservice), S3 (F3 trên checkoutservice), S4 (F4 trên frontend), S5 (F4 trên productcatalog), S6 (kép F1+F2).
4. `scripts/inject.py` — công cụ chạy tay: `--list`, `S2 --watch`, `--revert`, `--status`.
5. Chạy tay từng kịch bản theo `recommended_order` trong file, đối chiếu kết quả với `expected_symptom`.

### Tình trạng: PHASE 2 XONG (2026-08-23)

Cả 6 kịch bản đã chạy và kiểm chứng trọn vòng: tiêm, bắt triệu chứng, hoàn tác, hệ thống về sạch. 35 file bằng chứng trong `data/runs/`. Bảng dấu hiệu nhận dạng của từng kịch bản và bốn lỗi đã sửa nằm ở `docs/thesis-notes.md`.

Hai giả định ban đầu đã bị số liệu bác bỏ, chi tiết ở `docs/thesis-notes.md`:

- **F2 không tạo ra `missing_edges`** như dự đoán, mà tạo ra `error_edges`. Cạnh dựng từ span phía người gọi, nên service đích chết thì cạnh vẫn còn, chỉ mang trạng thái lỗi. `missing_edges` là chữ ký của loại hỏng khác: người gọi ngừng gọi hẳn.
- **Phải chờ lâu hơn cửa sổ quan sát, không phải ngắn hơn.** Chờ 2 phút như kế hoạch ban đầu thì cửa sổ 5 phút vẫn chứa 3 phút dữ liệu lúc còn khỏe, số liệu bị pha loãng tới mức service đã tắt hẳn vẫn hiện `0.0% errors`. Đã nâng lên 330 giây.

Thành công khi: mỗi kịch bản đều nhìn thấy dấu hiệu rõ ràng và **khớp với `expected_symptom`** đã ghi trong file. Không khớp thì sửa lại mô tả trong file cho đúng số liệu thật, đừng sửa số liệu cho vừa mô tả.

Nếu kịch bản nào không tạo ra dấu hiệu quan sát được thì bỏ nó, thay bằng kịch bản khác. Lỗi mà telemetry không thấy thì XAI không có cửa đoán đúng.

**Cổng chặn:** sau mỗi lần hoàn tác, hệ thống phải trở về trạng thái sạch. `inject.py` tự kiểm tra điều này: nó chụp ảnh nền và chỉ tiêm khi diff sạch, chờ tối đa 6 phút, quá thì dừng và báo lỗi thật chưa sửa.

---

## Phase 3 — XAI (1,5 tuần)

Mục tiêu: đưa snapshot vào, nhận JSON giải thích đúng schema ra, và biết nó đúng bao nhiêu phần trăm.

1. `src_thesis/xai/schema.py` — chép nguyên hai class `Explanation` và `ProposedAction` ở mục 7.2 KLTN.md.
2. `src_thesis/xai/prompt_templates.py` — prompt gồm: mô tả hệ thống, dữ liệu snapshot dạng text, schema JSON, và 2 ví dụ few-shot.
3. `src_thesis/xai/reasoner.py` — gọi API LLM, ép định dạng JSON, validate bằng Pydantic. Sai schema thì retry tối đa 3 lần, mỗi lần nhồi lại thông báo lỗi Pydantic vào prompt. Cache theo hash của snapshot. Ghi lại số token mỗi lần gọi.
4. Chuẩn bị API key trong `.env`, đọc bằng `python-dotenv`. Không commit file này.
5. `src_thesis/eval/metrics.py` — hai hàm đầu tiên: `root_cause_accuracy` và `propagation_accuracy` (so `propagation_path` với `expected_propagation` bằng Jaccard).
6. Chạy đánh giá riêng phần XAI: 5 kịch bản × 5 lần = 25 ca, chỉ đo hai chỉ số trên, chưa có agent.

Thành công khi: có bảng số cho biết XAI đoán đúng nguyên nhân gốc bao nhiêu phần trăm, kèm độ lệch chuẩn.

**Cổng chặn:** root cause accuracy dưới 50% thì dừng lại sửa prompt, đừng xây agent lên trên một XAI đoán bừa. Số này cũng là số đầu tiên đưa vào báo cáo được.

---

## Phase 4 — Digital Twin (1,5 tuần)

Mục tiêu: dựng được bản sao ở namespace `twin`, đo được, xóa được, và biết nó giống production đến mức nào.

1. `infra/twin-manifests.yaml` — copy `release/kubernetes-manifests.yaml`, xóa block của `adservice`, `recommendationservice`, `loadgenerator`. **Giữ lại** `currencyservice`, `shippingservice`, `emailservice`, lý do ở sự thật 3.
2. `src_thesis/agent/twin_manager.py` — `create_twin()` tạo namespace `twin` rồi apply manifest; `load_state(snapshot)` áp lại cấu hình hiện tại của production lên twin (số replica, biến env, resource limit); `destroy_twin()` xóa namespace.
3. Bơm traffic vào twin: viết một loadgen Python nhẹ trong `src_thesis/agent/twin_manager.py` gọi API frontend của twin, thay vì bật loadgenerator gốc (tiết kiệm RAM).
4. `src_thesis/agent/verifier.py` — đo RED metrics của twin trước và sau khi thử action, trả về phán quyết `better` / `worse` / `no_change` kèm con số cụ thể.
5. Đo twin fidelity: với mỗi kịch bản lỗi, tiêm lỗi vào twin, chạy một action, ghi kết quả. Rồi làm y hệt trên production, so hai kết quả. Tỉ lệ khớp chính là twin fidelity ở chỉ số 7 mục 8.

Thành công khi: `create_twin()` → đặt được đơn hàng trong twin → `destroy_twin()` xong RAM trở về mức nền.

**Cổng chặn:** phải chạy đủ chu trình tạo–đo–xóa ít nhất 3 lần liên tiếp mà máy không hết RAM. Nhớ mục 2 KLTN.md: không bao giờ chạy twin song song với thí nghiệm production.

Nếu twin fidelity thấp: đó là kết quả nghiên cứu, báo cáo trung thực, không phải thất bại (mục 10 KLTN.md).

---

## Phase 5 — ReAct loop (1 tuần)

Mục tiêu: nối XAI và twin thành một vòng lặp tự động.

1. `pip install langgraph langchain-core`.
2. `src_thesis/agent/actions.py` — bảy action ở schema mục 7.2, mỗi cái là một hàm Python có hàm hoàn tác. Gắn `risk_class` cho từng cái theo mục 7.3.
3. `src_thesis/agent/react_loop.py` — graph LangGraph các node: Observe → Reason → SelectAction → phân nhánh theo `risk_class` → (easy/medium: áp thẳng production) hoặc (hard: dựng twin, thử, đo, tốt thì áp production, xấu thì quay lại Reason kèm kết quả twin làm feedback).
4. Trần 3 vòng. Hết trần thì dừng và xuất báo cáo "không tự sửa được" kèm explanation.
5. Ghi log đầy đủ mỗi vòng vào `data/runs/<run_id>.json`: snapshot đầu vào, JSON của XAI, action đã chọn, kết quả twin, kết quả cuối, số token.

Thành công khi: tiêm F2 vào `currencyservice`, chạy agent, agent tự scale lại về 1 replica và hệ thống hồi phục, toàn bộ được ghi vào một file JSON.

**Cổng chặn:** file log JSON phải đủ để dựng lại toàn bộ câu chuyện một ca. Thiếu log thì phase 6 không viết được chương kết quả.

---

## Phase 6 — Thí nghiệm và viết (2 tuần)

Mục tiêu: bảng số liệu so ba chế độ, đủ để bảo vệ giả thuyết ở mục 0 KLTN.md.

1. `src_thesis/eval/runner.py` — chạy vòng lặp 3 chế độ (baseline, direct, twin-verified) × 5 kịch bản × 5 lần = 75 ca. Mỗi ca: khôi phục trạng thái nền, tiêm lỗi, chạy chế độ tương ứng, đo, hoàn tác.
2. Bổ sung `src_thesis/eval/metrics.py` đủ 7 chỉ số mục 8. Quan trọng nhất là chỉ số 4 (harmful action count) — định nghĩa rõ ràng bằng số trước khi chạy: action nào làm error rate tăng hoặc p95 latency tăng quá 20% so với trước khi thực hiện thì tính là harmful.
3. Chạy thử 5 ca trước để ước lượng thời gian và tiền API, rồi mới chạy đủ 75 ca. Chạy bằng model rẻ.
4. Vẽ đồ thị bằng matplotlib từ `data/runs/`: MTTR ba chế độ, harmful action ba chế độ, twin fidelity.
5. Viết `docs/thesis-notes.md` thành chương kết quả: giả thuyết, số liệu, và phần thảo luận về trade-off giữa harmful action ít hơn và MTTR lâu hơn.

Thành công khi: có bảng số cho thấy twin-verified có harmful action thấp hơn direct, và MTTR cao hơn. Nếu số liệu **không** cho thấy như vậy thì vẫn báo cáo trung thực và giải thích vì sao — đó vẫn là kết quả khoa học.

---

## Tổng thời gian

Phase 0 một tuần, phase 1 và 3 và 4 mỗi cái một tuần rưỡi, phase 2 và 5 mỗi cái một tuần, phase 6 hai tuần. Cộng lại khoảng 9,5 tuần nếu không tắc chỗ nào. Phase 0 bước 0.4 là chỗ dễ trượt tiến độ nhất, đặt hạn cứng một tuần cho nó.
