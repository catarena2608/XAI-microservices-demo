"""Kiểm tra trước khi chạy một ca thí nghiệm, và chờ hệ thống về trạng thái sạch.

VÌ SAO CẦN: phase 6 chạy 75 ca liên tiếp. Nếu một ca bắt đầu khi hệ thống còn dư âm
của ca trước, thì mọi số đo của ca đó lẫn hai lần tiêm — và không có gì báo cho ta
biết điều đó. Số liệu vẫn ra, vẫn đẹp, chỉ là sai.

Hai loại kiểm tra ở đây khác nhau về bản chất:

    `ensure_clean_slate`     — kiểm tra CẤU HÌNH: còn lỗi chưa hoàn tác không, twin
                               còn sống không, mọi deployment có sẵn sàng không
    `wait_for_clean_baseline` — kiểm tra HÀNH VI: số liệu quan sát được có sạch không

Phải qua cả hai. Cấu hình sạch mà hành vi chưa sạch nghĩa là hệ thống đang hồi phục
nhưng cửa sổ quan sát 5 phút vẫn còn giữ dữ liệu lúc hỏng.
"""

from __future__ import annotations

import time
from pathlib import Path

from src_thesis.faults.injectors import load_active_faults
from src_thesis.graph.baseline import find_baseline_file, graph_from_dict
from src_thesis.graph.model import ServiceGraph
from src_thesis.k8s_client import K8sClient
from src_thesis.telemetry.snapshot import SystemSnapshot, take_snapshot

# Nhãn dùng khi lưu ảnh nền mới. Phải nằm trong `BASELINE_LABELS` của
# `src_thesis/graph/baseline.py`, nếu không thì agent sẽ không tìm ra nó.
BASELINE_LABEL = "baseline-clean"

TWIN_NAMESPACE = "twin"


def _log(msg: str, log=None) -> None:
    (log or print)(msg)


def ensure_clean_slate(
    k8s: K8sClient | None = None,
    log=None,
    wait_ready_s: int = 0,
    gap_s: int = 20,
) -> tuple[bool, list[str]]:
    """Kiểm tra cấu hình sạch. Trả về (sạch, danh sách vấn đề).

    KHÔNG tự sửa gì. Một script tự dọn dẹp khi thấy trạng thái lạ là script sẽ
    xóa mất chính bằng chứng của lỗi mà ta cần đọc.

    `wait_ready_s` — chờ tối đa chừng này giây cho pod ĐANG KHỞI ĐỘNG LẠI, và CHỈ
    cho loại vấn đề đó. Chờ không phải là sửa: pod 20 giây tuổi chưa sẵn sàng thì
    trạng thái đúng của nó là "chưa biết", không phải "hỏng".

    VÌ SAO CẦN: ngày 2026-08-30 bộ chạy 15 ca dừng hai lần ở cùng một chỗ. Dọn dẹp
    sau ca S1 gỡ biến EXTRA_LATENCY, Kubernetes tạo lại pod productcatalogservice,
    và ca kế tiếp kiểm ngay lập tức rồi tuyên cả phiên hỏng. Ở chế độ `direct` agent
    còn chồng thêm scale_up hai lần và restart_pod, nên pod càng lâu sẵn sàng. Mọi
    ca S1 và S5 đều sẽ vấp chuyện này.

    Các vấn đề KHÁC — còn lỗi chưa hoàn tác, twin còn sống — thì KHÔNG chờ: thời
    gian không làm chúng tự hết, và chờ chỉ trì hoãn một lỗi thật.
    """
    deadline = time.time() + max(0, wait_ready_s)
    while True:
        blocking, not_ready = _check_once(k8s)
        if not blocking and not not_ready:
            return True, []
        if blocking or time.time() >= deadline:
            problems = list(blocking)
            if not_ready:
                problems.append(
                    f"{len(not_ready)} pod chua san sang: {', '.join(not_ready[:5])}")
            return False, problems
        _log(f"  {len(not_ready)} pod dang khoi dong lai "
             f"({', '.join(not_ready[:3])}), cho {gap_s}s...", log)
        time.sleep(gap_s)


def _check_once(k8s: K8sClient | None = None) -> tuple[list[str], list[str]]:
    """Một lượt kiểm. Trả về (vấn đề KHÔNG chờ được, pod chưa sẵn sàng).

    Tách hai loại ra vì chúng khác bản chất: một loại là trạng thái sai cần người
    xử lý, loại kia là trạng thái tạm thời sẽ tự hết.
    """
    k8s = k8s or K8sClient(namespace="default")
    problems: list[str] = []

    faults = load_active_faults()
    if faults:
        ids = ", ".join(f.ground_truth.fault_id for f in faults)
        problems.append(
            f"con {len(faults)} loi chua hoan tac ({ids}). "
            f"Chay: python scripts/inject.py --revert")

    # Twin sống song song với thí nghiệm production là điều mục 2 KLTN.md cấm:
    # hai môi trường cùng bơm trace vào một collector, và máy chỉ có chừng đó RAM.
    try:
        pods = k8s.list_pods(TWIN_NAMESPACE)
    except Exception:
        pods = []
    if pods:
        problems.append(
            f"namespace '{TWIN_NAMESPACE}' con {len(pods)} pod dang chay. "
            f"Chay: python scripts/twin.py --destroy")

    try:
        prod = k8s.list_pods("default")
    except Exception as e:
        problems.append(f"khong doc duoc pod cua namespace default: {e}")
        return problems, []

    return problems, [p.name for p in prod if not p.ready]


def wait_for_clean_baseline(
    label: str,
    baseline: ServiceGraph | None = None,
    max_tries: int = 6,
    gap_s: int = 60,
    save: bool = True,
    log=None,
) -> SystemSnapshot | None:
    """Chụp ảnh nền, lặp lại cho tới khi diff sạch. Trả về None nếu hết lượt.

    `baseline` là ảnh nền cũ dùng để so. TRUYỀN VÀO thì phép kiểm tra sạch chạy
    đúng độ nhạy mà agent sẽ chạy — bắt được cạnh chậm gấp 3 lần. KHÔNG truyền thì
    chỉ bắt cạnh chậm hơn 500ms tuyệt đối, tức là dễ dãi hơn agent, và ca thí nghiệm
    sẽ bắt đầu trên một hệ thống mà agent coi là đang hỏng.

    Chờ tối đa 6 phút. Vẫn không sạch thì dừng hẳn: lỗi đó là lỗi thật chưa sửa,
    không phải dư âm.
    """
    for i in range(1, max_tries + 1):
        _log(f"  chup anh NEN (lan {i}/{max_tries})...", log)
        snap = take_snapshot(label=label, baseline=baseline)
        if snap.diff.is_clean():
            if save:
                path = snap.save()
                _log(f"  anh nen SACH: {path.name}", log)
            else:
                _log("  anh nen SACH", log)
            return snap

        _log(f"  chua sach: {len(snap.diff.error_edges)} canh loi, "
             f"{len(snap.diff.slow_edges)} canh cham, "
             f"{len(snap.diff.missing_edges)} canh thieu", log)
        for f in (snap.diff.error_edges + snap.diff.slow_edges)[:3]:
            _log(f"    {f.source} -> {f.target}: {f.detail}", log)
        if i < max_tries:
            _log(f"  cho {gap_s}s roi thu lai...", log)
            time.sleep(gap_s)

    _log("", log)
    _log("HE THONG CHUA SACH sau 6 phut cho.", log)
    _log("Day khong phai du am cua ca truoc ma la loi that chua duoc sua.", log)
    _log("Kiem tra: kubectl get pods   va   python scripts/smoke_snapshot.py", log)
    return None


def capture_baseline(log=None) -> tuple[ServiceGraph | None, Path | None]:
    """Chụp một ảnh nền MỚI lúc hệ thống khỏe và lưu lại.

    Gọi một lần ở đầu mỗi phiên chạy 75 ca. Ảnh nền cũ từ phiên trước có thể đã lệch:
    cấu hình đổi, bản vá mới, hoặc đơn giản là máy đang chạy tải khác. Dùng nền cũ
    thì phép so lệch ra kết quả sai lệch về phía báo động giả — và báo động giả
    trong 75 ca thì lẫn vào kết quả không gỡ ra được.

    Ảnh nền đầu tiên chụp KHÔNG có nền để so (chỉ dựa vào topology và ngưỡng tuyệt
    đối), nên nó lỏng hơn. Đây là chỗ không tránh được: phải có một điểm khởi đầu.
    """
    snap = wait_for_clean_baseline(BASELINE_LABEL, baseline=None, save=False, log=log)
    if snap is None:
        return None, None
    path = snap.save()
    _log(f"  nen moi: {path.name} — {len(snap.runtime_graph.edges)} canh, "
         f"{snap.span_count} span", log)
    return snap.runtime_graph, path


def describe_baseline_drift(old: ServiceGraph, new: ServiceGraph) -> tuple[str, bool]:
    """So ảnh nền mới với ảnh nền của phiên trước. Trả về (mô tả, có lệch nhiều không).

    VÌ SAO CẦN: chạy 75 ca chia nhiều ngày thì mỗi ngày chụp một ảnh nền mới. Ảnh
    nền quyết định độ nhạy của phép phát hiện cạnh chậm — chậm gấp 3 lần so với
    CHÍNH CẠNH ĐÓ lúc khỏe. Nền hai ngày lệch nhau nghĩa là ca ngày 1 và ca ngày 2
    được chấm bằng hai cái thước khác nhau.

    Chụp nền mới mỗi ngày vẫn đúng hơn là dùng nền cũ: máy khởi động lại, tải khác,
    độ trễ tuyệt đối đổi theo. Nhưng mức lệch phải NHÌN THẤY ĐƯỢC, không được âm
    thầm. Đây là cùng một nguyên tắc với bài học phase 4: so hai môi trường thì mọi
    biến ngoài biến đang khảo sát phải khớp, và khớp một nửa nguy hiểm hơn không
    khớp gì vì nó tạo cảm giác đã kiểm soát.
    """
    old_edges = set(old.edges)
    new_edges = set(new.edges)
    common = old_edges & new_edges

    lines = [f"  canh: {len(old_edges)} -> {len(new_edges)}, "
             f"chung {len(common)}"]
    gone = old_edges - new_edges
    added = new_edges - old_edges
    if gone:
        lines.append(f"  mat {len(gone)} canh: "
                     + ", ".join(f"{a}->{b}" for a, b in list(gone)[:3]))
    if added:
        lines.append(f"  them {len(added)} canh: "
                     + ", ".join(f"{a}->{b}" for a, b in list(added)[:3]))

    ratios = []
    for key in common:
        o, n = old.edges[key].avg_ms, new.edges[key].avg_ms
        if o > 0 and n > 0:
            ratios.append(n / o)

    big = bool(gone or added)
    if ratios:
        ratios.sort()
        mid = ratios[len(ratios) // 2]
        worst = max(ratios + [1 / r for r in ratios])
        lines.append(f"  do tre trung vi doi {mid:.2f} lan, "
                     f"canh lech nhat {worst:.2f} lan")
        # 1.5 lan la nua duong toi nguong SLOW_RATIO = 3. Vuot muc nay thi nen moi
        # va nen cu da du khac de lam lech ket qua phat hien.
        big = big or mid > 1.5 or mid < 1 / 1.5

    return chr(10).join(lines), big


def compare_with_previous_baseline(new: ServiceGraph, path: Path | None = None,
                                   log=None) -> bool:
    """In mức lệch giữa nền mới và nền của phiên trước. True nghĩa là lệch nhiều.

    `path` phải là ảnh nền TRƯỚC khi chụp nền mới. Bên gọi có trách nhiệm lấy nó
    trước, vì `find_baseline_file()` luôn trả về cái mới nhất — gọi sau khi đã lưu
    nền mới thì nó tự so với chính nó và luôn báo "không lệch gì".
    """
    if path is None:
        path = find_baseline_file()
    if path is None:
        _log("  (chua co anh nen truoc do de so)", log)
        return False
    import json

    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    old = graph_from_dict(d.get("runtime_graph", {}))
    if not old.edges:
        return False

    text, big = describe_baseline_drift(old, new)
    _log(f"  so voi nen truoc ({path.name}):", log)
    for line in text.split(chr(10)):
        _log(line, log)
    if big:
        _log("  CANH BAO: nen moi lech nhieu so voi nen phien truoc.", log)
        _log("  Cac ca chay hom nay duoc cham bang mot thuoc khac cac ca hom truoc.", log)
        _log("  Ghi dieu nay vao phan han che cua chuong ket qua.", log)
    return big
