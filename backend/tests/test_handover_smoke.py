from pathlib import Path
import os
import sqlite3
import sys

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["DATA_DIR"] = str(ROOT / "backend" / "data_test")
os.environ["FIXTURES_DIR"] = str(ROOT / "fixtures")

db_path = Path(os.environ["DATA_DIR"]) / "app.db"
if db_path.exists():
    db_path.unlink()

from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["项目"] == "交班台"


def test_handover_and_reconcile(client):
    shifts = client.get("/api/shifts").json()
    assert len(shifts) >= 2
    batches = client.get("/api/batches", params={"owner_shift_id": 1}).json()
    assert any(b["status"] == "在途" for b in batches)

    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": 1, "to_shift_id": 2},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]
    assert started.json()["status"] == "进行中"

    # 并行交班应被拒绝
    again = client.post(
        "/api/handovers/start",
        json={"from_shift_id": 1, "to_shift_id": 3},
    )
    assert again.status_code == 409

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "已完成"

    after = client.get("/api/batches", params={"owner_shift_id": 1}).json()
    assert all(b["status"] != "在途" or b["owner_shift_id"] != 1 for b in after) or not any(
        b["status"] == "在途" for b in after
    )
    to_batches = client.get("/api/batches", params={"owner_shift_id": 2}).json()
    assert sum(1 for b in to_batches if b["status"] == "在途") >= 4

    reports = client.get("/api/reconcile").json()
    assert reports
    assert reports[0]["一致"] is True


def _inflight(client, shift_id):
    batches = client.get("/api/batches", params={"owner_shift_id": shift_id}).json()
    return sum(1 for b in batches if b["status"] == "在途")


def _sender_with_inflight(client):
    for s in client.get("/api/shifts").json():
        if _inflight(client, s["id"]) > 0:
            return s["id"]
    raise AssertionError("没有在途批次可交班")


def _other_shift(client, exclude):
    for s in client.get("/api/shifts").json():
        if s["id"] != exclude:
            return s["id"]
    raise AssertionError("班次不足")


def test_capacity_config_validation(client):
    receiver = _other_shift(client, _sender_with_inflight(client))
    bad_zero = client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 0})
    assert bad_zero.status_code == 422
    bad_neg = client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": -3})
    assert bad_neg.status_code == 422
    ok = client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 9})
    assert ok.status_code == 200, ok.text
    assert ok.json()["inflight_limit"] == 9
    missing = client.put("/api/shifts/9999/capacity", json={"inflight_limit": 5})
    assert missing.status_code == 404


def test_capacity_reject_zero_transfer(client):
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    n_sender = _inflight(client, sender)
    n_receiver = _inflight(client, receiver)
    assert n_sender >= 2
    # 上限压到 1：当前在途 + 本单键数必然超限
    r = client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 1})
    assert r.status_code == 200

    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]

    prev = client.get(f"/api/handovers/{hid}/precheck").json()
    assert prev["已落库"] is False
    assert prev["裁决"] == "预计拒绝"
    assert prev["当前在途"] + prev["本单键数"] > prev["上限"]

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["status"] == "已拒绝"
    assert "容量超限" in body["reason"]
    # 零过户：双方批次归属保持完成前状态
    assert _inflight(client, sender) == n_sender
    assert _inflight(client, receiver) == n_receiver
    # 裁决依据已固化可查：当前在途/清单数/上限/差值
    rep = client.get(f"/api/handovers/{hid}/precheck").json()
    assert rep["已落库"] is True
    assert rep["裁决"] == "拒绝"
    assert rep["上限"] == 1
    assert rep["差值"] == rep["上限"] - rep["当前在途"] - rep["本单键数"]
    assert rep["差值"] < 0
    one = client.get(f"/api/handovers/{hid}").json()
    assert one["precheck"]["decision"] == "拒绝"
    assert one["precheck"]["reason"]
    # 班次状态已释放，可再开新单
    shifts = {s["id"]: s for s in client.get("/api/shifts").json()}
    assert shifts[sender]["status"] == "值班中"
    assert shifts[receiver]["status"] == "空闲"


def test_capacity_pass_after_raising_limit(client):
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    n_sender = _inflight(client, sender)
    client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 100})

    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]
    prev = client.get(f"/api/handovers/{hid}/precheck").json()
    assert prev["裁决"] == "预计通过"

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "已完成"
    assert _inflight(client, sender) == 0
    rep = client.get(f"/api/handovers/{hid}/precheck").json()
    assert rep["已落库"] is True
    assert rep["裁决"] == "通过"
    reports = client.get("/api/reconcile").json()
    assert reports[0]["handover_id"] == hid
    assert reports[0]["一致"] is True
    assert _inflight(client, receiver) >= n_sender


def test_mid_transfer_anomaly_rolls_back(client):
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 100})
    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]
    victim = client.get(f"/api/handovers/{hid}").json()["items"][0]["id"]
    n_sender = _inflight(client, sender)
    n_receiver = _inflight(client, receiver)

    # 模拟过户前的异常写入：清单内某批被外部改成已结清
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE batches SET status = '已结清' WHERE id = ?", (victim,))
    conn.commit()
    conn.close()

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 409
    # 整单回滚到完成前归属：交班单仍进行中，无任何部分过户
    h = client.get(f"/api/handovers/{hid}").json()
    assert h["status"] == "进行中"
    assert _inflight(client, sender) == n_sender - 1  # victim 被外部结清，其余未动
    assert _inflight(client, receiver) == n_receiver
    assert client.get(f"/api/handovers/{hid}/precheck").json()["已落库"] is False

    # 恢复现场后可正常完成
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE batches SET status = '在途' WHERE id = ?", (victim,))
    conn.commit()
    conn.close()
    done2 = client.post(f"/api/handovers/{hid}/complete")
    assert done2.status_code == 200, done2.text
    assert done2.json()["status"] == "已完成"
    assert _inflight(client, sender) == 0


def test_precheck_numbers_match_batch_inflight(client):
    """预检数字必须与批次表派生的接班方在途数同源，对不上即为旁路。"""
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 100})
    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]
    pre = client.get(f"/api/handovers/{hid}/precheck").json()
    # 预检「当前在途」== 按批次表实时数出的接班方在途
    assert pre["当前在途"] == _inflight(client, receiver)
    # 本单键数 == 清单行数 == 交班方在途批次数
    assert pre["本单键数"] == started.json()["batch_count"]
    assert pre["本单键数"] == _inflight(client, sender)
    assert pre["差值"] == pre["上限"] - pre["当前在途"] - pre["本单键数"]
    # 收尾：完成本单，避免进行中交班阻塞后续测试
    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "已完成"


def test_capacity_verdict_readonly_snapshot_vs_actual(client):
    """容量裁决只读接口：返回预检快照与事后在途实数的对照结构。"""
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    n_receiver = _inflight(client, receiver)
    client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 100})
    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    hid = started.json()["id"]
    n_items = started.json()["batch_count"]

    # 完成前：无快照，对照为 None，事后实数仍可读
    before_v = client.get(f"/api/handovers/{hid}/capacity-verdict")
    assert before_v.status_code == 200, before_v.text
    bv = before_v.json()
    assert bv["预检快照"] is None
    assert bv["对照"] is None
    assert bv["事后实数"]["接班方在途实数"] == n_receiver

    done = client.post(f"/api/handovers/{hid}/complete")
    assert done.status_code == 200, done.text

    v = client.get(f"/api/handovers/{hid}/capacity-verdict").json()
    snap = v["预检快照"]
    assert snap["decision"] == "通过"
    assert snap["current_inflight"] == n_receiver
    assert snap["item_count"] == n_items
    assert snap["capacity_limit"] == 100
    assert snap["headroom"] == 100 - n_receiver - n_items
    # 事后在途实数同样从批次表派生
    assert v["事后实数"]["接班方在途实数"] == _inflight(client, receiver)
    cmp_ = v["对照"]
    assert cmp_["预检预判接班方在途"] == n_receiver + n_items
    assert cmp_["事后接班方在途实数"] == n_receiver + n_items
    assert cmp_["在途差值(事后-预判)"] == 0
    assert cmp_["事后是否超容"] is False

    # 上限事后被调小：快照不可变，对照应标出当前已超容
    client.put(f"/api/shifts/{receiver}/capacity", json={"inflight_limit": 1})
    v2 = client.get(f"/api/handovers/{hid}/capacity-verdict").json()
    assert v2["预检快照"]["capacity_limit"] == 100  # 快照未被改写
    assert v2["事后实数"]["当前上限"] == 1
    assert v2["对照"]["上限是否被改动"] is True
    assert v2["对照"]["事后是否超容"] is True

    assert client.get("/api/handovers/9999/capacity-verdict").status_code == 404


def test_mid_insert_over_capacity_rolls_back_whole_order(client):
    """中途插入导致超容：同一失败闭内整单回滚到完成前归属，零部分过户。"""
    sender = _sender_with_inflight(client)
    receiver = _other_shift(client, sender)
    n_sender = _inflight(client, sender)
    n_receiver = _inflight(client, receiver)
    # 上限恰好等于「当前在途 + 本单键数」：预检贴线通过，
    # 一旦同事务内多出一个在途批次落到接班方，事后复核必超容
    client.put(
        f"/api/shifts/{receiver}/capacity",
        json={"inflight_limit": n_receiver + n_sender},
    )
    started = client.post(
        "/api/handovers/start",
        json={"from_shift_id": sender, "to_shift_id": receiver},
    )
    assert started.status_code == 200, started.text
    hid = started.json()["id"]
    assert client.get(f"/api/handovers/{hid}/precheck").json()["裁决"] == "预计通过"

    # 触发器在过户事务内部、批次归属 UPDATE 发生时插入接班方在途批次，
    # 模拟预检之后、过户之中的中途插入；触发动作与过户同生共死
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TRIGGER trg_intrude_inflight
        BEFORE UPDATE ON batches
        BEGIN
          INSERT INTO batches(biz_key, title, owner_shift_id, status)
          VALUES ('B-INTRUDE-' || NEW.id, '中途插入批次', NEW.owner_shift_id, '在途');
        END
        """
    )
    conn.commit()
    conn.close()

    done = client.post(f"/api/handovers/{hid}/complete")

    conn = sqlite3.connect(db_path)
    conn.execute("DROP TRIGGER trg_intrude_inflight")
    conn.commit()
    conn.close()

    # 整单回滚：409、交班单仍进行中、归属回到完成前、无预检快照落库
    assert done.status_code == 409, done.text
    h = client.get(f"/api/handovers/{hid}").json()
    assert h["status"] == "进行中"
    assert _inflight(client, sender) == n_sender
    assert _inflight(client, receiver) == n_receiver
    assert client.get(f"/api/handovers/{hid}/precheck").json()["已落库"] is False
    v = client.get(f"/api/handovers/{hid}/capacity-verdict").json()
    assert v["预检快照"] is None  # 回滚连预检固化一并撤销
    # 触发插入物随事务回滚，不留残批次
    leftovers = client.get("/api/batches").json()
    assert not any(b["biz_key"].startswith("B-INTRUDE-") for b in leftovers)

    # 触发器摘除后可正常完成
    done2 = client.post(f"/api/handovers/{hid}/complete")
    assert done2.status_code == 200, done2.text
    assert done2.json()["status"] == "已完成"
    assert _inflight(client, sender) == 0
    assert _inflight(client, receiver) == n_receiver + n_sender
