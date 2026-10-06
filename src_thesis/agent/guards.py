"""Kiểm soát độ lệch trạng thái giữa lúc kiểm chứng và lúc thi hành.

File này cài hai trong bốn cơ chế đề cương cam kết: đối sánh trạng thái trước thi
hành, và kiểm tra điều kiện tiên quyết. Cơ chế thứ ba, tự hoàn tác, là node `watch`
và `auto_undo` của `react_loop.py`.

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

KIỂM TRA ĐIỀU KIỆN TIÊN QUYẾT. Mỗi hành động chỉ có nghĩa khi trạng thái hiện tại
thỏa vài điều kiện. Điều kiện đến từ hai nguồn:

  - Do CODE quy định cho từng hành động (`required_preconditions`). Nguồn này đáng tin.
  - Do LLM khai trong trường `preconditions` của mỗi hành động. Đây là chỗ lời giải
    thích của LLM bị đem đối chiếu với cluster thật: LLM nói "service này đang có 1
    bản sao" mà thật ra là 0 thì nó đang lập luận trên một trạng thái sai.

Kiểm trên production TRƯỚC khi dựng twin, nên hành động bất khả thi bị chặn trong
vài giây thay vì sau một chu kỳ twin.
"""

from __future__ import annotations

from src_thesis.agent.actions import ROLLBACK_ENV_KEYS, cpu_to_millicores
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


# ----------------------------------------------------------------------
# DIEU KIEN TIEN QUYET
# ----------------------------------------------------------------------

def required_preconditions(action: str, target: str) -> list[dict]:
    """Điều kiện BẮT BUỘC do code quy định cho từng hành động.

    Mỗi điều kiện chặn một kiểu hành động vô ích đã biết trước:

      restart_pod  replicas >= 1   0 bản sao thì không có pod nào để khởi động lại.
                                   Đúng ca phát hiện 16 (docs/thesis-notes.md): agent
                                   chọn restart_pod cho currencyservice đang ở 0 bản
                                   sao, twin phải dựng, chạy, đo xong mới báo "0/0 pod".
      scale_down   replicas >= 2   dưới 2 thì không giảm được, sàn là MIN_REPLICAS = 1.
      rollback     có biến để gỡ   không có biến nào trong ROLLBACK_ENV_KEYS thì
                                   rollback không làm gì.
    """
    if action == "restart_pod":
        return [{"kind": "replicas_gte", "target": target, "value": "1"}]
    if action == "scale_down":
        return [{"kind": "replicas_gte", "target": target, "value": "2"}]
    if action == "rollback":
        return [{"kind": "env_any_present", "target": target,
                 "value": ",".join(ROLLBACK_ENV_KEYS)}]
    return []


def _as_int(value: str) -> int | None:
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def check_preconditions(k8s: K8sClient, conditions: list[dict],
                        namespace: str = "default") -> list[dict]:
    """Kiểm từng điều kiện trên cluster thật, trong một lần gọi API.

    Trả về từng điều kiện kèm giá trị đọc được (`actual`) và kết luận (`ok`):

      True   đạt
      False  không đạt -> hành động bị chặn
      None   không kiểm được vì giá trị viết sai dạng, ví dụ "mot". Ghi lại nhưng
             KHÔNG chặn: một lỗi viết của LLM không phải bằng chứng hành động sai.
    """
    states = k8s.deployment_states(namespace, env_keys=ROLLBACK_ENV_KEYS)
    out: list[dict] = []
    for c in conditions:
        kind, target, value = c["kind"], c["target"].strip(), str(c["value"]).strip()
        r = {**c, "actual": None, "ok": None, "note": ""}
        s = states.get(target)
        if s is None:
            r.update(ok=False, note=f"khong co deployment '{target}'")
        elif kind in ("replicas_eq", "replicas_gte", "pods_ready_gte"):
            want = _as_int(value)
            r["actual"] = s["ready"] if kind == "pods_ready_gte" else s["replicas"]
            if want is None:
                r["note"] = f"gia tri '{value}' khong phai so nguyen"
            elif kind == "replicas_eq":
                r["ok"] = r["actual"] == want
            else:
                r["ok"] = r["actual"] >= want
        elif kind == "cpu_limit_eq":
            r["actual"] = s["cpu_limit"]
            if cpu_to_millicores(value) is None:
                r["note"] = f"gia tri '{value}' khong phai luong CPU"
            else:
                r["ok"] = _same_cpu(value, s["cpu_limit"])
        elif kind == "env_any_present":
            present = [k for k in value.split(",") if s["env"].get(k) is not None]
            r["actual"] = ",".join(present) or None
            r["ok"] = bool(present)
        else:
            r["note"] = f"khong biet loai dieu kien '{kind}'"
        out.append(r)
    return out


def describe_failed(results: list[dict]) -> list[str]:
    """Các điều kiện không đạt, viết thành câu ngắn để ghi log và nhồi vào prompt."""
    return [f"{r['kind']} {r['value']} on {r['target']} (actual: {r['actual']})"
            + (f" — {r['note']}" if r["note"] else "")
            for r in results if r["ok"] is False]
