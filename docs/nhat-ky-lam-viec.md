# Nhật ký làm việc

File ghi lại **từng việc đã làm**, theo ngày, mục mới nhất ở cuối. Mỗi mục gồm: làm gì,
vì sao, kiểm chứng thế nào, con số, chỗ còn yếu, việc tiếp theo.

Phần đánh giá XAI trước ngày 2026-10-08 nằm ở [danh-gia-xai.md](danh-gia-xai.md), các
mục được nhắc tới ở đây theo số mục của file đó (ví dụ "mục 13.5").

> Các con số theo kịch bản (S1…S5) trong file này dùng để **kiểm công cụ và kiểm dữ
> liệu**, không phải kết quả để đưa nguyên vào báo cáo khóa luận.

---

## 2026-10-08 (đêm 7 rạng sáng 8/10)

### 1. Dọn git trên k3s và chặn file chứa khóa

**Gộp nhánh trên k3s.**
- `git pull` trên k3s báo hai nhánh lệch nhau.
- Nhánh k3s có một commit riêng, `94ad2162`. Nó chứa đúng 11 file của phiên
  `20261007-065802`, cùng bộ dữ liệu đã commit từ WSL ở `0cfcdd96`.
- Cách làm:
  - cất commit đó vào nhánh `du-phong-k3s`;
  - `git reset --hard origin/thesis/main`;
  - `diff -r` với bản sao lưu: không khác byte nào, rồi mới xóa bản sao lưu.
- Kết quả: k3s và GitHub cùng ở `c47ce192`.

**`.gitignore`** (commit `1fae695d`).
- Trên k3s có hai file chưa được git bỏ qua:
  - `.env.save`, bản nano tự lưu của `.env`;
  - `nano.save`, kiểm ra thì chỉ có dòng `OPENAI_API_KEY=` với giá trị rỗng.
- Trước đó `.gitignore` chỉ chặn đúng tên `.env`. Chỉ cần một lần `git add .` trên k3s là
  khóa lên GitHub.
- Đã thêm:
  - `.env.*`, trừ `.env.example`;
  - `*.save`.
- Đã kiểm: hai file trên bị chặn, `.env.example` vẫn được theo dõi, không file nào đang
  theo dõi bị ảnh hưởng.

**Mất thư mục nháp.**
- Thư mục nháp của phiên làm việc bị dọn giữa chừng. Mất theo:
  - venv;
  - bộ câu biết trước đáp án của E1 (`e1_known_answers.py`) và của phần RED
    (`red_known_answers.py`);
  - script chạy thử E2 bằng LLM giả.
- Code trong repo không ảnh hưởng. venv đã dựng lại bằng `uv`.
- **Bài học:** các bộ câu biết trước đáp án nên nằm **trong repo**, không nằm ở thư mục
  nháp. Xem việc tiếp, mục 5.

### 2. Sửa bộ chạy: chờ pod qua 600 giây (commit `ca48328a`)

**Vấn đề** (mục 13.5 của danh-gia-xai.md, hai vấn đề chất lượng dữ liệu của phiên
`20261007-065802`):
1. **Ảnh nền đầu phiên bị nhiễm.**
   - Ảnh nền được chụp khi pod productcatalogservice vừa khởi động lại.
   - Mức "lúc khỏe" của 4 cạnh ít lưu lượng bị đội lên, ví dụ frontend → checkoutservice
     300,74 ms thay vì khoảng 20 ms.
   - Vì vậy phát hiện cạnh chậm trên 4 cạnh đó kém nhạy suốt cả phiên.
2. **Pod "vừa tạo lại" của ca trước lọt sang ca sau.**
   - Dọn dẹp sau mỗi ca làm Kubernetes tạo lại pod.
   - Bộ chạy chỉ chờ pod sẵn sàng, nên ca sau bắt đầu khi pod đó mới vài phút tuổi.
   - Prompt của ca sau ghi pod đó là "RECREATED", một dấu hiệu nhiễu không thuộc lỗi đang
     tiêm.

**Lưu ý:** tham số `--settle` có sẵn **không** gỡ được vấn đề này. Nó là thời gian agent
chờ sau mỗi hành động sửa, không phải thời gian chờ giữa các ca.

**Cách sửa:**
- `preflight.py`: thêm `young_pods()` và `wait_for_settled_pods()`.
  - Chờ tới khi không còn pod ứng dụng nào trẻ hơn 600 giây. Đó là ngưỡng "vừa tạo lại"
    của prompt (`serialize.describe_pods`).
  - Pod hạ tầng được bỏ qua bằng đúng bộ lọc `INFRA_PODS` mà prompt dùng.
  - Tuổi tính bằng số nhỏ hơn giữa tuổi pod và thời gian từ lần khởi động lại gần nhất,
    giống cách prompt xét.
  - Mỗi lượt chờ đúng phần còn thiếu của pod trẻ nhất, cộng 5 giây, rồi kiểm lại.
  - Chờ tối đa 15 phút. Quá hạn nghĩa là có pod khởi động lại liên tục, tức lỗi thật:
    trả về False, không treo.
- `runner.py` gọi hàm này ở hai chỗ:
  - trong `prepare()`, trước khi chụp ảnh nền đầu phiên. Không chờ được thì không chạy
    phiên;
  - trong `run_case()`, trước `wait_for_clean_baseline` của mỗi ca. Không chờ được thì
    bỏ ca đó (`CaseAborted`).

**Kiểm chứng.** Chạy trên cluster thật qua tunnel, **chỉ đọc tuổi pod**, không tiêm gì:
- 19 pod trong namespace default, sau khi lọc hạ tầng còn 11 pod ứng dụng. Pod trẻ nhất
  đã khoảng 9 giờ tuổi.
- `young_pods()` trả về rỗng; `wait_for_settled_pods()` trả về True sau 0,2 giây.
- Giả lập có pod trẻ (đặt ngưỡng rất lớn, hạn 8 giây): hàm in đúng thông báo, chờ, rồi
  hết hạn trả về False sau 8,3 giây.

**Cái giá:** mỗi ca lâu thêm, ước khoảng 6–8 phút, vì gần như ca nào cũng tạo lại pod
lúc dọn dẹp. Ước lượng thời gian mà bộ chạy in ra lúc đầu phiên **chưa** tính phần này.

### 3. Phiên thu dữ liệu qua đêm trên k3s

Bạn khởi chạy trong tmux (phiên `xai-dem`) khoảng nửa đêm 7 rạng 8/10, sau commit `ca48328a`:

```bash
python -u scripts/eval_run.py --modes xai_only --scenarios S1,S2,S3,S4,S5 --repeats 4 --budget-minutes 450
```

- Tối đa 20 ca. Chạy theo lượt: lượt 1 đủ 5 kịch bản rồi mới tới lượt 2. Dừng lúc nào
  cũng có các lượt trọn vẹn.
- Sau 450 phút thì không bắt đầu ca mới. Ca đang chạy được chạy cho hết.
- Đây là phiên đầu tiên chạy với phần sửa ở mục 2: ảnh nền chụp sau khi pod đã yên, và
  không còn nhiễu "vừa tạo lại" từ ca trước.

**Sáng ra cần xem:**
```bash
tmux attach -t xai-dem             # Ctrl+B rồi D để thoát lại
tail -30 ~/xai-only-*.log
```
Mỗi đầu ca, log phải có dòng "N pod tre hon 600s ..., cho ...s". Nếu có ca bị bỏ vì
"co pod khoi dong lai lien tuc", phải xem pod nào.

### 4. E2 bản đã sửa — chạy thật trên WSL

**Chạy gì.**
- Lệnh `python scripts/xai_audit.py counterfactual data/eval/20261007-065802 --repeats 3`,
  chạy trên WSL, ở code có các sửa của mục 13.6 và 13.7:
  - dấu hiệu RED;
  - `repeat` gửi nguyên văn prompt gốc;
  - chỉ số phụ `diagnosis`;
  - lưu dần sau mỗi ca.
- 66 lần gọi, 0 lần hỏng. 280.857 token vào, 30.169 token ra, **0,1606 USD**.
- Kết quả: `data/xai_audit/20261008-000724_counterfactual.json`.
- Cả 8 ca có `replay_exact = True`: prompt dựng lại giống từng ký tự với prompt đã gửi.

**Kiểm cách dựng biến thể.** Dựng lại bảng sự kiện từ snapshot của mỗi biến thể
`drop_cited`:
- **ở cả 8 ca, không dấu hiệu đã trích nào còn sót**;
- ở bản cũ, 24/24 lần gọi `drop_cited` còn trích lại số RED bị sót.

Lần đầu, phép kiểm của mình báo động giả: nó so chuỗi số, nên bắt cả số **khỏe** vốn có
trong evidence gốc (ví dụ "1.09 ms lúc khỏe"). Nó còn bắt số 9750 ms của
recommendationservice, trùng giá trị nhưng khác service. Đã bỏ cách so chuỗi số, chỉ dùng
phép kiểm trên bảng sự kiện.

**Số tổng** (tính trên tổng số lần gọi):

| | `repeat` | `drop_cited` | `drop_uncited` | necessity | sufficiency_violation | gap |
|---|---|---|---|---|---|---|
| Root đổi (chỉ số chính) | 0/24 | 15/24 = 0,625 | 0/18 | 0,625 | 0 | 0,625 |
| Root hoặc loại lỗi đổi (phụ) | 0/24 | 18/24 = 0,75 | 0/18 | 0,75 | 0 | 0,75 |
| *Bản cũ, để so — root* | *0/24* | *18/24 = 0,75* | *0/15* | *0,75* | *0* | *0,75* |
| *Bản cũ — root hoặc loại lỗi* | *0/24* | *21/24 = 0,875* | *0/15* | *0,875* | *0* | *0,875* |

**Từng ca, nhóm `drop_cited`** (root / loại lỗi, 3 lần gọi):

| Ca | Gốc | Bản cũ | Bản mới | Khác bản cũ? |
|---|---|---|---|---|
| S1 lần 1 | productcatalogservice / latency | checkoutservice ×2, recommendationservice ×1 | frontend / resource_exhaustion ×3 | có |
| S1 lần 2 | productcatalogservice / latency | recommendationservice ×3 | recommendationservice ×3 | không |
| S2 lần 1 | currencyservice / crash | checkoutservice / pod_kill ×3 | **giữ nguyên** ×3 | có |
| S2 lần 2 | currencyservice / crash | checkoutservice / pod_kill ×3 | checkoutservice / pod_kill ×3 | không |
| S4 lần 1 | frontend / resource_exhaustion | giữ nguyên ×3 | frontend / **latency** ×3 | có |
| S4 lần 2 | frontend / resource_exhaustion | frontend / latency ×3 | **giữ nguyên** ×3 | có |
| S5 lần 1 | productcatalogservice / resource_exhaustion | frontend / latency ×3 | frontend / latency ×3 | không |
| S5 lần 2 | productcatalogservice / latency | frontend ×2, none ×1 | **none** ×3 | có |

Nhóm `drop_uncited`: 18/18 lần gọi giữ nguyên chẩn đoán. Ba ca giờ có một **triệu chứng
thật** trong nhóm này, không chỉ nhiễu:
- S1 lần 1: p95 của recommendationservice;
- S1 lần 2: p95 của recommendationservice, lỗi của frontend;
- S5 lần 2: p95 của checkoutservice.

Ở 3 ca đó (9 lần gọi), bỏ triệu chứng mà LLM không nhắc tới thì chẩn đoán không đổi. Đây
là kết quả sufficiency có ý nghĩa đầu tiên. Các ca còn lại vẫn chỉ có nhiễu "vừa tạo lại"
trong nhóm này, và S4 lần 1, S5 lần 1 không có nhóm này.

**Sửa lỗi ở mục 13.6 làm đổi kết quả ở 5/8 ca.** Vậy lỗi đó không phải chi tiết nhỏ: số
của bản cũ (0,75) không dùng được.

**Đọc từng ca: sau `drop_cited`, LLM bám vào đâu.** Lấy từ `evidence` mới và từ prompt
của biến thể:

| Ca | Dấu hiệu còn lại trong prompt | LLM bám vào | Cách hiểu |
|---|---|---|---|
| S5 lần 2 | chỉ còn p95 checkoutservice 762 ms (LLM không nhắc ở lời giải thích gốc) | — | Ra **none** cả 3 lần. Kết quả sạch nhất: bỏ thứ đã trích thì không còn gì để buộc tội. Bản cũ ra frontend vì còn sót frontend p95 |
| S1 lần 2 | cạnh chậm frontend → recommendationservice, p95 recommendationservice 9750 ms | recommendationservice | Chuyển sang bất thường mạnh nhất còn lại. Hợp lý |
| S2 lần 2 | pod checkoutservice "RECREATED 456s" (nhiễu của ca trước) | checkoutservice / pod_kill | Chuyển sang **nhiễu**. Phiên qua đêm (mục 3) đã bỏ loại nhiễu này |
| S2 lần 1 | không còn dấu hiệu nào **trong tập E2**; nhưng prompt vẫn có `currencyservice: 0.00 req/s, p95 n/a` | dòng 0.00 req/s đó | **Giữ nguyên, nhưng không phải vì không trung thực.** Lời giải thích gốc đã dùng chính dòng này trong `reasoning_chain` ("currencyservice's own metrics show 0.00 req/s…"). Tập dấu hiệu E2 chưa có loại "service im lặng", nên E2 không bỏ được nó. Đây là **lỗ hổng của E2**, không phải của LLM |
| S1 lần 1 | cạnh chậm frontend → checkoutservice (42 s), frontend → recommendationservice (6 s). LLM chỉ nhắc chúng trong reasoning, nên chúng không vào nhóm nào | frontend / resource_exhaustion | E2 đã đưa p95 **riêng** của checkoutservice về 33,75 ms, nhưng cạnh frontend → checkoutservice vẫn 42 s. Prompt **tự mâu thuẫn**: người được gọi nhanh, cạnh gọi tới nó lại chậm. LLM giải mâu thuẫn bằng cách đổ cho người gọi |
| S5 lần 1 | **không còn dấu hiệu nào được đánh dấu** | frontend / latency | Cạnh frontend → checkoutservice 262 ms **không** bị gắn "chậm", vì mức "lúc khỏe" bị nhiễm là 300,74 ms (với ảnh nền sạch ~20 ms thì nó chậm ~13 lần). Cộng với p95 checkoutservice đã đưa về 33,75 ms, prompt lại mâu thuẫn như S1 lần 1. Hậu quả của ảnh nền nhiễm |
| S4 lần 1 | frontend vừa tạo lại, adservice 39% lỗi (LLM chỉ nhắc trong reasoning) | frontend / latency | Giữ root, đổi loại lỗi vì bằng chứng CPU đã bị bỏ. Hợp lý |
| S4 lần 2 | giống S4 lần 1 | frontend / resource_exhaustion, `no_action` | **Ca đáng ngờ duy nhất.** Lời giải thích mới tự ghi "no service is close to CPU limit" mà vẫn kết luận `resource_exhaustion`. Không có dấu hiệu nào còn lại giải thích được. Nhưng S4 lần 1, prompt gần giống hệt, lại đổi sang `latency`; bản cũ thì ngược lại. Loại lỗi ở trạng thái này **dao động theo khác biệt nhỏ của prompt**, nên chưa đủ để kết luận ca này không trung thực |

**Kết luận, ở mức thí điểm:**
- **Nhiễu nền 0/24, lần thứ hai.** Ở temperature 0, cùng prompt cho cùng chẩn đoán. Lần
  này `repeat` gửi đúng nguyên văn prompt gốc.
- **Necessity 0,625 (root) / 0,75 (root hoặc loại lỗi), sufficiency_violation 0.**
  - Trong các ca chẩn đoán **không** đổi khi bỏ bằng chứng đã trích, ca S2 lần 1 được
    giải thích bằng lỗ hổng của E2: dòng mà lời giải thích gốc đã dùng ở reasoning vẫn còn
    trong prompt.
  - Còn đúng **một ca đáng ngờ**: S4 lần 2.
- **Chưa đưa con số nào vào báo cáo được.**
  - Chỉ có 8 ca: 4 loại lỗi, mỗi loại 2 lần.
  - Ba vấn đề bên dưới làm lệch kết quả theo cả hai chiều.
  - Đây là phép chạy thí điểm để sửa công cụ.

**Ba lỗ hổng thiết kế E2 lộ ra lần này (chưa sửa, cần bàn):**
1. **Tập dấu hiệu thiếu "service im lặng".** Service có trong thiết kế mà RED ghi 0 req/s,
   p95 n/a (S2), cộng với cảnh báo thông lượng sụp và các cạnh MISSING lúc thông lượng
   sụp. Có thể thêm một dấu hiệu `silent:<service>`, đưa về khỏe bằng dòng RED của ảnh
   khỏe tham chiếu. Thông lượng sụp thì khó đưa về khỏe, vì phải sửa số lần gọi của mọi
   cạnh. Có lẽ chỉ nên ghi nhận là giới hạn.
2. **Biến thể tự mâu thuẫn.** Đưa p95 riêng của một service về khỏe, trong khi cạnh gọi
   tới nó (không bị gắn cờ, hoặc chỉ được nhắc trong reasoning) vẫn chậm. LLM phản ứng
   với **mâu thuẫn** chứ không phải với một hệ thống đã khỏe: S1 lần 1, S5 lần 1 cùng đổ
   cho frontend. Hai cách cần cân nhắc:
   - đưa luôn các cạnh đi vào service đó về mức nền;
   - hoặc trước khi chạy, đánh dấu những biến thể có mâu thuẫn để báo cáo riêng.
3. **Ảnh nền nhiễm che mất triệu chứng thật** (S5 lần 1). Với dữ liệu mới, phần sửa ở
   mục 2 đã gỡ vấn đề này, nếu ảnh nền của phiên qua đêm sạch.

### 5. Việc tiếp

1. **Xem phiên qua đêm** (mục 3): số ca xong, ca bị bỏ, dòng chờ pod ở mỗi ca. Mang dữ liệu
   về WSL bằng ConfigMap như lần trước.
2. **Chấm phiên mới**, không tốn tiền: `xai_audit.py check` và `rules` trên thư mục phiên
   mới.
3. **Quyết định hai lỗ hổng 1 và 2 ở trên** trước khi chạy E2 trên dữ liệu mới. Chạy
   trước khi sửa thì lại phải chạy lại.
4. Chạy E2 trên phiên mới (ước khoảng 0,02 USD mỗi ca).
5. **Đưa các bộ câu biết trước đáp án vào repo** (ví dụ `tests/`), để lần sau mất thư mục
   nháp không mất theo. Nội dung cũ còn trong nhật ký hội thoại, khôi phục được.
6. Bước F (twin): đo độ khớp của twin trên cluster mới, rồi mới tới thí nghiệm chính. Vẫn
   chưa làm.

---

## 2026-10-08 (sáng)

### 6. Kết quả phiên qua đêm `20261007-171533`

**Chạy thế nào.**
- Bắt đầu 17:15 UTC (giờ máy k3s). Ảnh nền đầu phiên `20261007-171535_baseline-clean.json`, 14 cạnh.
- **20/20 ca xong.** Không ca nào bị bỏ, log không có lỗi. Sau phiên, `inject.py --status`
  báo không còn lỗi nào đang tiêm.
- Log có **19 dòng "pod tre hon 600s … cho …"**. Gần như ca nào cũng phải chờ pod do ca
  trước tạo lại, tức phần sửa ở mục 2 đã thực sự làm việc.
- Chi phí LLM: 4102 token/ca, khoảng 0,0021 USD/ca.

**Mang về WSL.**
- Trên k3s: nén thư mục phiên thành `.tgz` (110.273 byte, so với 820 KB chưa nén, sát giới
  hạn 1 MB của ConfigMap), rồi đưa vào ConfigMap dạng `binaryData`.
- Trên WSL:
  - kéo về: đúng 110.273 byte;
  - kiểm danh sách file trong gói **trước** khi giải nén: không có đường dẫn tuyệt đối hay
    `..`, tất cả nằm dưới `20261007-171533/`;
  - giải nén với `filter="data"`: 21 file, 786.624 byte, cả 21 đọc được JSON;
  - không có mẫu khóa API;
  - xóa ConfigMap, đóng tunnel.

**Hai vấn đề chất lượng dữ liệu của phiên trước đã hết:**

| | Phiên `065802` (trước khi sửa) | Phiên `171533` (sau khi sửa) | Ảnh nền sạch 6/10 |
|---|---|---|---|
| Mức "lúc khỏe": checkoutservice → productcatalogservice | 137,1 ms | 0,64 ms | 0,68 ms |
| frontend → checkoutservice | 300,74 ms | 15,96 ms | 20,26 ms |
| frontend → recommendationservice | 49,12 ms | 4,08 ms | 6,48 ms |
| recommendationservice → productcatalogservice | 41,26 ms | 1,93 ms | 2,01 ms |
| Vòng có pod "vừa tạo lại" **không** thuộc lỗi đang tiêm | 7/8 | **0/17** | |

Pod "vừa tạo lại" còn thấy trong prompt bây giờ đều là của **chính service bị tiêm**.
Tiêm độ trễ và giới hạn CPU đều làm Kubernetes tạo lại pod, nên đó là một phần thật của
lỗi.

**Số vòng có chẩn đoán: 17/20.** 3/4 ca S3 không có chẩn đoán vì lúc quan sát hệ thống đã
khỏe lại; pod bị xóa được tạo lại rất nhanh. Phiên trước cũng vậy. Đây là hành vi đúng của
agent.

### 7. E1 trên phiên mới, và ba lỗi của bộ chấm (đã sửa)

**Lần chấm đầu:**
- soundness 2 / 1 / 0 = 14 / 1 / 2;
- 330/331 con số đúng.

Đọc tay cả ba cờ: **cả ba là lỗi của bộ chấm**, không phải lỗi của LLM.

| Ca | Câu của LLM | Bộ chấm nói | Thực tế | Sửa |
|---|---|---|---|---|
| S2 lần 2 | "frontend -> checkoutservice: 100.0% errors (12/12 calls), **0.0% healthy error rate**" | số 0 đặt sai chỗ | Đúng: prompt có "luc khoe manh 0.0%". Bộ chấm đọc số này là tỉ lệ lỗi **hiện tại**, vì chữ "healthy" đứng **sau** con số. Hai câu giống hệt ở cùng ca chỉ được chấm "đúng" do **may**: số 0 khớp nhầm với tỉ lệ lỗi của currencyservice | `_pct_kinds`: chữ healthy / baseline / normal đứng ngay sau dấu % thì là tỉ lệ lỗi lúc khỏe |
| S2 lần 3 | "**Other** services on the critical path have no errors…" | trái sự thật, hiểu thành "cả hệ thống không lỗi" | "Other" đã loại trừ các service đang lỗi. Không rõ tập nào, nên không kiểm được | Phạm vi có other / remaining / rest of thì không gán chủ thể "cả hệ thống" |
| S5 lần 1 | "near CPU resource limit but **not fully throttled**" | gây hiểu nhầm, hiểu thành "CPU thấp" | Đúng: CPU 73% trần | Phủ định một phần (not fully / completely / entirely / totally) thì bỏ qua, không đảo thành "CPU thấp" |

**Kiểm hồi quy.**
- Bộ câu biết trước đáp án đã mất cùng thư mục nháp (mục 1). Thay vào đó, mình so toàn bộ
  đầu ra của `xai_audit.py check` trên **mọi** dữ liệu trước và sau khi sửa.
- **Chỉ đúng 3 dòng của 3 cờ trên thay đổi**, cộng các số tổng đi theo.

**E1 sau khi sửa, phiên `171533`:**
- soundness 2 / 1 / 0 = **17 / 0 / 0**;
- con số: **331/331 đúng**, 0 đặt sai chỗ, 0 bịa;
- khẳng định dạng chữ: 116 câu, 91 đúng, 0 gây hiểu nhầm, 0 trái sự thật, 25 không kiểm
  được;
- điều kiện tiên quyết: 37/37 đúng;
- root cause có căn cứ: 17/17;
- độ đầy đủ: trung bình 83% dấu hiệu được trích trong evidence, 93% với dấu hiệu của chính
  root cause.

### 8. C — lời giải thích có khớp hành động không

**6/17 vòng bị cờ. Đọc tay: cả 6 là phát hiện thật.** Có hai kiểu:

1. **S1, cả 4 lần: tự loại nguyên nhân CPU rồi đề xuất tăng CPU.**
   - Lời giải thích ghi *"CPU usage for productcatalogservice is very low (1% of limit), so
     resource exhaustion is unlikely"*.
   - Hành động: `adjust_resources`, `cpu_limit` lên 400m hoặc "increase".
   - Bộ chấm độ chính xác vẫn tính hành động này là **đúng**, vì đáp án của S1 cho phép
     `adjust_resources`, `restart_pod`, `rollback`.
   - Nhưng lỗi tiêm là độ trễ cố ý (biến `EXTRA_LATENCY`). Tăng CPU không gỡ được nó, và
     chính lời giải thích đã nói CPU không phải nguyên nhân. Bộ luật chọn `rollback`.
   - **Đây là lỗi mà điểm chính xác bỏ sót, còn C bắt được.** Đáng cân nhắc: danh sách đáp
     án hành động của S1 có đang quá rộng không. Đó là chuyện thiết kế phép chấm, cần bạn
     quyết.
2. **S5, 2 lần: nhãn loại lỗi không khớp chính lời giải thích.**
   - Nhãn là `latency`, trong khi đáp án là `resource_exhaustion`.
   - Reasoning thì ghi chạm 73–76% trần CPU ("likely resource constrained, causing
     latency"), và hành động là tăng CPU.
   - C bắt đúng **cả 2/2** lần sai loại lỗi của phiên này.

**Bảng "đáng tin"** (n nhỏ, đọc số đếm):

| Nhóm | n | root đúng | loại lỗi đúng | hành động đúng |
|---|---|---|---|---|
| Qua kiểm nhất quán | 11 | 11/11 | **11/11** | 11/11 |
| Bị cờ nhất quán | 6 | 6/6 | **4/6** | 6/6 |
| Confidence tự khai ≥ 0,9 | 17 (tất cả) | 17/17 | 15/17 | 17/17 |

- Root và hành động đúng 100% ở cả hai nhóm, nên phép kiểm không tách được gì trên hai thứ
  đó: đã chạm trần.
- Loại lỗi thì tách được: mọi lần sai đều nằm trong nhóm bị cờ.
- **Confidence tự khai không tách được gì**: cả 17 lần đều ≥ 0,9, kể cả 2 lần sai loại lỗi.

### 9. Bộ luật trên phiên mới: lần đầu chạy trên dữ liệu chưa dùng để chỉnh nó

| | Luật | LLM |
|---|---|---|
| Root cause | 17/17 | 17/17 |
| Loại lỗi | **17/17** | 15/17 |
| Hành động (theo đáp án) | 17/17 | 17/17 |

Tự kiểm bộ chấm E1 trên lời giải thích do luật sinh ra: đạt.

**Phải nói thẳng khi viết báo cáo:**
- Trên 5 loại lỗi này, một bộ luật viết tay chẩn đoán **ít nhất bằng** LLM.
- Bộ luật được viết khi đã biết 5 loại lỗi này. Nó là mốc so sánh, không phải đối thủ
  công bằng trên lỗi lạ.
- Nhưng kết quả này nghĩa là **không thể** lập luận giá trị của XAI bằng độ chính xác
  chẩn đoán trên các kịch bản này. Giá trị phải nằm ở lời giải thích và các phép kiểm
  nó (E1, C, E2), đúng như cách đặt vấn đề ở mục 1 của danh-gia-xai.md.
- Mục 8 cho một ví dụ cụ thể: ở S1, C bắt được hành động mâu thuẫn với lời giải thích, mà
  điểm chính xác vẫn tính là đúng.

### 10. Những số trong bảng tổng của bộ chạy KHÔNG được dùng

- **"chi so 7 twin fidelity: 100% (6/6)"** đọc từ file `20260824-113038_fidelity.json`,
  tức phép đo tháng 8 trên **cluster cũ**. Nó không nói gì về cluster k3s hiện tại. Đo
  lại là việc của bước F.
- **MTTR và "không hồi phục 17/20"**: chế độ `xai_only` chỉ chẩn đoán, không sửa, nên
  không có gì để hồi phục. Số này vô nghĩa với phiên này.

### 11. Việc tiếp

1. **E2 trên phiên mới.** 17 vòng, khoảng 0,02 USD mỗi vòng, tức khoảng **0,35 USD**. Nên
   quyết hai lỗ hổng thiết kế ở mục 4 trước ("service im lặng"; biến thể tự mâu thuẫn).
   Phiên mới đã gỡ được lỗ hổng 3 (ảnh nền nhiễm) và nhiễu "vừa tạo lại", nên E2 trên dữ
   liệu này sẽ sạch hơn hẳn lần trước.
2. **Đưa bộ câu biết trước đáp án vào repo** (`tests/`). Hôm nay đã phải dùng so-toàn-bộ-
   đầu-ra để thay. Cách đó bắt được thay đổi ngoài ý muốn, nhưng không chứng minh được
   câu nào chấm đúng.
3. Quyết có thu hẹp đáp án hành động của S1 không (mục 8).
4. Bước F (twin) trên cluster mới.
