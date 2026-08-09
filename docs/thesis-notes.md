# Sổ tay khóa luận

Ghi lại mọi thứ cần cho chương kết quả. Ghi ngay lúc làm, đừng để cuối kỳ nhớ lại.

## Trạng thái nền của hệ thống

Điền sau bước 0.3 và 0.6. Dùng để đối chiếu mỗi lần tiêm lỗi và mỗi lần dựng twin.

- Ngày đo:
- RAM tổng của cluster khi rảnh (`kubectl top pods`):
- RAM từng pod:
- p95 latency luồng đặt hàng khi khỏe mạnh:
- Error rate khi khỏe mạnh:

## Nhật ký từng phase

Mỗi mục ghi: làm gì, tắc ở đâu, sửa thế nào, mất bao lâu.

### Phase 0 — Hạ tầng

### Phase 1 — Quan sát và mô hình hóa

### Phase 2 — Tiêm lỗi

### Phase 3 — XAI

### Phase 4 — Digital Twin

### Phase 5 — ReAct loop

### Phase 6 — Thí nghiệm

## Hạn chế đã biết (đưa vào báo cáo)

- `cartservice` và `adservice` không phát span server, `redis-cart` không nhìn thấy được. Cạnh tới `cartservice` suy ra từ thuộc tính của span client bên `frontend`.
- Online Boutique kiến trúc phẳng, lỗi ít lan nhiều tầng.
- Twin và production không chạy song song, nên MTTR của chế độ twin-verified có cộng thêm thời gian dựng twin.

## Số liệu cuối
