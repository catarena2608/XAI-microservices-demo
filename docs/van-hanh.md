# Tắt và mở lại project an toàn

Dùng khi nghỉ tay, hoặc khi cần máy trống RAM để làm việc khác. Cả hệ thống nằm gọn trong **một container Docker duy nhất** tên `boutique-control-plane` — kind chạy toàn bộ Kubernetes bên trong đó. Nên tắt hay bật chỉ là dừng hay chạy lại container đó.

Đo lúc viết file này: WSL chiếm 2.83 GB khi cluster đang chạy đủ 14 pod.

---

## Ba mức tắt, chọn theo nhu cầu

**Mức 1 — Tạm dừng (dùng hằng ngày).** Dừng container, giữ nguyên mọi thứ bên trong. Lấy lại gần hết RAM. Mở lại mất khoảng 2 phút. Đây là mức dùng 95% thời gian.

**Mức 2 — Tạm dừng và trả RAM triệt để.** Như mức 1, cộng thêm tắt Docker Desktop và tắt máy ảo WSL. Lấy lại toàn bộ RAM. Dùng khi sắp làm project khác nặng.

**Mức 3 — Xóa hẳn cluster.** Chỉ dùng khi cần dựng lại từ đầu, ví dụ muốn thêm cổng vào `kind-cluster.yaml`. Lệnh này xóa sạch cluster và toàn bộ Online Boutique đã cài, phải làm lại từ bước 0.3. Đừng chạy nếu chỉ muốn nghỉ tay.

---

## Quy trình TẮT

### Mức 1 và 2

**0. Kiểm tra xem có lỗi nào đang được tiêm không. Bước này quan trọng.**

```powershell
python scripts/inject.py --status
```

Phải ra `Khong co loi nao dang tiem`. Nếu đang có lỗi thì hoàn tác trước khi tắt:

```powershell
python scripts/inject.py --revert
```

Lý do phải làm trước khi tắt: lỗi tiêm vào là thay đổi thật trên cluster, ví dụ hạ số bản chạy về 0 hay đặt biến `EXTRA_LATENCY=6s`. Tắt máy không xóa nó đi. Lần sau bật lên hệ thống vẫn hỏng y nguyên, và nếu cậu quên mất mình đã tiêm gì thì sẽ ngồi gỡ một sự cố do chính mình tạo ra. File `data/runs/active_fault.json` nhớ hộ cậu, nhưng chỉ khi cậu chịu đọc nó.

**1. Đóng mọi cửa sổ `kubectl port-forward` đang mở** bằng `Ctrl` + `C`. Nếu không mở cái nào thì bỏ qua, các cổng 8080, 16686, 8889 đã được đục sẵn từ `kind-cluster.yaml` nên bình thường không cần port-forward.

**2. Dừng container.**

```powershell
docker stop boutique-control-plane
```

Chờ khoảng 15 giây, lệnh in ra tên container là xong.

**Bước này bắt buộc phải làm trước khi thoát Docker Desktop.** Lý do: kind đặt container ở chế độ tự khởi động lại, nên nếu cậu thoát Docker Desktop trong lúc container vẫn đang chạy, lần sau mở Docker Desktop lên nó sẽ tự bật cluster trở lại và âm thầm ăn RAM trong khi cậu đang code project khác. Dừng bằng tay trước thì lần sau nó nằm im.

**3. Kiểm tra đã dừng.**

```powershell
docker ps
```

Thành công khi danh sách trống, không còn dòng `boutique-control-plane`.

### Chỉ mức 2 làm thêm

**4. Thoát Docker Desktop.** Bấm chuột phải biểu tượng cá voi ở khay hệ thống, chọn Quit Docker Desktop.

**5. Tắt máy ảo WSL.**

```powershell
wsl --shutdown
```

Lệnh này tắt toàn bộ máy ảo Linux đang chạy nền. An toàn ở đây vì container đã dừng đúng cách ở bước 2. Nhưng nhớ rằng nếu chạy lệnh này lúc cluster đang hoạt động thì mọi thứ bị cắt đột ngột — không hỏng dữ liệu vĩnh viễn, nhưng có thể để lại pod ở trạng thái lỗi phải sửa tay.

**6. Kiểm tra RAM đã trả về.** Mở Task Manager, tab Details, tìm `vmmemWSL`. Không còn dòng đó nghĩa là đã trả hết.

### Mức 3

Đọc kỹ trước khi chạy: lệnh dưới đây **xóa vĩnh viễn** cluster `boutique` cùng toàn bộ Online Boutique, Jaeger, collector bên trong. Không có bước hoàn tác. Sau khi chạy phải làm lại từ bước 0.2 dựng cluster và 0.3 cài lại ứng dụng, mất khoảng 15 phút kể cả thời gian tải image.

```powershell
kind delete cluster --name boutique
```

---

## Quy trình MỞ LẠI

**1. Mở Docker Desktop** từ Start Menu. Chờ biểu tượng cá voi ở khay hệ thống hết nhấp nháy, khoảng 1 phút.

**2. Chạy lại container.**

```powershell
docker start boutique-control-plane
```

Bước này **bắt buộc phải làm bằng tay**. Mở Docker Desktop không tự bật cluster — đo thật ngày 2026-08-24: sau một đêm, container ở trạng thái `Exited (255) 10 hours ago` và `kubectl` báo `dial tcp 127.0.0.1:49877: connection refused`. Thấy thông báo đó thì gần như chắc chắn là container chưa chạy, kiểm tra bằng:

```powershell
docker ps -a --filter "name=boutique"
```

**3. Chờ các pod sống lại.**

```powershell
kubectl get pods -w
```

Kubernetes phải khởi động lại toàn bộ 14 pod nên mất 2-3 phút. Trong lúc đó sẽ thấy nhiều pod ở `CrashLoopBackOff` hoặc `Error` — bình thường, do các service khởi động không cùng nhịp và cái này chờ cái kia. Chúng tự thử lại và tự khỏi.

Thành công khi đủ 14 dòng `Running` và `1/1`. Thoát chế độ theo dõi bằng `Ctrl` + `C`.

Nếu sau 5 phút vẫn còn pod đỏ, chạy `kubectl describe pod <tên-pod>` rồi đọc mục Events ở cuối.

**3b. Xử lý pod bị `CrashLoopBackOff` sau khi bật lại.**

Chuyện này xảy ra thật và sẽ còn lặp lại. Lúc bật cluster, 14 pod khởi động cùng lúc và tranh nhau CPU. Kiểm tra sức khỏe của Online Boutique đặt `timeoutSeconds: 1`, tức service phải trả lời trong đúng một giây. `recommendationservice` viết bằng Python với trần CPU 200m không kịp, Kubernetes tưởng nó chết nên giết đi tạo lại, rồi lặp mãi thành `CrashLoopBackOff`.

Dấu hiệu trong `kubectl get pods`: cột STATUS là `CrashLoopBackOff` và số RESTARTS tăng dần. Xác nhận đúng nguyên nhân bằng:

```powershell
kubectl describe pod -l app=recommendationservice
```

Ở mục Events phải thấy dòng `Liveness probe failed: timeout ... within 1s`.

Cách sửa: chờ hệ thống lắng khoảng 5 phút rồi xóa pod đó đi, Kubernetes tạo lại trên một hệ thống đã rảnh CPU và nó sống bình thường.

```powershell
kubectl delete pod -l app=recommendationservice
```

Chờ một phút rồi kiểm tra lại, cột RESTARTS phải là 0. Không cần sửa cấu hình gì cả — cố tình giữ nguyên kiểm tra sức khỏe của hệ thống gốc, vì kịch bản lỗi F4 bóp CPU dựa vào chính hành vi này.

**3c. Pod kẹt ở `0/1 Running` hoặc `Unknown` — khác `CrashLoopBackOff`, và hay gặp hơn.**

Đo thật ngày 2026-08-24: sau một đêm tắt máy, bật lại thì **6 trên 14 pod không sẵn sàng**, nhưng không pod nào ở `CrashLoopBackOff`. Chúng ở `0/1 Running` — tức container sống nhưng trượt kiểm tra sẵn sàng — riêng `loadgenerator` ở `Unknown`.

Khác biệt quan trọng: `0/1 Running` **có thể tự khỏi**, `Unknown` thì **không bao giờ tự khỏi**. Sáng đó `currencyservice` tự khỏi sau khoảng một phút, `loadgenerator` thì nằm mãi.

Đừng ngồi đoán pod nào tự khỏi. Chờ khoảng 2 phút rồi xóa hết những pod còn chưa sẵn sàng bằng một lệnh:

```powershell
kubectl get pods --no-headers | Where-Object { ($_ -split '\s+')[1] -ne '1/1' } | ForEach-Object { kubectl delete pod ($_ -split '\s+')[0] }
```

Xóa pod đang khỏe cũng không sao — Kubernetes tạo lại ngay, và không service nào ở đây lưu trạng thái trong pod.

Kiểm tra lại, phải ra 14/14:

```powershell
kubectl get pods
```

**3d. Chờ 6 phút trước khi chạy bất cứ thí nghiệm nào.**

Bắt buộc, không phải cho chắc. Cửa sổ quan sát rộng 5 phút, nên ngay sau khi bật lại, số liệu vẫn còn nguyên vết hỏng lúc khởi động: `checkoutservice -> emailservice` báo 100% lỗi dù mọi thứ đã bình thường.

Chạy thí nghiệm lúc này thì `inject.py` chặn lại vì nền bẩn, và mỗi lần chặn tốn 6 phút thử lại — chờ trước rẻ hơn.

Xác nhận sạch bằng:

```powershell
python scripts/smoke_snapshot.py
```

Phải ra `CONG CHAN PHASE 1: DAT`.

**4. Kiểm tra ba cổng.**

- `http://localhost:8080` — web bán hàng, đặt thử một đơn cho tới màn hình "Your order is complete".
- `http://localhost:16686` — Jaeger, bấm Find Traces phải ra trace mới.
- `http://localhost:8889/metrics` — phải có các dòng `traces_span_metrics_calls_total`.

Đủ ba cái là hệ thống đã sẵn sàng làm việc tiếp.

---

## Cái gì mất, cái gì giữ sau khi tắt mở

**Giữ nguyên:** toàn bộ manifest đã cài, cấu hình collector, ClusterIP của các service, mọi thứ đã `kubectl apply`. Không phải cài lại gì.

**Mất:** toàn bộ trace cũ trong Jaeger, vì Jaeger all-in-one lưu trong RAM (xem `infra/jaeger-all-in-one.yaml`). Metric spanmetrics cũng đếm lại từ 0.

Hệ quả cho các phase sau: **mọi số liệu thí nghiệm phải được ghi ra file JSON trong `data/runs/` ngay trong lúc chạy ca đó**, không được để dữ liệu nằm lại trong Jaeger rồi hôm sau mới lấy. Tắt máy một lần là mất sạch.

---

## Lệnh cứu hộ khi máy quá tải

Xem pod nào ngốn RAM:

```powershell
kubectl top pods
```

Xem container Docker đang dùng bao nhiêu:

```powershell
docker stats --no-stream
```

Giải phóng nhanh namespace twin ở phase 4 (chỉ xóa twin, không đụng hệ thống chính):

```powershell
kubectl delete namespace twin
```

Tắt khẩn cấp toàn bộ khi máy đứng hình:

```powershell
wsl --shutdown
```

---

## Chống Docker tự bật khi khởi động Windows

Nếu thường xuyên làm project khác, tắt chế độ tự chạy: mở Docker Desktop, vào Settings, mục General, bỏ chọn **Start Docker Desktop when you sign in**. Từ đó máy khởi động sẽ không tốn RAM cho Docker cho tới khi cậu tự mở.

Kiểm tra nhanh xem có gì đang chạy nền không:

```powershell
docker ps; wsl --list --running
```

Cả hai đều trống nghĩa là máy đang sạch.
