# Đánh giá lời giải thích XAI — nhật ký việc đã làm

Ngày làm: 2026-10-07. Phạm vi: các bước A–E của kế hoạch đánh giá XAI (bước F — phần
twin — cần cluster, chưa làm ở đây).

> Các con số theo kịch bản (S1…S6) trong file này dùng để **kiểm công cụ**, không
> phải kết quả để đưa nguyên vào báo cáo khóa luận.

---

## 0. Tóm tắt

**Câu hỏi đặt ra.** Với một đồ án XAI, chẩn đoán đúng hay sai chưa đủ. Cần đo thêm ba
điều về **lời giải thích**:

| Điều cần đo | Tên chuẩn | Đo bằng |
|---|---|---|
| Mọi con số, mọi khẳng định truy ngược được về trạng thái hệ thống lúc chẩn đoán | Soundness / grounding | **E1** — `grounding.py` |
| Lập luận khớp với hành động đề xuất | Consistency | **C** — `consistency.py` |
| Bằng chứng được trích đúng là thứ đã quyết định chẩn đoán | Faithfulness | **E2** — `counterfactual.py` |

Kèm thêm **bộ chẩn đoán bằng luật** (`rule_baseline.py`) làm mốc so sánh, và **bảng
"đáng tin"**: nhóm qua kiểm có đúng nhiều hơn nhóm không qua kiểm không.

**Trạng thái từng việc:**

| # | Việc | Trạng thái | Kiểm chứng bằng gì |
|---|---|---|---|
| 1 | A — agent lưu snapshot và nguyên văn prompt mỗi vòng | Xong | Dựng lại prompt từ snapshot thật: giống hệt 3557/3557 ký tự |
| 2 | Bảng sự kiện dùng chung (`facts.py`) | Xong | Snapshot k3s thật: 247 sự kiện, 168 cái có trong prompt |
| 3 | B — E1 (`grounding.py`) | Xong | 14 câu biết trước đáp án và 4 điều kiện tiên quyết, trên snapshot thật: đúng hết. Chạy trên 1996 câu thật của phase 3 |
| 4 | C — kiểm nhất quán (`consistency.py`) | Xong | 164 lời giải thích thật. Cả 12 câu bị cờ "tự bác bỏ hành động" đều đã đọc tay, đều đúng |
| 5 | E — bộ chẩn đoán bằng luật (`rule_baseline.py`) | Xong | Đã chạy trên 8 ca lỗi thật, xem mục 13 |
| 6 | D — E2 phản thực (`counterfactual.py`) | Đã chạy bản cũ, chờ chạy bản đã sửa | Bản cũ (trước mục 13.6–13.7) đã chạy thật trên k3s: mục 13.8. Kết quả chưa sạch, chưa dùng làm số báo cáo. Bản đã sửa chưa chạy: khoảng 0,17 USD, chờ bạn đồng ý |
| 8 | Lần chạy đầu trên ca lỗi thật (phiên `20261007-065802`) | Xong | Mục 13: E1, C, luật, bản xem trước E2, cùng 5 lỗi của bộ chấm và của luật đã sửa, 2 vấn đề chất lượng dữ liệu |
| 7 | Script `scripts/xai_audit.py` cùng bộ nạp `xai_cases.py` | Xong | Chạy được trên toàn bộ dữ liệu thật đang có |

**Kết quả đầu tiên đáng chú ý.** Xem chi tiết và các giới hạn ở mục 9.
- Lời giải thích **không nhất quán** chỉ đúng nguyên nhân gốc **9/20** lần. Lời giải
  thích **nhất quán** đúng **118/134** lần.
- **Độ tin cậy LLM tự khai không tách được gì**: 152/154 lời giải thích đều tự khai ≥ 0.9.
- **16/20** lời giải thích không nhất quán vẫn được bảng điểm chấm "hành động đúng". Đây
  là bằng chứng trực tiếp rằng chỉ đo độ chính xác là không đủ.

**Chưa làm được, vì sao:**
- Máy WSL không có snapshot nào lúc hệ thống đang lỗi. `data/runs/` nằm ngoài git, nên
  snapshot "-sau" của phase 3 không theo sang máy này. Lịch sử git cũng không có.
- Vì vậy E1 ở chế độ đầy đủ, E2 và bộ luật **chưa được chạy trên ca lỗi thật**. Cách
  thu dữ liệu nằm ở mục 11.
- Chưa commit gì.

---

## 1. Định nghĩa "đáng tin" dùng trong đồ án

Không tuyên bố "XAI làm LLM đoán đúng hơn": không chứng minh được, và đó cũng không phải
việc của XAI. Tuyên bố dùng là:

> Các phép kiểm lời giải thích (E1, C, E2) cho người vận hành biết **khi nào nên tin**
> một chẩn đoán: chẩn đoán qua kiểm đúng nhiều hơn hẳn chẩn đoán không qua kiểm, và
> phân biệt tốt hơn con số `confidence` mà LLM tự khai.

Vì sao vẫn phải đo độ chính xác: một lời giải thích trôi chảy, trích số thật, cho một
chẩn đoán **sai** là thứ nguy hiểm nhất — nó thuyết phục người đọc tin vào kết luận sai.
Muốn biết phép kiểm có tách được ca đúng khỏi ca sai không thì phải biết ca nào đúng.
Nên độ chính xác là **biến bối cảnh bắt buộc**, không phải mục tiêu.

Nguồn tham khảo:
- **Zytek, Pidò, Veeramachaneni (2024)**, "LLMs for XAI: Future Directions for Explaining
  Explanations", arXiv:2405.06064, bài workshop CHI 2024 HCXAI. **Đã đọc.** Lấy định nghĩa
  soundness 0/1/2 và completeness ở Bảng 2.
- **Wu et al. (2024)**, "Usable XAI", phụ lục B: tách plausibility khỏi faithfulness. Đã
  dùng từ trước.
- **DeYoung et al. (2020)**, ERASER (ACL 2020): hai thước đo comprehensiveness và
  sufficiency cho lời giải thích dạng trích dẫn. **Chưa mở ra kiểm trong phiên này.**
- **Turpin et al. (2023)**, "Language Models Don't Always Say What They Think"
  (NeurIPS 2023). **Chưa mở ra kiểm trong phiên này.**

Hai nguồn cuối có nhắc trong chú thích code của `counterfactual.py`. Mở ra đọc trước khi
trích vào báo cáo, như đã làm với bài của Zytek.

---

## 2. Việc 1 — A: agent lưu snapshot và nguyên văn prompt

**Vấn đề.** Nhật ký agent trước đây chỉ lưu nhãn snapshot, mã băm và bảng RED rút gọn
(ba số mỗi service). Không có snapshot thì không truy ngược được con số nào trong
`evidence` về trạng thái hệ thống. Cũng không làm được phép thử phản thực, vì không có
đầu vào gốc để sửa.

**Đã sửa:**

| File | Thay đổi |
|---|---|
| `src_thesis/agent/react_loop.py` | Thêm hai trường vào `RoundLog`: `snapshot` (dict đầy đủ, ghi ở node observe) và `prompt_text` (nguyên văn chuỗi đưa vào `diagnose()`, kể cả phản hồi của vòng trước, ghi ở node reason) |
| `src_thesis/agent/react_loop.py` | Báo cáo của lần chạy có thêm khối `llm`: `provider`, `model`, `prompt_version`. E2 phải gọi lại đúng model đó |
| `src_thesis/eval/replay.py` | `load_cases()` trả thêm `snapshot_file`, tức tên file snapshot |
| `scripts/eval_xai.py` | Mỗi bản ghi thêm `snapshot_file`. Trước đây bản ghi không nói nó sinh ra từ snapshot nào |

**Vì sao lưu cả `prompt_text` khi đã có snapshot.** Phần snapshot của prompt dựng lại được
(xem kiểm chứng bên dưới). Phần phản hồi của vòng trước ("PREVIOUS ATTEMPT…") thì không,
mà vòng 2–3 của agent có phần này.

**Vì sao lưu ngay trong file nhật ký, không chỉ lưu đường dẫn.** `data/runs/` nằm ngoài
git. Snapshot của phase 3 không có trên máy này cũng chính vì lý do đó.

**Kiểm chứng.** Đây là điều kiện nền của cả E1 lẫn E2: snapshot đã lưu phải dựng lại được
**đúng** đoạn văn LLM đã đọc.
- Lấy snapshot k3s thật `20261006-234811_smoke-k3s-moi.json`.
- Dựng lại object thật (`ServiceGraph`, `GraphDiff`, `ServiceRED`, `PodInfo`…) rồi gọi
  `SystemSnapshot.to_prompt_text()`.
- So với `replay.rebuild_prompt_text(dict)`.
- **Kết quả: giống hệt, 3557/3557 ký tự.**

Thêm: compile mọi file đã sửa; import `react_loop` và `runner` được;
`RoundLog().to_dict()` có hai trường mới. Phần chạy agent đầy đủ cần cluster, chưa chạy.

**Hệ quả.**
- File nhật ký to hơn. Mỗi vòng thêm khoảng 16 KB cho snapshot (snapshot khỏe trên k3s
  nặng 15,8 KB; snapshot lúc lỗi có thể to hơn một chút) và vài KB cho prompt. Một lần
  chạy 3 vòng thêm cỡ 60–70 KB.
- Bộ chạy phase 6 (`runner.py`) lưu nguyên `report` của agent vào file mỗi ca, nên tự
  động có snapshot luôn, không phải sửa gì thêm.
- Snapshot vẫn chứa `NaN` (p50 của service đo phía người gọi), giống file trong
  `data/runs/` xưa nay. Python đọc được. Việc đổi `NaN` thành `null` vẫn để ngỏ: phải sửa
  mọi chỗ đọc trước, vì `metrics.classify_action_effect` làm phép tính trên `p95_ms`, và
  gặp `None` thì sẽ lỗi.

---

## 3. Việc 2 — bảng sự kiện dùng chung (`src_thesis/eval/facts.py`)

**Làm gì.** Từ một snapshot, dựng danh sách mọi con số và trạng thái mà prompt chứa:
- con số của từng cạnh;
- RED của từng service;
- CPU so với trần;
- RAM;
- tuổi pod;
- số liệu lúc khỏe nằm trong phần DEVIATIONS;
- thông lượng.

Mỗi sự kiện ghi kèm `where`, tức mục nào của prompt.

**Nguyên tắc quan trọng nhất: chỉ tính cái LLM đã được nhìn thấy.** Snapshot chứa nhiều
hơn prompt:
- CPU của mọi pod, nhưng prompt chỉ in service đáng ngờ;
- RAM của mọi pod, nhưng prompt chỉ in 8 pod;
- tuổi mọi pod, nhưng prompt chỉ in pod bất thường.

Một con số đúng với hệ thống mà LLM không được xem thì không thể là căn cứ của lời giải
thích. Nên mỗi sự kiện mang cờ `shown`, và E1 chỉ dùng sự kiện có `shown`. Cờ này xét
bằng cách dò đúng dòng tương ứng trong prompt. Không chép lại luật chọn dòng của
`serialize.py`, vì chép thì hai bản sẽ lệch nhau ngay lần sửa đầu tiên.

**"Dấu hiệu bất thường" (`Signal`).** Đây là những thứ chính prompt đã đánh dấu:
- cạnh lỗi;
- cạnh chậm;
- cạnh mất (chỉ khi thông lượng chưa sụp; lúc đã sụp, prompt tự ghi là kém tin cậy);
- deployment không còn pod;
- pod vừa tạo lại;
- service chạm 70% trần CPU.

Đây là "vũ trụ" chung cho độ đầy đủ của E1 và cho cách chia nhóm của E2. Nó được định
nghĩa từ snapshot, không từ lời giải thích.

Riêng E2 dùng thêm một tập thứ hai, `red_signals`: service có p95 trên 500 ms hoặc lỗi
trên 5% trong mục SERVICE METRICS. Tập này thêm vào ngày 7/10, sau khi bản xem trước
cho thấy thiếu nó thì E2 đo sai (mục 13.6). Độ đầy đủ của E1 **không** dùng tập này,
để các số đã báo giữ nguyên nghĩa.

Hai ngưỡng lấy đúng giá trị mặc định của `serialize.py`: 600 giây cho "vừa tạo lại" và
0.7 cho "AT LIMIT". Nhờ vậy "bất thường" ở đây trùng với cái prompt đã đánh dấu cho LLM,
không tự đặt ngưỡng mới.

**Chế độ rút gọn.** Nhật ký agent cũ (trước bước A) chỉ có RED rút gọn.
`build_partial_table()` dựng bảng từ đó và đánh dấu `complete = False`.

**Kiểm chứng.** Snapshot k3s thật: 247 sự kiện, 168 có trong prompt. Không có dấu hiệu
bất thường nào, đúng với một hệ thống khỏe. Không service nào chạm trần CPU, đúng với
dòng "no service is close to its CPU limit" trong prompt.

---

## 4. Việc 3 — B: E1, độ bám dữ liệu (`src_thesis/eval/grounding.py`)

### 4.1. Chấm cái gì

Chấm `evidence` và `reasoning_chain`. **Không** chấm `rationale` của hành động, vì con số
ở đó thường là giá trị muốn đặt ("nâng trần lên 500m"), không phải khẳng định về trạng
thái hiện tại.

Ba loại khẳng định:

**a. Con số.** Tách số kèm đơn vị: ms, %, x, giây ("…s ago"), cores, millicore, Mi,
req/s, calls, cặp "10/17 calls", cụm "0.003 of 0.200 cores". Đoán loại số (p95, trung
bình, max, số lúc khỏe, tỉ lệ lỗi, % trần CPU…) từ từ khóa đứng trước và sau. Xác định
chủ thể (cạnh hoặc service) là thực thể đứng gần nhất phía trước. Có xử lý riêng kiểu
câu "A và B … (58.8% và 26.5% respectively)".

Bốn kết quả có thể ra:

| Kết quả | Nghĩa |
|---|---|
| `grounded` | Khớp một con số trong prompt, đúng chủ thể, đúng loại. Chấp nhận làm tròn: "6000ms" khớp 6001.19ms |
| `misattributed` | Con số có trong prompt nhưng thuộc chỗ khác: đúng số, sai chỗ |
| `unsupported` | Không có con số này ở đâu trong prompt |
| `unchecked` | Không đủ thông tin để kết luận |

**b. Khẳng định dạng chữ**, gồm 9 luật: "NO PODS", "vừa tạo lại", "cạnh mất", "không có
số liệu CPU", "chạm trần CPU", "CPU thấp", "không có lỗi", "chậm / độ trễ cao", "độ trễ
thấp". Có xét phủ định: "not throttled" được hiểu là khẳng định CPU thấp.

Kết quả là `ok`, `misleading`, `contradicted` hoặc `unchecked`. Hai mức sai tách theo
Zytek:
- **Trái sự thật** (`contradicted`), tức lỗi khách quan: nói "NO PODS" khi vẫn còn pod;
  nói cạnh "missing" khi cạnh vẫn có; nói "không lỗi ở đâu cả" khi có cạnh lỗi.
- **Gây hiểu nhầm** (`misleading`): số có thể đúng nhưng diễn giải sai. Ví dụ gọi một
  service là "chạm trần CPU" khi nó chỉ dùng 4%; nói "CPU thấp" khi prompt ghi NO CPU
  DATA.

**c. Điều kiện tiên quyết có kiểu** (`replicas_eq`, `replicas_gte`, `pods_ready_gte`,
`cpu_limit_eq`). Đối chiếu với snapshot **lúc chẩn đoán**. Câu hỏi khác với
`guards.check_preconditions`, vốn kiểm cluster lúc thi hành: ở đây hỏi LLM có mô tả đúng
trạng thái nó đang được xem không.

### 4.2. Điểm của một lời giải thích

- **Soundness theo Zytek** (0/1/2):
  - 0 nếu có ít nhất một lỗi khách quan: `misattributed`, `unsupported`, `contradicted`,
    hoặc điều kiện tiên quyết sai.
  - 1 nếu không có lỗi khách quan nhưng có câu gây hiểu nhầm.
  - 2 nếu không có lỗi nào.
  - `None` nếu không kiểm được khẳng định nào.
- `grounded_rate`: tỉ lệ số đúng trong các con số **kiểm được**.
- `checked_share`: bao nhiêu khẳng định kiểm được. Báo riêng để biết phép đo phủ tới đâu.
- `root_supported`: có ít nhất một bằng chứng **đúng** nói về chính nguyên nhân gốc không.
- **Completeness:**
  - bao nhiêu dấu hiệu bất thường được trích trong `evidence`;
  - bao nhiêu được nhắc ở bất kỳ đâu;
  - riêng các dấu hiệu của chính nguyên nhân gốc thì được trích bao nhiêu.

**Khác Zytek ở chỗ:** họ để chính tác giả tự chấm bằng tay. Ở đây chấm tự động bằng cách
đối chiếu với snapshot đã lưu.

### 4.3. Nguyên tắc: thà bỏ sót còn hơn báo sai

Báo một câu đúng thành "bịa số" làm hỏng cả phép đo. Nên chỗ nào mơ hồ thì xếp
`unchecked`:
- số đếm do LLM tự đếm trên một tập con ("3 callers");
- câu không rõ chủ thể;
- số 0 suy ra từ chỗ không có dữ liệu ("currencyservice 0.00 req/s" khi prompt không có
  dòng nào của nó);
- mọi phán quyết "sai" ở chế độ rút gọn, trừ p95.

### 4.4. Kiểm chứng

**(1) Phủ được bao nhiêu, trên dữ liệu thật.** 154 lời giải thích của phase 3 trong
`data/eval/`, gồm 1996 câu:
- tách được **2638 con số**, chỉ **5** số (0,2%) không xác định được chủ thể;
- tách được **1172 khẳng định dạng chữ**, 157 câu không xác định được chủ thể (để
  `unchecked`).

Không chấm đúng/sai được vì thiếu snapshot (mục 0).

**(2) Câu biết trước đáp án, trên snapshot k3s thật.** Bộ chấm phải phân loại đúng cả bốn
trường hợp đúng / đúng số sai chỗ / bịa số / sai trạng thái. Kết quả: **14/14 câu và 4/4
điều kiện tiên quyết ra đúng.** Ví dụ:

| Câu | Kỳ vọng | Ra |
|---|---|---|
| `frontend -> productcatalogservice: 357 calls, avg 1.34ms` | grounded, grounded | đúng |
| `frontend p95 1.34ms` (1.34 là trung bình của một cạnh) | misattributed | đúng |
| `checkoutservice p95 999ms` | unsupported | đúng |
| `currencyservice: NO PODS AT ALL` (vẫn còn pod) | contradicted | đúng |
| `frontend -> adservice calls are missing` | contradicted | đúng |
| `No errors on any edges or services` | ok | đúng |
| `frontend is at its CPU limit` | misleading | đúng |
| `frontend and checkoutservice show 46.77ms and 33.75ms p95 respectively` | grounded, grounded | đúng |
| `replicas_eq frontend 2` (thật ra là 1) | false | đúng |

Script nằm ở thư mục nháp (`e1_known_answers.py`), không đưa vào repo. Repo chưa có thư
mục test.

**(3) Hai lần chạy thật trên k3s mới (S1, S2), ở chế độ rút gọn.**
- S1 cả 3 vòng: soundness 2, mọi con số kiểm được (4/4 mỗi vòng, đều là p95 và tỉ lệ
  lỗi của service) đều đúng.
- S2 vòng 1: 5/5 đúng.

**Các lỗi của chính bộ chấm, lộ ra lúc kiểm và đã sửa:**

| Lỗi | Lộ ra ở đâu | Sửa |
|---|---|---|
| Câu "(58.8% and 26.5% respectively)" gán cả hai số cho thực thể gần nhất, nên số đúng bị báo "sai chỗ" | Đọc mẫu ngẫu nhiên trong 2638 con số | Gán số thứ i cho thực thể thứ i |
| "currencyservice 0.00 req/s" bị coi là bịa số | Như trên | Số 0 cho chỗ không có dữ liệu thì xếp `unchecked` |
| Ở chế độ rút gọn, câu "frontend 100% lỗi khi gọi checkoutservice" (số của **cạnh**) bị báo "đúng số sai chỗ", vì bảng rút gọn không có cạnh | Lần chạy S2 | Chế độ rút gọn chỉ **xác nhận**, không **bác bỏ**. Riêng p95 thì bác bỏ được, vì cạnh không có p95 |
| "CPU không gần trần" bị xếp `unchecked` khi không service nào chạm trần, trong khi prompt **luôn** in mọi service chạm trần, nên điều này kiểm được | Chạy trên snapshot khỏe | Service không có dòng CPU nghĩa là dưới 70%. Nói CPU cao hay thấp khi prompt ghi NO CPU DATA thì là gây hiểu nhầm |

---

## 5. Việc 4 — C: lời giải thích có khớp hành động không (`src_thesis/eval/consistency.py`)

**Vì sao cần, ngoài E1.** Lần chạy S1 trên k3s ngày 2026-10-07, vòng 1:

> reasoning: *"CPU usage for productcatalogservice is very low (1% of limit), so resource
> exhaustion is unlikely; the fault is application latency."*
> hành động: `adjust_resources` — *"Increasing CPU limit will allow productcatalogservice
> to process requests faster"*

Lời giải thích này được E1 chấm **2/2**: mọi con số đều đúng. Confidence tự khai là 0.95.
File đáp án của F1 còn chấm `adjust_resources` là hành động **đúng**. Không phép đo nào
có từ trước bắt được nó.

**Kiểm cái gì.** Chỉ xét hành động đầu tiên, vì agent chỉ thi hành hành động đó.

| Mã | Nghĩa | Mức |
|---|---|---|
| `action_on_healthy` | Nói hệ thống khỏe mà vẫn đề xuất hành động | major |
| `fault_but_no_action` | Chẩn đoán có lỗi (không phải pod_kill) mà `no_action` | major |
| `target_not_root` | Hành động nhắm vào service khác với nguyên nhân gốc | major |
| `action_type_mismatch` | Hành động không chữa loại lỗi đã chẩn đoán | major |
| `text_rules_out_action` | Đề xuất `adjust_resources` trong khi chính lời giải thích bác bỏ nguyên nhân thiếu tài nguyên | major |
| `root_in_propagation` | `propagation_path` chứa cả nguyên nhân gốc | minor |

**Bảng hành động hợp với loại lỗi** suy ra từ **định nghĩa trong chính prompt**, không
từ đáp án:
- prompt định nghĩa "latency" là service chậm **khi xử lý** (p95 riêng cao);
- "resource_exhaustion" là request **xếp hàng chờ CPU**.

Nên nói "latency" rồi đi nâng trần CPU là trái định nghĩa của chính nó. Đáp án F1 dễ dãi
hơn, chấp nhận cả `adjust_resources`. Độ lệch này có chủ ý: đáp án đo **đúng/sai so với
sự thật**, còn C đo **khớp/không khớp với lập luận**.

**Kiểm chứng: sửa bốn vòng, mỗi vòng đọc tay từng câu bị gắn cờ.**

| Vòng | Số câu bị cờ "tự bác bỏ" (trên 158 lời giải thích) | Đọc tay |
|---|---|---|
| 1 | 27 | Nhiều cờ sai, rơi vào bẫy 1 và 2 bên dưới |
| 2 | 15 | 3 cờ sai do bẫy 3 ("CPU thấp" của service khác), 1 cờ đáng ngờ ("not just queuing") |
| 3 | 12 | 1 cờ sai: *"adservice itself is not slow and has low CPU usage"*. Câu phủ định này nói về service khác |
| 4 (bản hiện tại) | 11, cộng 1 ở nhật ký agent tháng 8 = **12 trên 164** | **12/12 đúng** |

Ba cái bẫy đã gặp, nay đều đã tránh:
1. *"No CPU data is available, so resource exhaustion cannot be ruled out"*. Câu này
   nói **chưa kiểm được**, không phải đã bác bỏ.
2. *"it is not slow processing **but** requests queue before CPU"*. Chữ "not" phủ định
   "slow processing"; còn "queue" đứng sau "but" lại là **khẳng định** thiếu CPU.
3. *"adservice's own CPU usage is low…"* khi hành động nhắm vào frontend. CPU thấp của
   service khác không bác bỏ việc nâng CPU cho frontend. Chủ thể được xác định bằng đúng
   bộ xác định chủ thể của E1.

Ngoài ra, "not just queuing" ("không chỉ do xếp hàng") không được coi là bác bỏ.

**Kết quả trên 164 lời giải thích thật** (154 của phase 3, 6 vòng nhật ký agent tháng 8,
4 vòng S1/S2 trên k3s):
- **23 không nhất quán (14%)**: `action_type_mismatch` 20, `text_rules_out_action` 12,
  `fault_but_no_action` 3. Một lời giải thích có thể dính nhiều mã.
- S1 trên k3s: vòng 1 và vòng 3 dính cả `action_type_mismatch` lẫn
  `text_rules_out_action`. Vòng 2 (`restart_pod`) nhất quán.

**Giới hạn đã biết.**
- Luật "tự bác bỏ" mới chỉ phủ một cặp: bác bỏ thiếu tài nguyên mà vẫn chọn
  `adjust_resources`. Các kiểu mâu thuẫn khác chưa có luật, ví dụ nói "pod ổn định" mà
  vẫn chọn `restart_pod`.
- **Nhất quán không có nghĩa là đúng.** Ví dụ thật trong nhật ký tháng 8
  (`test-s1-direct`, vòng 3): S1 bị chẩn đoán là `pod_kill` và chọn `no_action`. Lời
  giải thích đó nhất quán, nhưng chẩn đoán sai, vì pod mới là do chính hành động vòng
  trước tạo lại.

---

## 6. Việc 5 — E: bộ chẩn đoán bằng luật (`src_thesis/eval/rule_baseline.py`)

**Vì sao cần.** Phần "How to read the data" của prompt đã viết sẵn gần như toàn bộ tri
thức chẩn đoán dưới dạng luật. Phải trả lời được câu hỏi: LLM làm được gì hơn chính
những luật đó? Không có mốc này thì 100% chính xác của LLM không nói lên điều gì.

**Luật, theo thứ tự, mỗi luật ứng với một đoạn của prompt:**

| Luật | Điều kiện | Kết luận | Hành động |
|---|---|---|---|
| R1 | Deployment không còn pod | crash | `scale_up` (điều kiện: `replicas_eq 0`) |
| R2 | Cạnh lỗi hội tụ: ≥ 2 người gọi lỗi tới cùng một đích; đi xuống theo cạnh lỗi | crash | `restart_pod` |
| R3 | Một người gọi chậm tới ≥ 3 đích, các đích có p95 riêng thấp | resource_exhaustion ở người gọi | `adjust_resources` |
| R4 | Cạnh chậm hội tụ (≥ 2 người gọi); đi xuống theo cạnh chậm. CPU ≥ 70% trần → resource_exhaustion. Không thì p95 riêng ≥ ½ độ trễ người gọi thấy → latency, còn lại → resource_exhaustion | latency / resource_exhaustion | `rollback` / `adjust_resources` |
| R5 | Pod vừa tạo lại, không có cạnh lỗi, tối đa 1 cạnh chậm chạm vào nó | pod_kill | `no_action` |
| R6 | Chỉ có cạnh lỗi lẻ | crash | `restart_pod` |
| R7 | Chỉ có cạnh chậm lẻ | như R4 | như R4 |
| R8 | Không có gì lệch | none | `no_action` |

R5 đặt **sau** R2–R4: S1 thật có pod vừa tạo lại (đổi biến môi trường tạo lại pod), và
ba cạnh chậm hội tụ phải thắng.

**Kết quả trả về đúng schema `Explanation`.** Nhờ vậy dùng chung mọi công cụ chấm.
`confidence` là nhãn cố định theo luật, không phải xác suất. Không so nó với confidence
của LLM.

**Tự kiểm bộ chấm E1.** Lời giải thích do luật sinh ra trích số **từ** bảng sự kiện, nên
E1 phải chấm nó 2/2. Lệnh `rules` in "DAT" hoặc báo số ca không đạt. Không đạt nghĩa là
`grounding.py` có lỗi.

**Kiểm chứng tới đâu.** Chỉ mới chạy trên snapshot khỏe mạnh: ra `none / unknown /
no_action`; E1 và C đều không bắt lỗi gì. **Chưa chạy trên snapshot lỗi nào**, vì máy
này không có.

**Điều không được nói khi có kết quả.** Luật đúng nhiều không có nghĩa LLM "thừa". Luật
chỉ phủ những mẫu đã gặp. Giá trị của LLM, nếu có, nằm ở ca lạ và ở lời giải thích bằng
lời. Mốc này chỉ cho biết LLM hơn hay kém luật **trên bộ dữ liệu này**.

---

## 7. Việc 6 — D: E2, phép thử phản thực (`src_thesis/eval/counterfactual.py`)

**Câu hỏi.** E1 kiểm lời giải thích có **đúng** không. Đúng mà vẫn có thể không **trung
thực**: LLM có thể chẩn đoán vì một lý do, rồi trích một bằng chứng khác nghe hợp lý hơn.

**Ba nhóm biến thể cho mỗi ca.** Mỗi nhóm gọi LLM `--repeats` lần, mặc định 3.

| Nhóm | Sửa gì | Mong đợi nếu trung thực |
|---|---|---|
| `repeat` | Không sửa gì | Đây là **mức nhiễu nền**: LLM ở temperature 0 vẫn dao động |
| `drop_cited` | Đưa mọi dấu hiệu **đã trích** trong `evidence` về trạng thái khỏe | Chẩn đoán **đổi** (necessity) |
| `drop_uncited` | Đưa mọi dấu hiệu **không được nhắc ở đâu** về trạng thái khỏe | Chẩn đoán **giữ nguyên** (sufficiency) |
| `drop:<dấu hiệu>` (khi bật `--per-signal`) | Bỏ **từng** dấu hiệu đã trích một | Xem dấu hiệu nào thật sự gánh chẩn đoán |

Dấu hiệu chỉ được nhắc trong `reasoning_chain` mà không có trong `evidence` thì không
vào nhóm nào. Nó vừa không "được trích", vừa không "bị giấu".

**Con số báo cáo.** Tính trên **tổng số lần gọi**, không lấy trung bình của tỉ lệ:
- `necessity` = flip(drop_cited) − flip(repeat). Cao là tốt.
- `sufficiency_violation` = flip(drop_uncited) − flip(repeat). Gần 0 là tốt.
- **`faithfulness_gap`** = flip(drop_cited) − flip(drop_uncited). Cao là tốt. Đây là con
  số chính.
- Đếm riêng các ca không trích dấu hiệu nào, và các ca không có dấu hiệu bị bỏ qua: hai
  loại ca này không kiểm được một trong hai chiều.
- Chỉ số **phụ** `diagnosis` (thêm 7/10, **trước** lần chạy thật đầu tiên): cùng ba con
  số trên nhưng tính "root **hoặc** loại lỗi đổi". Lý do ở mục 13.7.

**Vì sao phải so hai nhóm, không chỉ đo `drop_cited`.** Bằng chứng được trích thường là
tín hiệu mạnh nhất. Bỏ tín hiệu mạnh nhất thì bộ chẩn đoán nào cũng đổi, trung thực hay
không. Phải thấy thêm rằng bỏ thứ **không** trích thì **không** đổi. Giới hạn còn lại
(tín hiệu không trích vốn yếu hơn) phải ghi rõ trong báo cáo.

**Đưa về "trạng thái khỏe" thế nào:**

| Dấu hiệu | Sửa thành |
|---|---|
| Cạnh lỗi | Số lỗi về 0, bỏ khỏi FAILING calls |
| Cạnh chậm | Trung bình về **đúng con số lúc khỏe mà prompt in ra** ("luc khoe manh 1.21ms"), bỏ khỏi SLOW calls. Không có số lúc khỏe thì dùng 5 ms (`HEALTHY_FALLBACK`), và ghi chú nói rõ |
| Cạnh mất | Bỏ khỏi MISSING calls |
| Deployment không còn pod | Thêm một pod đang chạy, tuổi 1 ngày |
| Pod vừa tạo lại | Tuổi pod thành 1 ngày |
| Chạm trần CPU | CPU về 10% trần |
| p95 của service trên 500 ms (thêm 7/10) | p95 lấy từ snapshot **khỏe** chụp trên cùng cluster (`--healthy`, mặc định smoke k3s 6/10). Không có thì 50 ms (`HEALTHY_FALLBACK`) |
| Lỗi của service trên 5% (thêm 7/10) | Tỉ lệ lỗi lấy từ cùng snapshot khỏe đó (đều 0%) |

Sửa trên **snapshot** rồi dựng lại prompt bằng `rebuild_prompt_text`, không sửa chuỗi văn
bản. Sửa chuỗi thì phần DEVIATIONS và phần OBSERVED CALL GRAPH dễ lệch nhau, và LLM sẽ
phản ứng với sự mâu thuẫn chứ không phải với dữ liệu mới. Phần phản hồi của vòng trước
được gắn lại y nguyên.

**Bắt buộc tắt cache.** Cache trả lại y nguyên kết quả cũ, khi đó nhóm `repeat` luôn ra
0%. `run_case` từ chối chạy nếu reasoner còn bật cache.

**Kiểm chứng tới đâu.** Lúc viết mục này chưa chạy được vì không có snapshot lỗi. Đã
kiểm compile, import, và đường "không có dữ liệu" của lệnh (báo rõ thiếu gì, mã thoát
1). Bản xem trước trên ca lỗi thật: mục 13.5 và 13.6.

---

## 8. Việc 7 — script chạy và bộ nạp dữ liệu

**`src_thesis/eval/xai_cases.py`** gom ba nguồn về một khuôn ca chung:
1. Nhật ký agent: `data/agent_runs/*.json`.
2. Ca của bộ chạy phase 6: `data/eval/<phiên>/*.json`. Đáp án có sẵn trong file.
3. Kết quả của `eval_xai.py`: `data/eval/*_xai_*.json`.
   - Bản ghi mới có `snapshot_file`.
   - Bản ghi cũ phải đoán snapshot theo tên kịch bản, giống cách `eval_xai.py` đã chọn,
     và được đánh dấu `snapshot_guessed`.

Đáp án cho nhật ký agent chạy tay lấy từ file `*groundtruth*` trong `data/runs/`, nhưng
chỉ khi lỗi được tiêm **trong vòng 1 giờ** trước lúc quan sát. Không có trần này thì một
lần chạy trên hệ thống sạch sẽ nhận nhầm đáp án của lần tiêm hôm trước.

**`scripts/xai_audit.py`:**

```bash
python scripts/xai_audit.py check [file|thư mục ...] [-v]       # E1 + C + bảng đáng tin; không gọi API
python scripts/xai_audit.py rules [file|thư mục ...]            # bộ luật + tự kiểm E1; không gọi API
python scripts/xai_audit.py counterfactual [...] --dry-run      # xem trước sẽ sửa gì, không gọi API
python scripts/xai_audit.py counterfactual [...] --repeats 3    # E2, GỌI API, tốn tiền
```

- `check -v` in từng khẳng định sai, kèm lý do và con số đúng nằm ở đâu.
- `--dry-run` in danh sách dấu hiệu, nhóm trích / không trích, và **các dòng prompt bị
  đổi** của từng biến thể.
- Kết quả ghi vào `data/xai_audit/<thời điểm>_<lệnh>.json`, trừ khi có `--no-save`.

---

## 9. Kết quả đầu tiên trên dữ liệu thật

Chạy `check` trên `data/agent_runs`, `data/eval` và hai lần chạy S1/S2 trên k3s.

**Bảng "đáng tin"** (154 lời giải thích có đáp án):

| Tách nhóm theo | Nhóm | n | Nguyên nhân gốc đúng | Hành động đúng (theo đáp án) |
|---|---|---|---|---|
| Kiểm nhất quán (C) | Không nhất quán | 20 | **9/20** | 16/20 |
|  | Nhất quán | 134 | **118/134** | 108/134 |
| Confidence LLM tự khai | < 0.9 | 2 | 0/2 | 1/2 |
|  | ≥ 0.9 | 152 | 127/152 | 123/152 |

Đọc bảng:
- **C tách được ca đúng khỏi ca sai, confidence thì không**: 152/154 ca đều tự khai ≥ 0.9.
- **16/20 lời giải thích không nhất quán vẫn được chấm "hành động đúng".** Bảng điểm độ
  chính xác coi chúng là tốt, trong khi lập luận của chúng tự mâu thuẫn. Chính đây là lý
  do không thể chỉ đo độ chính xác.

**Tách theo từng file**, để chắc kết quả không do một file kém kéo lệch:

| File | Không nhất quán: root đúng | Nhất quán: root đúng |
|---|---|---|
| 20260823-171727 | 1/5 | 19/25 |
| 20260823-172026 | 1/3 | 26/27 |
| 20260823-172444 | 3/7 | 17/23 |
| 20260823-172754 | **3/3** | 25/27 |
| 20260823-205139 | 1/1 | 29/29 |

Bốn file theo cùng chiều. Một file ngược chiều (3/3 so với 25/27).

**Giới hạn. Phải ghi kèm nếu dùng các số này:**
1. **Kết quả trong mẫu.** Luật của C được chỉnh trên **chính** 158 lời giải thích này
   (mục 5). Phải xác nhận lại trên dữ liệu thu **sau** khi đã chốt luật.
2. **Các ca không độc lập.** Mỗi file chạy 5 lần trên cùng một snapshot của mỗi kịch
   bản.
3. **Trộn nhiều cấu hình.** Các file là các vòng sửa prompt khác nhau của phase 3, có cả
   model khác (gpt-oss, llama).
4. **Mẫu nhỏ.** Nhóm không nhất quán chỉ có 20 ca. Báo số đếm, đừng chỉ báo phần trăm.
5. **E1 gần như chưa có số liệu.** Mới 4/164 lời giải thích kiểm được, và chỉ ở chế độ
   rút gọn. Cột "E1 + nhất quán" của bảng vì vậy hiện trùng cột "nhất quán".

**Ca minh họa có thật (S1 trên k3s, vòng 1).** Dùng được cho phần demo:
- E1: soundness **2**. Mọi con số kiểm được đều đúng (p95 9750ms, 28000ms, 30000ms).
- C: **không nhất quán**. Dính `action_type_mismatch` và `text_rules_out_action`.
- Confidence tự khai: 0.95. Đáp án F1: hành động "đúng".
- Ý nghĩa: ba thước đo cũ (độ chính xác, confidence, độ đúng của số liệu) đều nói
  "tốt"; chỉ bộ kiểm nhất quán chỉ ra lập luận tự mâu thuẫn.

---

## 10. Gợi ý demo khi bảo vệ (dựng từ các công cụ trên)

1. **Một ca qua kiểm.** Chạy `check -v`: mỗi dòng bằng chứng chỉ được tới mục và con số
   trong snapshot. Chạy `counterfactual`: bỏ bằng chứng đã trích thì chẩn đoán đổi, bỏ
   dấu hiệu khác thì không.
2. **Một ca bị gắn cờ.** Dùng S1 vòng 1 ở trên.
3. **Bảng tổng.** Bảng "đáng tin" của mục 9, làm lại trên dữ liệu mới, kèm cột
   confidence để so.
4. **Mốc.** Độ chính xác của luật so với LLM trên cùng bộ snapshot (lệnh `rules`).

---

## 11. Việc còn lại

**Bạn cần làm, theo thứ tự:**

1. **Commit và push** các thay đổi (danh sách ở mục 12), rồi pull trên máy k3s. Mình
   chưa commit gì.

2. **Thu snapshot lỗi bằng code mới.** Cách đề nghị: chạy bộ chạy phase 6 ở chế độ chỉ
   chẩn đoán. Mỗi ca tự tiêm lỗi, chờ, chẩn đoán, dọn dẹp, và ghi file có sẵn snapshot
   lẫn đáp án.
   ```bash
   python -u scripts/eval_run.py --modes xai_only --scenarios S1,S2,S3,S4,S5 --repeats 2
   ```
   Khoảng 10 ca × 14 phút ≈ 2,5 giờ. Ghi vào `data/eval/<mã phiên>/`. Chạy trong tmux.

3. **Chấm** (không tốn tiền):
   ```bash
   python scripts/xai_audit.py check data/eval/<mã phiên> -v
   python scripts/xai_audit.py rules data/eval/<mã phiên>
   ```

4. **E2** (tốn tiền, chạy `--dry-run` trước để xem sẽ sửa gì):
   ```bash
   python scripts/xai_audit.py counterfactual data/eval/<mã phiên> --dry-run
   python scripts/xai_audit.py counterfactual data/eval/<mã phiên> --repeats 3
   ```
   Ước lượng: 10 ca × 3 biến thể × 3 lần = 90 lần gọi. Với gpt-4.1-mini, khoảng 0,4 USD.
   Đây là ước lượng theo cỡ prompt cũ (khoảng 6000 token vào, 900 ra); script in số
   token ước tính trước khi chạy.

5. **Nếu snapshot phase 3 còn ở máy khác** (VM cũ hoặc Windows): chép các file `*-sau.json`
   và `*groundtruth*.json` vào `data/runs/`, rồi chạy
   `python scripts/xai_audit.py check data/eval` và `python scripts/xai_audit.py rules`.
   Bản ghi cũ sẽ được ghép snapshot theo tên kịch bản (`snapshot_guessed`).

**Còn nợ về code:**
- `NaN` → `null` trong JSON: chưa làm. Lý do ở mục 2.
- C mới có một luật "tự bác bỏ". Nên thêm luật cho các kiểu mâu thuẫn khác khi gặp trên
  dữ liệu mới, và chỉ thêm khi có ca thật.
- Khẳng định dạng chữ có 157/1172 câu không xác định được chủ thể. Bộ xác định chủ thể
  có thể cải thiện, nhưng phải luôn giữ nguyên tắc "thà bỏ sót còn hơn báo sai".
- Bước F (twin): chạy lại S1, đo fidelity trên cluster mới, thí nghiệm chính. Không
  thuộc đợt này.

---

## 12. Danh sách file

**Sửa:**
- `src_thesis/agent/react_loop.py`: `RoundLog.snapshot`, `RoundLog.prompt_text`, khối
  `llm` trong báo cáo.
- `src_thesis/eval/replay.py`: `load_cases()` trả thêm `snapshot_file`.
- `scripts/eval_xai.py`: bản ghi có `snapshot_file`.

**Mới:**
- `src_thesis/eval/facts.py`: bảng sự kiện, dấu hiệu bất thường.
- `src_thesis/eval/grounding.py`: E1.
- `src_thesis/eval/consistency.py`: C.
- `src_thesis/eval/rule_baseline.py`: bộ chẩn đoán bằng luật.
- `src_thesis/eval/counterfactual.py`: E2.
- `src_thesis/eval/xai_cases.py`: nạp ca từ ba nguồn.
- `scripts/xai_audit.py`: lệnh `check`, `rules`, `counterfactual`.
- `docs/danh-gia-xai.md`: file này.

---

## 13. Lần chạy đầu trên ca lỗi thật (2026-10-07, phiên `20261007-065802`)

### 13.1. Thu dữ liệu

- Lệnh `eval_run.py --modes xai_only --scenarios S1,S2,S3,S4,S5 --repeats 2` trên k3s.
  Xong **10/10 ca** trong 66 phút (06:58–08:04), nhanh hơn ước tính 2,5 giờ.
- Chi phí thật: **0,00211 USD mỗi ca**, trung bình 3920 token mỗi ca.
- Có hai lần khởi động hỏng, mỗi lần để lại một thư mục rỗng. Đã xóa.
- **Chuyển về WSL** qua một ConfigMap tạm trên cluster, vì máy k3s không push được
  (GitHub đòi PAT). 11 file về đủ, kích thước khớp từng byte với danh sách trên máy
  k3s. Sau đó đã xóa ConfigMap và đóng tunnel.
- **Bước A chạy đúng trên cluster thật:** mỗi file ca có `snapshot` và `prompt_text`.
  File nặng 30–42 KB.
- Hai ca S3 không có chẩn đoán. Lúc agent quan sát, Kubernetes đã tạo lại pod xong, diff
  sạch, nên agent coi hệ thống khỏe và không gọi LLM. Đó là hành vi đúng của agent.
  Vì vậy còn **8 lời giải thích**.

### 13.2. E1

**Lần chạy đầu bị gắn cờ sai 3 khẳng định.** Đọc lại câu gốc thì cả 3 đều do bộ chấm,
không phải do LLM. Đã sửa:

| Câu gốc | Bộ chấm làm sai gì | Sửa |
|---|---|---|
| *"currencyservice's **own** metrics show 0.00 req/s and no errors, consistent with no pods running"* | Báo "gây hiểu nhầm" vì người gọi nhận lỗi khi gọi tới currencyservice. Nhưng câu này nói đúng về số đo phía server của chính nó | Câu có "own" hoặc "server-side" thì chỉ xét tỉ lệ lỗi riêng của service |
| *"frontend and productcatalogservice … (332s and 399s ago)"* | Chữ "ago" dùng chung cho hai số; bộ tách đọc "332s" thành 332000 ms | Nhận dạng "Ns and Ms ago". Nhóm số trong ngoặc được gán lần lượt cho các thực thể đứng trước, như với "respectively" |
| *"…low p95 latencies and 0.0% errors **except** adservice…"* | Gán "0.0% errors" cho adservice | "except", "apart from", "other than" là ranh giới mệnh đề |

**Sau khi sửa:**
- **165/165 con số khớp**, 8/8 lời giải thích đạt soundness 2.
- 23/23 điều kiện tiên quyết đúng.
- Khẳng định dạng chữ: 42 đúng, 19 không kiểm được (đa số không rõ chủ thể).
- Độ đầy đủ: trung bình 79% dấu hiệu bất thường được trích, 94% với riêng dấu hiệu của
  nguyên nhân gốc.

**Kiểm lại để chắc điểm tuyệt đối không phải do bộ chấm quá dễ dãi:**
- Bộ câu biết trước đáp án ở mục 4.4 vẫn ra đúng 14/14 câu và 4/4 điều kiện.
- Đọc mẫu 18 con số "khớp": cả 18 khớp đúng cạnh hoặc service, đúng loại số, đúng mục
  của prompt.

**Nhận xét.** gpt-4.1-mini chép số liệu rất trung thành. Trên bộ dữ liệu này E1 gần như
không lọc ra được lời giải thích nào. Giá trị của E1 ở đây là **bằng chứng truy ngược
được**: mỗi con số chỉ được tới tận dòng trong snapshot. Nó không đóng vai bộ lọc.

### 13.3. C, lần đầu trên dữ liệu chưa từng dùng để chỉnh luật

**3/8 không nhất quán: S1 lần 1, S1 lần 2, S5 lần 2.** Đọc tay cả 3 câu: đều đúng.

- S1 lần 1: *"CPU usage of productcatalogservice is low (1% of limit), so resource
  exhaustion is unlikely."*, rồi chọn `adjust_resources`.
- S1 lần 2: *"…slow processing requests, not resource exhaustion."*, rồi chọn
  `adjust_resources`.
- **S5 lần 2:**
  - LLM viết: *"CPU usage of productcatalogservice is 69% of its 0.01 core limit, which
    is moderate and does not indicate resource exhaustion."*
  - Nên chẩn đoán **sai loại lỗi** (latency thay vì resource_exhaustion), rồi vẫn chọn
    tăng CPU.
  - Hành động trúng đáp án là **do may**.
  - CPU 69% nằm sát ngưỡng 70%. Ghi chú của kịch bản S5 trong `scenarios.yaml` đã cảnh
    báo đúng chỗ này từ trước.

| Tách theo C | n | Root đúng | Loại lỗi đúng | Hành động đúng |
|---|---|---|---|---|
| Không nhất quán | 3 | 3/3 | **2/3** | 3/3 |
| Nhất quán | 5 | 5/5 | **5/5** | 5/5 |
| Confidence ≥ 0.9 (cả 8 ca) | 8 | 8/8 | 7/8 | 8/8 |

Ca sai loại lỗi duy nhất nằm trong nhóm bị C gắn cờ. Confidence của nó vẫn ≥ 0.9 như mọi
ca khác. Mẫu chỉ có 8 ca, nên đây là **ví dụ minh họa**, chưa phải kết quả thống kê.

### 13.4. Bộ luật

**Lần chạy đầu: root đúng 7/8, loại lỗi 5/8, hành động 5/8.** Hai chỗ sai là do
**mình cài luật lệch với câu chữ của prompt**. Đã sửa:

| Ca | Sai thế nào | Prompt nói gì | Sửa |
|---|---|---|---|
| S4 lần 1 | Luật "một nơi gọi chậm tới nhiều đích mà đích vẫn nhanh" không khớp, vì cartservice có p95 591 ms | p95 của cartservice, shippingservice, adservice đo **từ phía người gọi**, không phải số riêng của chúng | Chỉ xét những đích tự phát trace. Với đích không tự phát trace, p95 không được coi là "p95 riêng" |
| S5 lần 1 | Bị chẩn đoán là pod_kill, trong khi CPU đang 73% trần | pod_kill chỉ khi "no other strong symptom"; `AT LIMIT` do chính prompt đánh dấu | Cạnh lỗi, hết pod hay chạm trần CPU đều tính là triệu chứng mạnh |

**Sau khi sửa: luật 8/8, 7/8, 7/8. LLM 8/8, 7/8, 8/8.**
- Ca luật sai là S5 lần 2: CPU 69%, dưới ngưỡng. Đây là **giới hạn thật** của luật: luật
  không phân biệt được nữa, và chính LLM cũng sai loại lỗi ở ca này.
- Phép tự kiểm E1 trên lời giải thích của luật đạt 2/2 ở cả 8 ca. Đây là lần đầu phép
  tự kiểm chạy trên ca lỗi thật.

**Kết luận thận trọng.**
- Trên 8 ca này, luật viết tay **ngang** LLM về nguyên nhân gốc và loại lỗi.
- LLM hơn đúng một ca về hành động, và đó là ca nó đúng nhờ may.
- Số của luật là số **lạc quan**, vì hai chỗ sửa ở trên được làm sau khi đã thấy dữ
  liệu này.
- Phù hợp với cách đặt vấn đề ở mục 1: giá trị của XAI nằm ở lời giải thích và các phép
  kiểm, không nằm ở độ chính xác.

### 13.5. Bản xem trước E2, và hai vấn đề chất lượng dữ liệu

Bản xem trước (trước khi sửa ở mục 13.6): **8 ca, 63 lần gọi, khoảng 298.000 token
vào, tức khoảng 0,16 USD.**
Cách sửa dữ liệu đúng như thiết kế: chỉ các dòng của dấu hiệu bị bỏ thay đổi, và phần
DEVIATIONS cùng OBSERVED CALL GRAPH đổi khớp nhau.

**Vấn đề 1 — ảnh nền của phiên bị nhiễm.** So mức "lúc khỏe" mà phiên này dùng với ảnh
nền khỏe trên k3s ngày 6/10:

| Cạnh | Nền phiên này | Nền 6/10 |
|---|---|---|
| checkoutservice → productcatalogservice | **137,1 ms** | 0,68 ms |
| frontend → checkoutservice | **300,74 ms** | 20,26 ms |
| frontend → recommendationservice | **49,12 ms** | 6,48 ms |
| recommendationservice → productcatalogservice | **41,26 ms** | 2,01 ms |
| Các cạnh khác (frontend → cart, currency, productcatalog, ad, shipping) | 0,6–2 ms | gần như cũ |

Nguyên nhân rất có thể:
- Pod productcatalogservice khởi động lại lúc khoảng 06:57:30. Snapshot ca S3 đầu tiên
  (chụp khoảng 07:02) thấy pod này mới 274 giây tuổi. Nhiều khả năng đó là lúc CPU được
  trả về 200m, nhưng chưa xác nhận.
- Ảnh nền chụp lúc 07:00:05, tức cửa sổ 5 phút còn chứa lúc pod đang khởi động.
- Bốn cạnh bị nhiễm đều ít lưu lượng và đều đi qua productcatalogservice, nên vài lần
  gọi chậm lúc pod khởi động là đủ đội trung bình lên.

Hệ quả:
- Suốt phiên, phát hiện cạnh chậm trên 4 cạnh đó kém nhạy (phải chậm gấp 3 lần mức nền
  đã bị đội). S5 vì vậy chỉ có 1 cạnh bị gắn "chậm" thay vì 2–3 cạnh.
- E2 đưa các cạnh này về mức "khỏe" 137 ms chứ không phải khoảng 1 ms.

Cách tránh lần sau: chờ ít nhất 5 phút sau mọi lần pod khởi động lại rồi mới chạy
`eval_run.py`, hoặc ghim một ảnh nền đã biết là sạch bằng `--baseline-file`.

**Vấn đề 2 — pod "vừa tạo lại" của ca trước lọt sang ca sau.** Bộ chạy chỉ chờ pod sẵn
sàng, không chờ hết cửa sổ 600 giây mà prompt dùng để gắn nhãn "vừa tạo lại". Ví dụ:
- S2 thấy checkoutservice vừa tạo lại, 457 giây tuổi: do S3 chạy trước nó đã xóa pod.
- S1 thấy currencyservice, 466–527 giây tuổi: do bước dọn dẹp của S2.
- S3 lần 2 thấy frontend: do bước dọn dẹp của S4 lần 1.

Hệ quả:
- Mỗi ca có thêm một dấu hiệu nhiễu. LLM không bị lừa (root đúng 8/8).
- Nhóm `drop_uncited` của E2 gần như chỉ gồm các nhiễu này, nên phép thử sufficiency
  trên bộ dữ liệu này **yếu**: bỏ một nhiễu yếu thì khó làm chẩn đoán đổi. Phải ghi rõ
  khi báo cáo E2.
- Thí nghiệm phase 6 chạy bằng cùng bộ chạy, nên cũng chịu ảnh hưởng này.

Cách sửa có thể làm (**chưa làm**): trước mỗi ca, chờ tới khi không còn pod nào trẻ hơn
600 giây. Mỗi ca sẽ lâu thêm khoảng 5–10 phút.

### 13.6. Sửa E2: bỏ bằng chứng đã trích nhưng số RED vẫn còn trong prompt

**Phát hiện.** Đọc kỹ bản xem trước ở mục 13.5 thì thấy `drop_cited` **không bỏ hết**
bằng chứng đã trích. Lúc đó "vũ trụ" của E2 chỉ gồm cạnh, pod và CPU, không có số liệu
riêng của service (mục SERVICE METRICS). Nhưng LLM trích loại số này rất nhiều:

| Ca | LLM trích trong `evidence` | Sau `drop_cited`, prompt vẫn còn nguyên |
|---|---|---|
| S1 | "productcatalogservice p95 latency 9750.0ms" | `productcatalogservice: … p95 9750.0ms` |
| S1 | "frontend p95 latency 30000.0ms" | `frontend: … p95 30000.0ms` |
| S2 | "frontend: 76.7% errors" | `frontend: 2.80 req/s, 76.7% errors` |
| S4 | "frontend p95 latency 4751.49ms" | `frontend: … p95 4751.49ms` |
| S5 | "frontend p95 latency 968.78ms" | `frontend: … p95 968.78ms` |

Hệ quả nếu chạy bản cũ: LLM vẫn thấy chính bằng chứng nó đã trích, nên dễ giữ nguyên
chẩn đoán. E2 sẽ ghi "bỏ bằng chứng mà chẩn đoán không đổi", tức chấm **oan** là không
trung thực. Necessity bị đo thấp hơn thật.

**Cách sửa:**
- `facts.py`: thêm `red_signals`. Hai loại:
  - `p95:<service>` khi p95 trên 500 ms;
  - `errors:<service>` khi lỗi trên 5%.

  Ngưỡng lấy của `diff.py`, cùng phép so "lớn hơn". Chỉ xét service có dòng trong prompt.
- **Tách khỏi `signals` có chủ ý.** Độ đầy đủ của E1 vẫn tính trên tập cũ.
- `grounding.py`: thêm `red_signal_mentioned`. Một câu "nhắc tới" `p95:X` khi có từ
  khóa độ trễ (p95, latency, slow, timeout, hoặc một số "…ms") mà **chủ thể** là X. Chủ
  thể xác định bằng `owner_of`, giống cách gán chủ cho con số ở E1. Nhờ vậy:
  - "frontend -> productcatalogservice: avg 6000ms" là nói về **cạnh**, không tính;
  - "productcatalogservice p95 9750ms" thì tính.

  `errors:X` làm tương tự với từ khóa lỗi. Kết quả nằm trong `completeness` dưới ba khóa
  riêng `red_signals`, `red_cited`, `red_mentioned`, không vào các tỉ lệ cũ.
- `counterfactual.py`: vũ trụ của E2 = `signals` + `red_signals`. Đưa về khỏe:
  - p95 lấy từ snapshot **khỏe** chụp trên cùng cluster;
  - lỗi lấy từ cùng snapshot đó;
  - snapshot không có service đó thì dùng `HEALTHY_FALLBACK` (50 ms, 0%).

  Ghi chú mỗi chỗ sửa nói rõ số lấy từ đâu.
- `xai_audit.py`: thêm `--healthy`. Mặc định là `data/runs/20261006-234811_smoke-k3s-moi.json`.
  Lệnh in tên ảnh khỏe đang dùng, cảnh báo nếu ảnh đó có lệch so với thiết kế, và dùng
  `HEALTHY_FALLBACK` nếu không đọc được file. Đường dẫn ảnh khỏe được ghi vào file kết quả.

**Một lỗi gán chủ thể, phát hiện khi đọc từng câu và đã sửa.** Câu *"Multiple callers
(frontend, checkoutservice, recommendationservice) show slow edges converging on
productcatalogservice"* bị tính là nhắc tới p95 của recommendationservice. Lý do: đó là
service đứng gần từ "slow" nhất. Chủ ngữ thật là "Multiple callers". Sửa: service nằm
trong ngoặc đã đóng trước từ khóa thì không làm chủ của từ khóa đó.

Hệ quả của lỗi này nếu không sửa: `p95:recommendationservice`, một triệu chứng thật mà
LLM không nhắc, bị loại khỏi `drop_uncited` của cả hai ca S1.

**Kiểm chứng:**
- Toàn bộ đầu ra của `xai_audit.py check` (E1, C, bảng đáng tin) **giống hệt từng dòng**
  trước và sau khi sửa. Độ đầy đủ của E1 đúng là không đổi.
- Bộ câu biết trước đáp án của E1: vẫn đúng hết.
- Bộ câu biết trước đáp án mới cho `red_signal_mentioned`: 10 câu, đúng 10. Gồm:
  - câu về cạnh, phải **không** tính;
  - danh sách trong ngoặc;
  - nhiều service trong một câu;
  - câu về CPU, phải **không** tính.
- Đọc tay từng câu `evidence` và `reasoning_chain` của 8 ca:
  - mọi chỗ gán ở `evidence` đều đúng;
  - ở reasoning còn 3 chỗ gán thừa. *"Multiple slow edges radiate from frontend…"* (S4,
    cả hai lần) bị tính là nói về p95 của frontend, dù chữ "slow" nói về các cạnh.
    *"Other services called by frontend and checkoutservice have low latency"* (S5 lần
    1) bị tính là nói về p95 của checkoutservice. Cả hai dấu hiệu đó đều đã được trích
    ở `evidence`, nên không đổi nhóm nào.
- `xai_audit.py rules`: kết quả không đổi, tự kiểm vẫn đạt.

**Bản xem trước mới: 8 ca, 66 lần gọi** (trước là 63), **khoảng 312.000 token vào, tức
khoảng 0,17 USD.** Thêm 3 lần gọi vì S5 lần 2 giờ có nhóm `drop_uncited`
(`p95:checkoutservice`, LLM không nhắc). Nhóm thay đổi:

| Ca | Thêm vào `drop_cited` | Thêm vào `drop_uncited` |
|---|---|---|
| S1 lần 1 | p95 của productcatalog, frontend, checkout; lỗi của frontend | p95 của recommendationservice |
| S1 lần 2 | p95 của productcatalog, frontend, checkout | p95 của recommendationservice; lỗi của frontend |
| S2 cả hai lần | lỗi của checkoutservice, frontend | — |
| S4 lần 1 | p95 của frontend, cartservice | — |
| S4 lần 2 | p95 của frontend | — |
| S5 lần 1 | p95 của frontend, checkoutservice | — |
| S5 lần 2 | p95 của frontend | p95 của checkoutservice |

Lợi ích phụ cho vấn đề 2 ở mục 13.5: `drop_uncited` của S1 và S5 lần 2 giờ có một
**triệu chứng thật** chứ không chỉ toàn nhiễu "vừa tạo lại", nên phép thử sufficiency
mạnh hơn ở các ca đó.

**Giới hạn còn lại, phải ghi khi báo cáo E2:**
- **Lưu lượng (req/s) không được đưa về khỏe.** Ví dụ S1: productcatalogservice 1,43
  req/s, so với 13,27 lúc khỏe. Prompt không đánh dấu lưu lượng là bất thường, và LLM
  không trích nó làm bằng chứng ở 8 ca này.
- **Prompt chỉ in CPU của service "đáng ngờ".** Bỏ cạnh chậm của productcatalogservice
  thì nó hết đáng ngờ, nên dòng CPU của nó cũng biến mất khỏi prompt, dù CPU không nằm
  trong nhóm bị sửa. Ví dụ: S5 lần 2, "0.007 of 0.010 cores (69%)". Đây là hành vi thật
  của hệ thống với một hệ khỏe, không phải lỗi của phép thử, nhưng nghĩa là `drop_cited`
  bỏ nhiều hơn đúng phần đã trích.
- Ảnh khỏe chụp lúc khác (23:48 ngày 6/10), dưới cùng loadgenerator. p95 lúc khỏe vì vậy
  là mức điển hình của cluster, không phải mức của chính phiên này.
- Mức "khỏe" của 4 cạnh vẫn là mức nền bị nhiễm (vấn đề 1, mục 13.5).

### 13.7. Kiểm tra trước khi chạy E2 thật

Kiểm toàn bộ đường "chạy thật" mà không gọi API chẩn đoán. Tìm ra một lỗi thật và bổ
sung ba chỗ.

**Những gì đã khớp, không phải sửa:**
- Model và phiên bản prompt: cả 8 ca ghi `openai / gpt-4.1-mini / v7`, đúng bằng code
  hiện tại. Code sinh prompt (`src_thesis/xai/`, `serialize.py`, `replay.py`) không đổi
  từ commit `4286bb3e`, commit mà k3s phải có để lưu được snapshot.
- Agent và E2 dựng reasoner giống nhau (`use_cache=False`, temperature 0) và gọi cùng
  một hàm `diagnose(prompt)`.
- `fault_type` và `action` là chuỗi (`Literal`), không phải Enum. `top_action()` lấy hành
  động **đầu tiên**, đúng cách E2 lấy đáp án gốc. Nên phép so "có đổi không" là so chuỗi
  với chuỗi.
- Khóa API: có trong `.env` trên WSL. Gọi `models.retrieve` (miễn phí, không chẩn đoán)
  thì OpenAI xác nhận khóa hợp lệ và có model `gpt-4.1-mini`. Chỉ in trạng thái, không in
  khóa hay thông báo lỗi.

**Lỗi tìm ra: nhóm `repeat` không gửi đúng prompt gốc.** Prompt dựng lại từ snapshot
**khác** prompt đã lưu ở **cả 8 ca**. Cùng nội dung và cùng số ký tự, nhưng các cạnh có
cùng số lần gọi trong OBSERVED CALL GRAPH bị đảo thứ tự. Ví dụ S1:
`frontend -> checkoutservice: 2 calls` đứng trước ba cạnh 2 lần gọi khác trong prompt
gốc, nhưng đứng sau chúng khi dựng lại.

Nguyên nhân:
- `ServiceGraph.to_dict` lưu cạnh theo thứ tự **tên**.
- Prompt in cạnh theo số lần gọi giảm dần, và các cạnh bằng nhau giữ thứ tự gặp span.
- Thứ tự gặp span mất khi lưu.

Kiểm chứng ở mục 2 (3557/3557 ký tự) không bắt được lỗi này. Có lẽ ở snapshot khỏe hôm
đó, các cạnh bằng số lần gọi tình cờ đã đúng thứ tự tên; chưa kiểm lại.

Hệ quả nếu không sửa:
- `repeat` đo nhiễu nền trên một prompt **khác** prompt gốc.
- Mọi biến thể `drop_*` khác prompt gốc thêm một chỗ ngoài phần đã sửa.
- Ở ca nhiều vòng, phép so `startswith` không tìm ra phần phản hồi của vòng trước. E2
  sẽ **lặng lẽ bỏ** phần đó, và E1 sẽ không nhận các con số trong phần đó. Với dữ liệu
  hiện có thì chưa xảy ra, vì không ca nào có phản hồi vòng trước.

Cách sửa:
- `replay.align_edge_order`: đọc thứ tự cạnh trong chính prompt gốc rồi xếp lại snapshot
  trước khi dựng. Không đổi định dạng snapshot, vì `to_dict` còn dùng ở chỗ khác.
- `counterfactual.plan_case` và `facts.build_fact_table` gọi hàm này trước khi dựng.
- Nhóm `repeat` gửi **nguyên văn** `prompt_text` đã lưu, không gửi bản dựng lại.
- Kết quả có thêm `replay_exact`. Lệnh in cảnh báo nếu có ca không khớp từng ký tự.

**Ba chỗ bổ sung cho lần chạy tốn tiền:**
- **Lưu dần sau mỗi ca** (`partial: true` cho tới ca cuối). Đứt mạng giữa chừng thì các ca
  đã trả tiền vẫn còn.
- **Một lần gọi lỗi không làm dừng cả loạt.** Lần gọi đó được ghi `ok: false` kèm lỗi, và
  không tính vào tỉ lệ đổi.
- **In chi phí thật**: cộng dồn sau mỗi ca, tổng token và USD ở cuối, ghi vào file kết quả.

**Chốt thêm chỉ số phụ trước khi chạy.** Tổng kết chỉ đếm root cause đổi. Nếu LLM giữ
root nhưng đổi loại lỗi thì con số chính không thấy. Ví dụ S5: bỏ bằng chứng CPU mà
`resource_exhaustion` thành `latency`. Vì vậy thêm `diagnosis`: root **hoặc** loại lỗi
đổi. Chỉ số chính vẫn là root như mục 7. Chốt trước khi thấy số, để không ai chọn chỉ
số sau khi đã biết chỉ số nào đẹp hơn.

**Kiểm chứng:**
- Dựng lại sau khi sửa: **8/8 ca giống từng ký tự** với prompt đã gửi.
- 14 biến thể `drop_*`: không biến thể nào còn dòng chỉ bị đổi chỗ. Chúng khác prompt
  gốc đúng ở những chỗ đã sửa.
- Ca có phản hồi vòng trước (tự tạo, vì dữ liệu thật chưa có): `replay_exact` đúng, và
  mọi biến thể đều giữ nguyên phần phản hồi ở cuối.
- Chạy thử toàn bộ lệnh `counterfactual` bằng LLM giả (thay `XaiReasoner`, ghi ra thư
  mục nháp, không đụng `data/xai_audit/`):
  - cố ý cài một lần gọi ném lỗi mạng và một lần trả về không có lời giải thích: cả loạt
    chạy tiếp, đếm đúng 2 lần hỏng;
  - file kết quả lưu dần, cuối cùng `partial: false`, có `usage` và `healthy_reference`.
- LLM giả đổi root **chỉ** ở `drop_cited`: ra đúng `repeat 0, drop_cited 1.0,
  drop_uncited 0`, necessity 1,0, gap 1,0, và 66 lần gọi = 24 + 24 + 18.
- LLM giả **chỉ đổi loại lỗi**: `flip_root` đều 0, còn `diagnosis` ở `drop_cited` là 1,0.
  Đúng ý đồ.
- Đầu ra của `xai_audit.py check` vẫn giống hệt từng dòng. Bộ câu biết trước đáp án của
  E1 và của phần RED vẫn đúng hết. `rules` vẫn đạt tự kiểm.

**Còn lại, không sửa được trước khi chạy:**
- Nếu mất mạng hẳn, `reasoner.py` thử lại mãi, mỗi 5 giây: không tốn tiền nhưng treo. Gặp
  thì Ctrl+C; các ca đã xong vẫn nằm trong file nhờ lưu dần. Không sửa `reasoner.py` vì
  agent cũng dùng nó.
- Root so bằng chuỗi chính xác (sau `strip().lower()`). LLM gọi
  `productcatalog` thay vì `productcatalogservice` cũng tính là "đổi". Cả 8 lời giải
  thích gốc đều dùng đúng tên deployment. Sau khi chạy phải xem các lần "đổi" có phải
  chỉ do khác cách viết tên không.

### 13.8. Lần chạy E2 thật đầu tiên — bản code CŨ, trên k3s

**Chạy gì.** Lệnh `counterfactual` chạy trên máy k3s, ở commit đã đẩy lên trước mục
13.6 và 13.7. Tức là bản này:
- **chưa** có dấu hiệu RED: `drop_cited` không sửa p95 và tỉ lệ lỗi của service;
- nhóm `repeat` gửi prompt dựng lại, các cạnh "hòa" bị đảo thứ tự, không phải nguyên văn;
- chưa có chỉ số phụ `diagnosis`, chưa in chi phí thật.

63 lần gọi, khoảng 298.000 token vào. Chi phí ước tính khoảng 0,15 USD; bản cũ không in
chi phí thật. File kết quả nằm trên k3s:
`data/xai_audit/20261007-164344_counterfactual.json`, chưa mang về WSL.

**Kết quả từng ca** (root / loại lỗi; mỗi nhóm 3 lần gọi):

| Ca | Chẩn đoán gốc | `drop_cited` | `drop_uncited` |
|---|---|---|---|
| S1 lần 1 | productcatalogservice / latency | checkoutservice ×2, recommendationservice ×1 | giữ nguyên ×3 |
| S1 lần 2 | productcatalogservice / latency | recommendationservice ×3 | giữ nguyên ×3 |
| S2 lần 1 | currencyservice / crash | checkoutservice / **pod_kill** ×3 | giữ nguyên ×3 |
| S2 lần 2 | currencyservice / crash | checkoutservice / **pod_kill** ×3 | giữ nguyên ×3 |
| S4 lần 1 | frontend / resource_exhaustion | **giữ nguyên** ×3 | không có nhóm này |
| S4 lần 2 | frontend / resource_exhaustion | frontend / **latency**, no_action ×3 | giữ nguyên ×3 |
| S5 lần 1 | productcatalogservice / resource_exhaustion | frontend / latency ×3 | không có nhóm này |
| S5 lần 2 | productcatalogservice / latency | frontend ×2, none ×1 | không có nhóm này |

Nhóm `repeat`: **24/24 lần gọi ra đúng y chẩn đoán gốc**, cả root, loại lỗi lẫn hành động.

**Số tổng (tính trên tổng số lần gọi):**

| | `repeat` | `drop_cited` | `drop_uncited` | necessity | sufficiency_violation | gap |
|---|---|---|---|---|---|---|
| Root đổi (chỉ số chính) | 0/24 | 18/24 = 0,75 | 0/15 | 0,75 | 0 | 0,75 |
| Root hoặc loại lỗi đổi (chỉ số phụ, mình tính tay từ đầu ra) | 0/24 | 21/24 = 0,875 | 0/15 | 0,875 | 0 | 0,875 |

**Sau `drop_cited`, LLM còn thấy gì.** Bản cũ dựng lại đúng prompt đó trên WSL rồi đọc:

| Ca | Còn lại trong prompt | LLM chuyển sang |
|---|---|---|
| S1 | Hai cạnh chậm frontend → checkoutservice và frontend → recommendationservice. LLM chỉ nhắc chúng trong reasoning, nên không vào nhóm nào. Còn cả **productcatalogservice p95 9750 ms** (đã trích, bản cũ không sửa) | checkoutservice / recommendationservice, tức hai service nằm ở đầu hai cạnh chậm còn lại |
| S2 | Pod checkoutservice **"RECREATED 457s ago"**, là nhiễu do ca S3 chạy trước để lại (vấn đề 2, mục 13.5). Còn cả checkoutservice 100% lỗi (đã trích, không sửa) | checkoutservice / **pod_kill**, đúng theo dấu hiệu nhiễu |
| S4 lần 1 | DEVIATIONS "none", CPU "no service is close". Nhưng **frontend p95 4751 ms** (đã trích, không sửa) và adservice 39,4% lỗi vẫn còn | không đổi |
| S5 | DEVIATIONS "none", CPU "none", pod khỏe hết. Chỉ còn **frontend p95 968 / 1796 ms**, là bằng chứng đã trích mà bản cũ không sửa | frontend |

**Đọc kết quả thế nào:**
- **Mức nhiễu nền 0/24 là số tin được.** Ở temperature 0, cùng một prompt cho ra cùng
  một chẩn đoán. Thêm một điều: prompt `repeat` ở bản này bị đảo thứ tự cạnh (mục
  13.7), vậy mà 24/24 vẫn giữ nguyên chẩn đoán. Với 8 ca này, lỗi thứ tự không làm đổi
  kết quả.
- **Necessity 0,75 CHƯA dùng làm số báo cáo được.** Lỗi ở mục 13.6 làm lệch kết quả theo
  cả hai chiều:
  - S5: chẩn đoán đổi **vì** bằng chứng đã trích còn sót. LLM bám vào frontend p95 còn
    nằm trong prompt. Bản mới sửa cả số đó, nên kết quả có thể khác (ví dụ ra "none").
  - S4 lần 1: chẩn đoán không đổi, nhưng frontend p95 4751 ms, bằng chứng chính đã trích,
    vẫn còn. Không thể kết luận lời giải thích này không trung thực.
- **Sufficiency 0/15 yếu, đúng như đã báo trước ở mục 13.5.** Ở bản cũ, nhóm
  `drop_uncited` chỉ toàn nhiễu "vừa tạo lại", và 3/8 ca không có nhóm này.
- **Chỉ số phụ có tác dụng ngay.** S4 lần 2 giữ root nhưng đổi `resource_exhaustion`
  thành `latency` và bỏ hành động. Tức bằng chứng CPU đúng là thứ gánh loại lỗi và hành
  động. Chỉ số chính (root) không thấy điều này.
- **Một quan sát cần kiểm thêm, chưa phải kết luận:** khi bị bỏ bằng chứng đã trích, LLM
  hầu như không nói "hệ thống khỏe". Chỉ 1/24 lần ra "none". Nó chuyển sang bất thường
  mạnh nhất còn lại, kể cả nhiễu (S2). Ở cả 8 ca, prompt sau khi sửa vẫn còn bất thường,
  nên chưa tách được đây là thói quen của LLM hay chỉ là phản ứng đúng với dữ liệu còn lại.

**Việc lần chạy bản mới sẽ trả lời:**
- S4 lần 1: bỏ thêm frontend p95 thì chẩn đoán có đổi không?
- S5: bỏ thêm frontend p95 thì LLM chuyển sang "none" hay sang chỗ khác?
- S1 lần 2 và S5 lần 2: nhóm `drop_uncited` giờ có một triệu chứng thật (mục 13.6). Bỏ
  nó thì chẩn đoán có giữ nguyên không?

So từng ca giữa bản cũ và bản mới sẽ cho thấy lỗi ở mục 13.6 thực sự làm lệch bao nhiêu.

### 13.9. Việc tiếp

- Chạy E2 bản đã sửa trên WSL: `python scripts/xai_audit.py counterfactual
  data/eval/20261007-065802 --repeats 3`, 66 lần gọi, khoảng 0,17 USD, khoảng 10 phút. Cần
  bạn đồng ý.
- (Tùy chọn) Mang file kết quả bản cũ từ k3s về bằng ConfigMap, để giữ đủ `evidence` của
  từng lần gọi.
- Commit dữ liệu phiên `20261007-065802` cùng các chỗ sửa của mục 13.
- Quyết định có sửa bộ chạy cho vấn đề 2 không, rồi mới thu thêm dữ liệu.
