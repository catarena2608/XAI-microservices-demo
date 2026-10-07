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
