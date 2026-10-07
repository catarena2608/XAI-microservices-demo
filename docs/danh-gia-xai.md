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
| 5 | E — bộ chẩn đoán bằng luật (`rule_baseline.py`) | Code xong | Mới chạy được trên snapshot khỏe mạnh. **Chưa có snapshot lỗi để chạy** |
| 6 | D — E2 phản thực (`counterfactual.py`) | Code xong | **Chưa chạy**: cần snapshot lỗi, và lệnh này gọi API |
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

Sửa trên **snapshot** rồi dựng lại prompt bằng `rebuild_prompt_text`, không sửa chuỗi văn
bản. Sửa chuỗi thì phần DEVIATIONS và phần OBSERVED CALL GRAPH dễ lệch nhau, và LLM sẽ
phản ứng với sự mâu thuẫn chứ không phải với dữ liệu mới. Phần phản hồi của vòng trước
được gắn lại y nguyên.

**Bắt buộc tắt cache.** Cache trả lại y nguyên kết quả cũ, khi đó nhóm `repeat` luôn ra
0%. `run_case` từ chối chạy nếu reasoner còn bật cache.

**Kiểm chứng tới đâu.** **Chưa chạy**: không có snapshot lỗi. Đã kiểm compile, import,
và đường "không có dữ liệu" của lệnh (báo rõ thiếu gì, mã thoát 1).

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
