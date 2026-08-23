# XAI + ReAct Agent + Digital Twin cho Microservices

Repo khóa luận. Fork từ [GoogleCloudPlatform/microservices-demo](https://github.com/GoogleCloudPlatform/microservices-demo) (Online Boutique) — hệ thống 11 microservice dùng làm đối tượng nghiên cứu.

## Đọc theo thứ tự

1. [KLTN.md](KLTN.md) — bản giao việc: đề tài, ràng buộc, những thứ không làm, kiến trúc cần xây.
2. [KLTN-PLAN.md](KLTN-PLAN.md) — kế hoạch chia 7 phase, mỗi phase có bước nhỏ và tiêu chí thành công.
3. [docs/van-hanh.md](docs/van-hanh.md) — cách tắt project để trả RAM và cách mở lại. Đọc trước khi nghỉ tay.
4. [docs/thesis-notes.md](docs/thesis-notes.md) — sổ ghi số liệu nền và những phát hiện trong lúc làm.

## Còn lại gì của repo gốc

Đã xóa terraform, helm-chart, istio, CI của Google, docs của Google, và các bản sao manifest trùng lặp. Lấy lại được bằng `git checkout <commit-trước-khi-dọn> -- <đường-dẫn>`.

- `release/kubernetes-manifests.yaml` — file cài Online Boutique, image đã pin ở `v0.10.6`.
- `kustomize/components/google-cloud-operations/` — nguồn của phần vá biến env bật tracing. Bước 0.4 copy từ đây.
- `src/` — mã nguồn 11 service. Chỉ đọc để tra cứu, không sửa. Code khóa luận nằm ở `src_thesis/`.
- `protos/` — định nghĩa gRPC, dùng khi viết `data/logical_topology.yaml`.

## Giấy phép

Mã nguồn gốc theo Apache License 2.0, xem [LICENSE](LICENSE).
