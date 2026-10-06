"""Kiểm soát độ lệch trạng thái giữa lúc kiểm chứng và lúc thi hành.

ĐỐI SÁNH TRẠNG THÁI TRƯỚC THI HÀNH. Agent ra quyết định dựa trên một trạng thái chụp
từ trước: snapshot lúc observe, hoặc trạng thái mà twin chép từ production. Nhánh qua
twin mất khoảng 13 phút giữa lúc chép và lúc áp. Nếu trong lúc đó production đã đổi
— ai đó scale, đổi trần CPU, deploy bản mới — thì phán quyết của twin nói về một
trạng thái không còn tồn tại, và áp hành động lên production là áp mù.

Cách làm: chụp cấu hình lúc kiểm chứng, chụp lại ngay trước khi thi hành, khác nhau
thì KHÔNG thi hành mà quay lại quan sát từ đầu.

So đúng những gì twin chép sang (số bản sao, trần CPU, các biến trong
`COPIED_ENV_KEYS`), cộng thêm image. Cố ý KHÔNG so số pod đang sẵn sàng: con số đó
dao động tự nhiên mỗi khi pod khởi động lại, so nó thì agent bị chặn vô cớ.

Chỉ so các deployment của ứng dụng (`TWIN_DEPLOYMENTS`). Namespace `default` còn
chứa Prometheus, Grafana, Jaeger và collector; chúng không thuộc hệ thống được
nghiên cứu, và bộ giám sát tự đổi trạng thái không phải lý do để chặn agent.
"""

from __future__ import annotations

from src_thesis.agent.actions import cpu_to_millicores
from src_thesis.agent.twin_manager import COPIED_ENV_KEYS, TWIN_DEPLOYMENTS
from src_thesis.k8s_client import K8sClient


def capture_state(k8s: K8sClient, namespace: str = "default") -> dict[str, dict]:
    """Chụp cấu hình các deployment của ứng dụng, trong một lần gọi API."""
    states = k8s.deployment_states(namespace, env_keys=COPIED_ENV_KEYS)
    return {name: s for name, s in states.items() if name in TWIN_DEPLOYMENTS}


def _same_cpu(a: str | None, b: str | None) -> bool:
    """So CPU theo millicore: Kubernetes chuẩn hóa "0.4" thành "400m"."""
    ma, mb = cpu_to_millicores(a), cpu_to_millicores(b)
    if ma is None or mb is None:
        return ma is None and mb is None
    return abs(ma - mb) < 1e-6


def diff_state(before: dict[str, dict], after: dict[str, dict]) -> list[str]:
    """Liệt kê những chỗ khác nhau giữa hai lần chụp. Rỗng nghĩa là không lệch."""
    out: list[str] = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b is None or a is None:
            out.append(f"{name}: {'moi xuat hien' if b is None else 'bien mat'}")
            continue
        for key in ("replicas", "image"):
            if b[key] != a[key]:
                out.append(f"{name}.{key}: {b[key]} -> {a[key]}")
        for key in ("cpu_limit", "cpu_request"):
            if not _same_cpu(b[key], a[key]):
                out.append(f"{name}.{key}: {b[key]} -> {a[key]}")
        for k in sorted(set(b["env"]) | set(a["env"])):
            if b["env"].get(k) != a["env"].get(k):
                out.append(f"{name}.env.{k}: {b['env'].get(k)} -> {a['env'].get(k)}")
    return out
