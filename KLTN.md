# KLTN.md — Khóa luận: XAI + ReAct Agent + Digital Twin cho Microservices

> File này là bản giao việc (brief) cho AI coding agent. Đọc hết trước khi viết dòng code đầu tiên.
> Khi có xung đột giữa file này và ý tưởng "hay hơn" của agent: **file này thắng**, hoặc hỏi lại người dùng.

---

## 0. TÓM TẮT ĐỀ TÀI TRONG MỘT ĐOẠN

Xây một hệ thống tự chẩn đoán sự cố cho kiến trúc microservices, trong đó:

1. Telemetry (metric + trace) của hệ thống được biến thành **graph** và văn bản mô tả.
2. Một **LLM đóng vai XAI** đọc dữ liệu đó, suy luận từng bước (chain-of-thought), rồi xuất ra **JSON đặc tả** gồm: nguyên nhân gốc, đường lan truyền lỗi, độ tự tin, hành động đề xuất.
3. Một **ReAct agent** đọc JSON đó, chọn hành động sửa lỗi — nhưng **thi hành thử trên Digital Twin trước**, đo kết quả, chỉ khi twin xác nhận tốt mới áp lên hệ thống chính.

**Điểm mới (contribution) cần bảo vệ trước hội đồng:**
Đề tài gốc có 2 hướng riêng lẻ — (A) ReAct agent tự sửa hệ thống, (B) digital twin để phân tích hậu quả. Đề tài này **ghép hai hướng**: twin trở thành "sân tập" bắt buộc để agent thử hành động trước khi ra production. Giả thuyết cần chứng minh bằng số: **agent-có-twin gây ít hành động sai/gây hại hơn agent-sửa-trực-tiếp, với chi phí là thời gian phục hồi lâu hơn.**

Đây là trade-off phải đo được, không phải khẳng định suông.

---

## 1. NGƯỜI DÙNG VÀ CÁCH LÀM VIỆC

- Sinh viên làm khóa luận, **mạnh về software + AI, yếu về DevOps/Kubernetes**.
- Làm **một mình toàn bộ project** (chiến thuật solo — không được giả định có người khác lo phần hạ tầng).
- Vì vậy: mọi phần liên quan hạ tầng phải được **giải thích bằng ngôn ngữ đời thường**, kèm lệnh chạy cụ thể, kèm cách kiểm tra "làm đúng chưa".
- Khi hướng dẫn phần k8s/DevOps: **luôn nói rõ chạy lệnh ở đâu (PowerShell hay Ubuntu), và dấu hiệu nào là thành công.**

### Quy ước trả lời trong repo này
- Tiếng Việt, ngắn gọn, dùng từ đời thường.
- Thuật ngữ chuyên ngành: giải thích ngay bằng một câu ngắn.
- Không mở bài dài. Đi thẳng vào việc cần làm, theo từng bước.

---

## 2. MÔI TRƯỜNG PHÁT TRIỂN (RÀNG BUỘC CỨNG)

| Thành phần | Cấu hình |
|---|---|
| OS | Windows |
| RAM | 15.3 GB — **đây là nút thắt lớn nhất của project** |
| CPU | Ryzen 7 |
| GPU | RTX 4050 (6GB VRAM) — **không dùng cho LLM** |
| Cluster | `kind` (Kubernetes chạy trong Docker) |
| Nơi code | **Trực tiếp trên Windows**, VSCode như bình thường |
| WSL2 | Cài để Docker Desktop chạy được, nhưng **không sống trong đó** |

### Ngân sách RAM

Dự trù ban đầu (ước lượng, trước khi đo):
```
WSL (giới hạn qua .wslconfig)    10.0 GB
  ├─ kind control plane          ~1.0 GB
  ├─ Online Boutique (chính)     ~2.5 GB
  ├─ kube-prometheus-stack       ~2.0 GB
  ├─ Jaeger + OTel Collector     ~0.7 GB
  └─ còn lại cho twin            ~3.8 GB
```

**Số đo thật sau bước 0.6** — thấp hơn dự trù rất nhiều, chi tiết ở `docs/thesis-notes.md`:
```
Online Boutique 14 pod (gồm Jaeger + Collector)   ~0.35 GB
kube-prometheus-stack 5 pod                       ~0.71 GB
```
Đây là RAM *đang dùng*, chưa tính phần JVM và .NET giữ sẵn trong heap. Phần còn lại của WSL là kubelet, etcd, apiserver và bộ nhớ đệm đĩa.

File `C:\Users\<user>\.wslconfig` hiện tại:
```ini
[wsl2]
memory=6GB
processors=8
swap=4GB
autoMemoryReclaim=gradual
```
Sau khi sửa file này **bắt buộc** chạy `wsl --shutdown`, nếu không giới hạn mới không có tác dụng.

Hạ từ 10GB xuống 6GB vẫn đủ theo số đo thật, nhưng biên an toàn hẹp hơn. Chỗ dễ vỡ là phase 4, lúc namespace `twin` chạy thêm 9 pod. Dấu hiệu vượt ngưỡng là pod bị `OOMKilled`. `autoMemoryReclaim=gradual` giúp WSL trả dần RAM không dùng về lại cho Windows.

### CHIẾN LƯỢC CHẠY: KHÔNG SONG SONG
Đã quyết định: **không chạy production và twin cùng lúc.** Vòng thí nghiệm là:
1. Chụp trạng thái hệ thống chính (snapshot).
2. Dựng twin ở namespace riêng.
3. Thử hành động trên twin, đo.
4. Xóa twin (`kubectl delete namespace twin`).
5. Áp hành động lên hệ thống chính.

Chậm hơn nhưng **chắc chắn chạy được với 15.3GB RAM**. Đừng tự ý đổi sang song song.

---

## 3. NHỮNG THỨ TUYỆT ĐỐI KHÔNG LÀM

Đây là các quyết định đã cân nhắc và loại bỏ. Agent **không được đề xuất lại** trừ khi người dùng chủ động hỏi.

| Không làm | Lý do |
|---|---|
| **Huấn luyện GNN** | Cần vài nghìn ca lỗi có nhãn. Chaos cả kỳ chỉ ra được vài trăm ca → model tệ → phải bào chữa trong báo cáo. Graph chỉ dùng để **mô tả bằng text rồi nhồi cho LLM đọc**. |
| **Chạy LLM nội bộ trên GPU 4050** | 6GB VRAM chỉ vừa model 7–8B đã lượng tử hóa. Loại đó suy luận nhiều bước và xuất JSON đúng schema rất kém → làm hỏng đúng phần cốt lõi. **Dùng API.** Quyết định cụ thể ở phase 3: hai tầng — Groq gói miễn phí (`openai/gpt-oss-120b`, model mở 120 tỉ tham số) cho chạy loạt, OpenAI cho demo và bảng so sánh cuối. Model 120B không rơi vào cái bẫy 7–8B nói trên, và chạy cả hai tầng cho luôn một bảng so sánh model rẻ với model mạnh. |
| **Tự viết hệ thống microservices** | Đốt 4–6 tuần vào phần không được tính điểm. Tệ hơn: lỗi do chính mình thiết kế → hội đồng phản biện "tự ra đề tự giải". |
| **train-ticket / robot-shop** | Đã loại. train-ticket: 40+ service, quá nặng RAM, tracing không đầy đủ. robot-shop: tốt hơn nhưng phải tự cắm OpenTelemetry cho nhiều ngôn ngữ. |
| **Chaos Mesh** | Quá nặng cho nhu cầu. Dùng 4 cách tiêm lỗi thủ công ở mục 6. |
| **Script bash cho fault injection / actions** | Agent buộc phải gọi được các hành động bằng code → **viết Python ngay từ đầu**, đừng viết bash rồi bọc lại. |
| **Mount thư mục Windows vào container** | Chậm + lỗi line-ending. Project này không cần. |
| **Twin "dự đoán" hậu quả bằng mô hình toán** | Xây simulation model cho microservices là đề tài tiến sĩ. Twin ở đây = **bản sao chạy thật**, muốn biết hậu quả thì **chạy thử rồi đo**. |
| **Học sâu Kubernetes** | Chỉ cần 4 lệnh: `get pods`, `logs`, `describe pod`, `port-forward`. |

---

## 4. HỆ THỐNG MẪU: GOOGLE ONLINE BOUTIQUE

Repo: `GoogleCloudPlatform/microservices-demo` (11 service, đa ngôn ngữ, **đã cắm sẵn OpenTelemetry**).

Lý do chọn: tracing có sẵn → gỡ được nút thắt DevOps lớn nhất. Đánh đổi: kiến trúc phẳng hơn train-ticket, lỗi ít lan tầng sâu → phải bù bằng thiết kế kịch bản lỗi thông minh (mục 6).

### Các service và quan hệ
```
frontend ──┬── productcatalogservice
           ├── cartservice ──── redis-cart
           ├── recommendationservice ── productcatalogservice
           ├── currencyservice
           ├── adservice
           ├── shippingservice
           └── checkoutservice ──┬── cartservice
                                 ├── productcatalogservice
                                 ├── currencyservice
                                 ├── shippingservice
                                 ├── paymentservice
                                 └── emailservice
loadgenerator ── frontend   (bơm traffic tự động, có sẵn)
```

### Luồng nghiệp vụ chính để tập trung nghiên cứu
`xem hàng → thêm giỏ → thanh toán` = frontend → productcatalogservice → cartservice → checkoutservice → paymentservice

### Độ phủ tracing thực tế (đã kiểm tra trong code, không phải suy đoán)
Không phải cả 11 service đều phát trace.

- **Có span server (7):** `frontend`, `productcatalogservice`, `currencyservice`, `recommendationservice`, `checkoutservice`, `paymentservice`, `emailservice`. Đây là 7 service đọc biến `ENABLE_TRACING` và `COLLECTOR_SERVICE_ADDR`.
- **Không có OpenTelemetry (3):** `cartservice` (C#, trong code không hề import OTel), `shippingservice` (Go, nhưng không import OTel và không đọc `ENABLE_TRACING`), `adservice` (Java, hàm `initTracing()` chỉ in `Tracing enabled but temporarily unavailable` rồi thoát).
- **Không nhìn thấy (1):** `redis-cart`.

Cứu được phần lớn: `frontend` và `checkoutservice` đều bọc kết nối gRPC bằng `otelgrpc.NewClientHandler()`, nên **span phía người gọi** vẫn sinh ra. Vậy các cạnh `frontend → cartservice`, `checkoutservice → cartservice`, `checkoutservice → shippingservice` dựng được từ span client, chỉ là không có span server của chính ba service đó.

**Tag thật của span client (đã kiểm chứng trên Jaeger, otelgrpc 0.69):**
```
rpc.method              hipstershop.CartService/GetCart
rpc.system.name         grpc
rpc.response.status_code OK
server.address          10.96.119.247        <- ClusterIP, KHÔNG phải tên service
server.port             7070
span.kind               client
```

Không có tag `rpc.service`. Đừng đi tìm nó.

Suy ra hai cách xác định service đích, dùng cả hai để đối chiếu:
1. **Tra IP:** `server.address` + `server.port` đối chiếu với bảng ClusterIP lấy từ `k8s_client.list_services()`. Chính xác nhất, nhưng ClusterIP đổi mỗi khi Service bị xóa và tạo lại, nên **phải dựng lại bảng tra mỗi lần chụp snapshot**, không được hardcode. Namespace `twin` có dải IP riêng nên càng bắt buộc.
2. **Tách tên gRPC:** lấy phần trước dấu `/` của `rpc.method` được `hipstershop.CartService`, rồi ánh xạ sang tên Deployment `cartservice`. Cần một bảng ánh xạ viết tay, nhưng không phụ thuộc IP.

Hệ quả về metric: spanmetrics tính RED theo `service_name` của span, nên `cartservice`, `shippingservice`, `adservice` sẽ **không có** dòng metric riêng. Độ trễ và lỗi của chúng chỉ quan sát gián tiếp qua span client bên người gọi.

Về tên service trong trace: các service Go không đặt tên trong code, chúng lấy từ biến `OTEL_SERVICE_NAME`. Thiếu biến này thì trace hiện tên `unknown_service`, làm hỏng toàn bộ graph. Bắt buộc đặt đủ cho cả 7 service.

Hệ quả bắt buộc nhớ:
- `runtime_graph.py` phải có **hai quy tắc dựng cạnh**: từ quan hệ cha–con của span server, và từ thuộc tính của span client khi không có span server đối ứng.
- `redis-cart` là điểm mù, ghi thẳng vào phần hạn chế của báo cáo.
- Không đặt kịch bản lỗi mà bằng chứng duy nhất nằm ở `cartservice` hay `redis-cart` — telemetry không thấy thì XAI không có cửa đoán đúng.

### Service thuộc twin (bản gọn, tiết kiệm RAM)
BỎ đúng 3 thứ: `adservice`, `recommendationservice`, `loadgenerator`.
GIỮ tất cả phần còn lại: `frontend`, `cartservice`, `redis-cart`, `productcatalogservice`, `checkoutservice`, `paymentservice`, `currencyservice`, `shippingservice`, `emailservice`.

Vì sao không cắt sâu hơn: `checkoutservice` bắt buộc phải có đủ 6 địa chỉ mới khởi động và xử lý đơn hàng được — `PRODUCT_CATALOG_SERVICE_ADDR`, `SHIPPING_SERVICE_ADDR`, `PAYMENT_SERVICE_ADDR`, `EMAIL_SERVICE_ADDR`, `CURRENCY_SERVICE_ADDR`, `CART_SERVICE_ADDR`. Cắt `currencyservice`, `shippingservice` hay `emailservice` khỏi twin thì luồng đặt hàng gãy, mà đó đúng là luồng cần đo. Ba service này đều nhẹ, giữ lại rẻ hơn nhiều so với mất luồng nghiệp vụ chính.

Cách làm: copy `release/kubernetes-manifests.yaml` → `infra/twin-manifests.yaml`, xóa 3 block `adservice`, `recommendationservice`, `loadgenerator` (mỗi service gồm 1 Deployment và 1 Service, riêng loadgenerator chỉ có Deployment).

---

## 5. KIẾN TRÚC PHẦN MỀM CẦN XÂY

Repo này là fork của `GoogleCloudPlatform/microservices-demo`, nên thư mục `src/` **đã bị chiếm** bởi mã nguồn 11 service của Google. Code Python của khóa luận nằm ở `src_thesis/` để khỏi lẫn.

Repo đã được dọn: xóa `terraform/`, `helm-chart/`, `istio-manifests/`, `.github/`, `docs/` gốc, `cloudbuild.yaml`, `skaffold.yaml`, `.deploystack/`, thư mục `kubernetes-manifests/` và `kustomize/base/` (hai bản sao trùng của cùng bộ manifest), cùng mọi component kustomize trừ `google-cloud-operations`. Đừng đề xuất dùng lại chúng. Cần lấy lại thì `git checkout <commit-trước-khi-dọn> -- <đường-dẫn>`.

```
project-root/
├── release/kubernetes-manifests.yaml    # của Google, giữ nguyên — dùng để cài production
├── kustomize/components/google-cloud-operations/   # của Google, giữ nguyên — nguồn của phần vá env tracing
├── src/                                 # của Google, mã nguồn 11 service — chỉ đọc, không sửa
│
├── infra/
│   ├── kind-cluster.yaml
│   ├── kustomization.yaml               # release manifests + component tracing-local
│   ├── tracing-local/                   # copy của google-cloud-operations, đã thay collector
│   │   ├── kustomization.yaml           # giữ nguyên phần vá env của Google
│   │   └── otel-collector.yaml          # bản tự viết: spanmetrics + xuất về Jaeger
│   ├── jaeger-all-in-one.yaml
│   ├── collector-servicemonitor.yaml    # cho Prometheus đọc cổng 8889 của collector
│   └── twin-manifests.yaml              # bản gọn của Online Boutique
│
├── src_thesis/
│   ├── k8s_client.py                    # bọc thư viện kubernetes, mọi tương tác cluster đi qua đây
│   ├── telemetry/
│   │   ├── prometheus_client.py         # query PromQL, lấy RED metrics
│   │   ├── jaeger_client.py             # lấy trace, dựng service dependency graph
│   │   └── snapshot.py                  # gom telemetry thành 1 object "trạng thái hệ thống"
│   ├── graph/
│   │   ├── logical_graph.py             # đọc YAML thiết kế (viết tay)
│   │   ├── runtime_graph.py             # dựng từ trace thực tế
│   │   ├── diff.py                      # so lệch logical vs runtime — TÍN HIỆU QUAN TRỌNG cho XAI
│   │   └── serialize.py                 # graph → text mô tả cho LLM đọc
│   ├── xai/
│   │   ├── prompt_templates.py
│   │   ├── schema.py                    # Pydantic schema cho JSON đầu ra
│   │   └── reasoner.py                  # gọi LLM, validate, retry nếu JSON sai
│   ├── agent/
│   │   ├── actions.py                   # action space, mỗi action là 1 hàm Python
│   │   ├── twin_manager.py              # dựng / nạp trạng thái / xóa twin
│   │   ├── verifier.py                  # đo twin sau khi thử action → tốt hơn hay xấu đi?
│   │   └── react_loop.py                # LangGraph: Reason → Act-on-Twin → Observe → Promote/Retry
│   ├── faults/
│   │   ├── injectors.py                 # 4 cách tiêm lỗi, viết bằng Python
│   │   └── scenarios.yaml               # định nghĩa kịch bản + ground truth
│   └── eval/
│       ├── runner.py                     # chạy hàng loạt thí nghiệm 3 chế độ
│       └── metrics.py                    # tính các chỉ số ở mục 8
│
├── data/
│   ├── logical_topology.yaml            # sơ đồ thiết kế, VIẾT TAY
│   └── runs/                            # log từng lần thí nghiệm (JSON)
│
├── docs/
│   └── thesis-notes.md
├── KLTN.md                              # file này — bản giao việc
└── KLTN-PLAN.md                         # kế hoạch chia phase, bước nhỏ, tiêu chí thành công
```

### Nguyên tắc code
- **Mọi tương tác cluster đi qua `k8s_client.py`** — không rải `kubectl` khắp nơi.
- Mọi hàm tiêm lỗi và mọi action đều là **hàm Python thuần**, gọi được từ agent, và **có hàm nghịch đảo để hoàn tác**.
- Mỗi lần thí nghiệm ghi một file JSON đầy đủ vào `data/runs/` (input telemetry, JSON của XAI, action đã chọn, kết quả twin, kết quả cuối). Không có log này thì không viết được chương kết quả.
- LLM output **luôn validate bằng Pydantic**, sai schema thì retry, không tin mù.

---

## 6. TIÊM LỖI (FAULT INJECTION)

Viết bằng Python (`kubernetes` package), không dùng bash, không dùng Chaos Mesh.

| # | Loại lỗi | Cách làm | Hoàn tác |
|---|---|---|---|
| F1 | Service chậm | `productcatalogservice` có biến env `EXTRA_LATENCY` — đặt `6s` | về `0s` |
| F2 | Service chết | `patch_namespaced_deployment_scale(replicas=0)` | về `replicas=1` |
| F3 | Pod chết đột ngột | `delete_namespaced_pod(...)` | k8s tự tạo lại |
| F4 | Nghẹt CPU | hạ `resources.limits.cpu` xuống rất thấp | về giá trị gốc |

**Bắt buộc:** mỗi injector khi chạy phải ghi ra JSON ground truth:
```json
{
  "fault_id": "F1-productcatalog-latency",
  "target_service": "productcatalogservice",
  "fault_type": "latency",
  "params": {"extra_latency": "6s"},
  "expected_propagation": ["frontend", "recommendationservice", "checkoutservice"],
  "correct_action_class": "medium",
  "injected_at": "<timestamp>"
}
```
Không có ground truth thì không chấm điểm được agent.

Bản đã cài đặt (`src_thesis/faults/injectors.py`) thêm hai thứ so với mẫu trên:

- **`correct_actions`** — danh sách hành động được coi là đúng, chứ không chỉ có mức rủi ro. Cần vì kịch bản F3 có đáp án đúng là `no_action`: Kubernetes tự tạo lại pod, agent nhảy vào sửa là thừa. Không ghi rõ điều này thì không phân biệt được "sửa đúng" với "sửa thừa" ở chỉ số 5 mục 8.
- **`expected_propagation` tính tự động** bằng cách lần ngược sơ đồ thiết kế, thay vì viết tay. Viết tay thì mỗi lần sửa `logical_topology.yaml` là đáp án lệch mà không ai biết.

**Cơ chế an toàn bắt buộc:** trạng thái cũ được ghi ra `data/runs/active_fault.json` **trước** khi thực sự phá. Script chết giữa chừng, mất điện, hay lỡ đóng terminal thì vẫn hoàn tác được bằng `python scripts/inject.py --revert`. Không có cơ chế này thì một lần treo máy là cluster kẹt ở trạng thái hỏng mà không còn nhớ giá trị cũ.

**Phạm vi:** 3–5 loại lỗi, không hơn. Có thể thêm kịch bản kết hợp (2 lỗi cùng lúc) nếu còn thời gian — đây là chỗ bù cho việc Online Boutique kiến trúc phẳng.

---

## 7. XAI VÀ REACT LOOP

### 7.1 Input cho LLM
- RED metrics (request rate, error rate, latency) từng service — lấy từ **spanmetrics** (xem bước 0.5)
- Metric hạ tầng: CPU, RAM từng pod
- Runtime dependency graph (dựng từ trace)
- Logical topology (YAML viết tay)
- **Diff giữa hai graph** — đây thường là manh mối rõ nhất
- Log gần nhất của các service nghi vấn

Vì `cartservice`, `adservice`, `redis-cart` không phát trace (mục 4), RED metrics từ spanmetrics sẽ **không có** ba service này. Bù bằng hai nguồn khác: metric CPU/RAM từ Prometheus vẫn có đủ mọi pod, và log lấy qua `k8s_client.py` cũng vậy. Prompt phải nói rõ cho LLM biết service nào thiếu dữ liệu trace, nếu không nó dễ suy diễn "không có metric nghĩa là service đã chết".

### 7.2 Output JSON schema (Pydantic)
```python
class Explanation(BaseModel):
    root_cause_service: str
    fault_type: Literal["latency", "crash", "resource_exhaustion", "dependency_failure", "unknown"]
    confidence: float                    # 0..1
    reasoning_chain: list[str]           # từng bước suy luận, hiển thị cho người
    propagation_path: list[str]          # lỗi lan qua service nào
    evidence: list[str]                  # trích dẫn metric/log cụ thể đã dùng
    proposed_actions: list[ProposedAction]

class ProposedAction(BaseModel):
    action: Literal["scale_up", "scale_down", "adjust_resources",
                    "reroute_traffic", "purge_queue",
                    "restart_pod", "rollback"]
    target: str
    params: dict
    risk_class: Literal["easy", "medium", "hard"]
    rationale: str
```

### 7.3 Action space (phân theo mức rủi ro)
- **easy** — agent được tự làm: tăng/giảm replica, điều chỉnh CPU/RAM
- **medium** — agent được tự làm: đổi hướng traffic, xóa queue
- **hard** — **chỉ được làm sau khi twin xác nhận**: restart pod, rollback

### 7.4 Vòng ReAct (LangGraph)
```
Observe telemetry
   ↓
Reason (LLM) → Explanation JSON
   ↓
Chọn action ưu tiên cao nhất
   ↓
┌─ risk = easy/medium ─→ áp thẳng production ─→ đo lại
└─ risk = hard ────────→ dựng twin ─→ thử trên twin ─→ đo
                              ├─ tốt hơn  → áp production
                              └─ không    → quay lại Reason (kèm kết quả twin làm feedback)
   ↓
Trần 3 vòng lặp. Hết trần → dừng, xuất báo cáo "không tự sửa được" + explanation vì sao.
```

### 7.5 Kiểm soát chi phí LLM
- Trần 3 vòng lặp/ca. Cache kết quả theo hash của telemetry snapshot.
- Chạy thí nghiệm hàng loạt bằng **model rẻ**; chỉ dùng model mạnh cho demo và cho bảng so sánh cuối.
- Ghi lại token dùng mỗi ca → đưa vào báo cáo phần chi phí.

---

## 8. ĐÁNH GIÁ (PHẦN QUYẾT ĐỊNH ĐIỂM KHÓA LUẬN)

So sánh **3 chế độ** trên cùng tập kịch bản lỗi:

| Chế độ | Mô tả |
|---|---|
| **Baseline** | Không agent — chỉ ghi nhận, không sửa |
| **Direct** | Agent sửa trực tiếp production (đúng đề xuất 1 của thầy) |
| **Twin-verified** | Agent thử trên twin trước (đề tài này) |

### Chỉ số phải đo
1. **Root cause accuracy** — % ca chỉ đúng service gây lỗi (so với ground truth)
2. **Propagation accuracy** — độ trùng của `propagation_path` với `expected_propagation`
3. **MTTR** — thời gian từ lúc tiêm lỗi đến lúc hệ thống hồi phục
4. **Harmful action count** — số hành động làm hệ thống xấu hơn (chỉ số này là **trái tim** của đề tài)
5. **Wasted action count** — hành động không đổi gì
6. **Số vòng lặp / token / chi phí** mỗi ca
7. **Twin fidelity** — twin dự đoán đúng kết quả production bao nhiêu % (chỉ số riêng, chứng minh twin đáng tin)

Mỗi kịch bản chạy **tối thiểu 5 lần** để có độ lệch chuẩn — LLM không ổn định, một lần chạy không có giá trị khoa học.

---

## 9. LỘ TRÌNH THỰC HIỆN

### Giai đoạn 0 — Chốt hạ tầng (LÀM NGAY, tối đa 1 tuần)
> Nếu giai đoạn này gãy thì mọi thứ sau đều gãy. Không viết code AI trước khi xong bước 0.4.

**0.1** Bật WSL2 (`wsl --install` trong PowerShell admin), cài Docker Desktop, cấp ≥8GB RAM trong Settings > Resources. Tạo `.wslconfig` như mục 2.

**0.2** `winget install Kubernetes.kind` + `winget install Kubernetes.kubectl`, rồi:
```powershell
kind create cluster --name boutique
kubectl get nodes        # thấy 1 dòng Ready = xong
```

**0.3** Cài Online Boutique:
```powershell
kubectl apply -f ./release/kubernetes-manifests.yaml
kubectl get pods         # chờ tất cả Running, ~3-5 phút
kubectl port-forward deployment/frontend 8080:8080
# mở localhost:8080, đặt thử 1 đơn hàng
```

**0.4** **BƯỚC DỄ VỠ NHẤT — làm cẩn thận:** bật tracing, trỏ về Jaeger nội bộ.

Đã đọc code thật, tình hình cụ thể như sau (khác với giả định ban đầu, đừng mất thời gian tìm lại):

- `release/kubernetes-manifests.yaml` **không có** biến `ENABLE_TRACING`. Đừng tìm ở đó.
- Phần bật tracing nằm ở `kustomize/components/google-cloud-operations/kustomization.yaml`. File này vá sẵn `ENABLE_TRACING=1` và `COLLECTOR_SERVICE_ADDR=opentelemetrycollector:4317` vào 8 deployment. **Phần vá này dùng lại được nguyên vẹn.**
- Đi kèm nó là `otel-collector.yaml`, và file này **không chạy được trên kind**: có initContainer gọi `metadata.google.internal` để lấy project id của Google Cloud (trên máy cá nhân địa chỉ đó không tồn tại → pod treo ở `Init:0/1`), và exporter là `googlecloud` tức đẩy thẳng lên GCP.

Cách làm:
1. Dựng Jaeger all-in-one bằng `kubectl apply -f infra/jaeger-all-in-one.yaml`, bật `COLLECTOR_OTLP_ENABLED=true`, mở cổng 16686 (web) và 4317 (nhận OTLP).
2. Copy `kustomize/components/google-cloud-operations` → `infra/tracing-local`.
3. Trong bản copy, viết lại `otel-collector.yaml` của mình: bỏ initContainer, bỏ exporter `googlecloud`, thay bằng exporter `otlp` trỏ tới `jaeger:4317`. **Giữ nguyên tên Service là `opentelemetrycollector` và cổng `4317`** — giữ nguyên thì không phải sửa một dòng nào trong phần vá env.
4. Viết `infra/kustomization.yaml`: `resources` trỏ `../release/kubernetes-manifests.yaml`, `components` trỏ `./tracing-local`. Rồi `kubectl apply -k infra/`.

**Tiêu chí thành công:** đặt 1 đơn hàng trên web → trong Jaeger UI, trace của `frontend` có span con sang `productcatalogservice`, `currencyservice`, `checkoutservice`, và trong `checkoutservice` có span sang `paymentservice`.

Lưu ý theo mục 4: sẽ **không** có span mang tên service `cartservice`. Thay vào đó là span client nằm trong `frontend`, mang thuộc tính `rpc.service = hipstershop.CartService`. Nhìn thấy span client đó là đạt, đừng tưởng cấu hình sai rồi đi sửa lung tung.

Repo hay đổi cấu hình giữa các phiên bản → nếu lệch tài liệu, đọc manifest thực tế là nguồn tin cậy.

**0.5** Metric mà không phải sửa code service — mẹo quan trọng nhất:
- Thêm connector **`spanmetrics`** vào `infra/tracing-local/otel-collector.yaml`. Nó tự đọc trace và sinh ra RED metrics (rate, error, duration) cho từng service.
- Nghĩa là **không cần cắm Prometheus client vào 11 service** — tiết kiệm hàng tuần công việc.
- Xuất ra dạng Prometheus scrape được.

**0.6** Metric hạ tầng bằng 1 lệnh Helm:
```powershell
helm install mon prometheus-community/kube-prometheus-stack --set alertmanager.enabled=false
```
Thêm cấu hình cho Prometheus scrape thêm endpoint của collector ở 0.5. Giữ Grafana để chụp đồ thị đưa vào báo cáo.

**0.7** Viên gạch đầu tiên của phần AI — viết `src_thesis/k8s_client.py`, test hàm tắt/bật service:
```python
from kubernetes import client, config
config.load_kube_config()
apps = client.AppsV1Api()
apps.patch_namespaced_deployment_scale(
    "cartservice", "default", {"spec": {"replicas": 0}}
)
```
Chạy được hàm này = đã có action đầu tiên cho agent.

### Giai đoạn 1 — Quan sát và mô hình hóa
- `prometheus_client.py`, `jaeger_client.py`, `snapshot.py`
- Viết tay `data/logical_topology.yaml` cho toàn bộ 11 service (khả thi vì ít service)
- `runtime_graph.py` dựng graph từ trace, `diff.py` so lệch
- `serialize.py` — biến graph thành text cho LLM đọc

### Giai đoạn 2 — Tiêm lỗi
- 4 injector + ground truth JSON
- Chạy tay từng loại, xác nhận nhìn thấy dấu hiệu trong Prometheus và Jaeger

### Giai đoạn 3 — XAI
- Prompt template, Pydantic schema, `reasoner.py` có validate + retry
- Đánh giá riêng chất lượng XAI (chỉ số 1 và 2 ở mục 8) **trước khi** làm agent

### Giai đoạn 4 — Twin
- `twin_manager.py`: dựng namespace, nạp trạng thái, xóa
- `verifier.py`: đo twin trước/sau action
- Đo **twin fidelity** — chứng minh twin đáng tin trước khi dựa vào nó

### Giai đoạn 5 — ReAct loop
- LangGraph, trần 3 vòng, phân luồng theo risk_class

### Giai đoạn 6 — Thí nghiệm và viết
- `eval/runner.py` chạy 3 chế độ × N kịch bản × 5 lần
- Bảng số liệu, đồ thị, chương kết quả

---

## 10. RỦI RO ĐÃ BIẾT VÀ ĐƯỜNG LÙI

| Rủi ro | Dấu hiệu | Đường lùi |
|---|---|---|
| Bước 0.4 (tracing) tắc quá 1 tuần | không thấy trace trong Jaeger | Hỏi người dùng ngay. Có phương án khác. |
| RAM không đủ | pod bị `OOMKilled`, máy lag nặng | Cắt thêm service khỏi twin; đóng Chrome khi thí nghiệm; đẩy production lên cloud bằng credit sinh viên, giữ twin ở máy |
| Online Boutique kiến trúc phẳng, lỗi ít lan | XAI dễ đoán trúng, kết quả không thú vị | Thêm kịch bản lỗi kết hợp (2 lỗi cùng lúc), lỗi ở service tầng sâu |
| LLM xuất JSON sai schema | Pydantic báo lỗi liên tục | Retry có feedback lỗi; few-shot example; đổi sang model có structured output |
| Chi phí API đội | hóa đơn tăng | Cache theo hash snapshot; model rẻ cho batch; giảm N |
| Twin không phản ánh đúng production | twin fidelity thấp | Báo cáo trung thực con số này — nó là **kết quả nghiên cứu**, không phải thất bại |

**Lệnh cứu hộ khi máy quá tải:**
```powershell
kubectl top pods                    # xem pod nào ngốn RAM
kubectl delete namespace twin       # giải phóng nhanh
wsl --shutdown                      # reset toàn bộ
```

---

## 11. CƠ SỞ THAM KHẢO

- ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al., 2022) — arxiv 2210.03629
- A Survey on Large Language Model based Autonomous Agents — Springer s11704-024-40231-1
- A Comprehensive Survey on Root Cause Analysis in (Micro) Services — arxiv 2408.00803
- Digital Twins in Software Engineering — A Systematic Literature Review and Vision (MDPI 2076-3417/14/3/977)
- Digital Twinning for Microservice Architectures (ResearchGate 374928072)
- LangGraph: github.com/langchain-ai/langgraph
- Online Boutique: github.com/GoogleCloudPlatform/microservices-demo

---

## 12. CHECKLIST CHO AGENT MỖI KHI BẮT ĐẦU MỘT TASK

- [ ] Task này có nằm trong mục 3 (những thứ không làm) không?
- [ ] Có tuân thủ ngân sách RAM ở mục 2 không?
- [ ] Nếu là hành động lên cluster: đã đi qua `k8s_client.py` chưa? Có hàm hoàn tác chưa?
- [ ] Nếu là fault injection: đã ghi ground truth JSON chưa?
- [ ] Nếu là thí nghiệm: đã ghi log đầy đủ vào `data/runs/` chưa?
- [ ] Nếu là phần DevOps: đã giải thích bằng từ đời thường + nêu tiêu chí thành công chưa?
- [ ] Nếu gọi LLM: đã validate schema + đặt trần retry chưa?