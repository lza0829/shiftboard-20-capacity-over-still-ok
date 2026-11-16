from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException

from app.db import connect, rows_to_dicts


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _inflight_count(conn, shift_id: int) -> int:
    # 在途数一律从批次表同源派生；禁止另起容量计数器冒充批次表
    return conn.execute(
        "SELECT COUNT(*) AS c FROM batches WHERE owner_shift_id = ? AND status = '在途'",
        (shift_id,),
    ).fetchone()["c"]


def list_shifts() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM batches b
                     WHERE b.owner_shift_id = s.id AND b.status = '在途') AS inflight
            FROM shifts s
            ORDER BY s.id
            """
        ).fetchall()
        return rows_to_dicts(rows)


def set_shift_capacity(shift_id: int, inflight_limit: int) -> dict:
    if not isinstance(inflight_limit, int) or isinstance(inflight_limit, bool) or inflight_limit <= 0:
        raise HTTPException(400, "在途容量上限必须是正整数")
    with connect() as conn:
        cur = conn.execute(
            "UPDATE shifts SET inflight_limit = ? WHERE id = ?",
            (inflight_limit, shift_id),
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "班次不存在")
        row = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM batches b
                     WHERE b.owner_shift_id = s.id AND b.status = '在途') AS inflight
            FROM shifts s
            WHERE s.id = ?
            """,
            (shift_id,),
        ).fetchone()
        return dict(row)


def list_batches(owner_shift_id: int | None = None) -> list[dict]:
    with connect() as conn:
        if owner_shift_id is None:
            rows = conn.execute(
                """
                SELECT b.*, s.name AS owner_shift_name
                FROM batches b
                LEFT JOIN shifts s ON s.id = b.owner_shift_id
                ORDER BY b.id
                """
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT b.*, s.name AS owner_shift_name
                FROM batches b
                LEFT JOIN shifts s ON s.id = b.owner_shift_id
                WHERE b.owner_shift_id = ?
                ORDER BY b.id
                """,
                (owner_shift_id,),
            ).fetchall()
        return rows_to_dicts(rows)


def list_handovers() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT h.*,
                   fs.name AS from_shift_name,
                   ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts fs ON fs.id = h.from_shift_id
            JOIN shifts ts ON ts.id = h.to_shift_id
            ORDER BY h.id DESC
            """
        ).fetchall()
        return rows_to_dicts(rows)


def get_handover(handover_id: int) -> dict:
    with connect() as conn:
        h = conn.execute(
            """
            SELECT h.*,
                   fs.name AS from_shift_name,
                   ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts fs ON fs.id = h.from_shift_id
            JOIN shifts ts ON ts.id = h.to_shift_id
            WHERE h.id = ?
            """,
            (handover_id,),
        ).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        items = conn.execute(
            """
            SELECT b.*
            FROM handover_items hi
            JOIN batches b ON b.id = hi.batch_id
            WHERE hi.handover_id = ?
            ORDER BY b.id
            """,
            (handover_id,),
        ).fetchall()
        out = dict(h)
        out["items"] = rows_to_dicts(items)
        pre = conn.execute(
            "SELECT * FROM capacity_prechecks WHERE handover_id = ?",
            (handover_id,),
        ).fetchone()
        out["precheck"] = dict(pre) if pre else None
        return out


def precheck_handover(handover_id: int) -> dict:
    """容量预检：已落库则返回裁决报告，否则按当前批次表现算实时预览。"""
    with connect() as conn:
        h = conn.execute(
            """
            SELECT h.*, ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts ts ON ts.id = h.to_shift_id
            WHERE h.id = ?
            """,
            (handover_id,),
        ).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        persisted = conn.execute(
            "SELECT * FROM capacity_prechecks WHERE handover_id = ?",
            (handover_id,),
        ).fetchone()
        if persisted:
            p = dict(persisted)
            return {
                "handover_id": handover_id,
                "to_shift_id": h["to_shift_id"],
                "to_shift_name": h["to_shift_name"],
                "当前在途": p["current_inflight"],
                "本单键数": p["item_count"],
                "上限": p["capacity_limit"],
                "差值": p["headroom"],
                "裁决": p["decision"],
                "原因": p["reason"],
                "已落库": True,
            }
        limit = conn.execute(
            "SELECT inflight_limit FROM shifts WHERE id = ?",
            (h["to_shift_id"],),
        ).fetchone()["inflight_limit"]
        current = _inflight_count(conn, h["to_shift_id"])
        items = conn.execute(
            "SELECT COUNT(*) AS c FROM handover_items WHERE handover_id = ?",
            (handover_id,),
        ).fetchone()["c"]
        headroom = limit - current - items
        return {
            "handover_id": handover_id,
            "to_shift_id": h["to_shift_id"],
            "to_shift_name": h["to_shift_name"],
            "当前在途": current,
            "本单键数": items,
            "上限": limit,
            "差值": headroom,
            "裁决": "预计通过" if headroom >= 0 else "预计拒绝",
            "原因": "",
            "已落库": False,
        }


def capacity_verdict(handover_id: int) -> dict:
    """容量裁决只读接口（按交班单 id）：预检快照与事后在途实数对照。

    预检快照取自 capacity_prechecks（完成时同事务固化），事后实数一律从
    批次表同源派生；本接口只读，不写任何容量计数器。
    """
    with connect() as conn:
        h = conn.execute(
            """
            SELECT h.*, ts.name AS to_shift_name
            FROM handovers h
            JOIN shifts ts ON ts.id = h.to_shift_id
            WHERE h.id = ?
            """,
            (handover_id,),
        ).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        pre_row = conn.execute(
            "SELECT * FROM capacity_prechecks WHERE handover_id = ?",
            (handover_id,),
        ).fetchone()
        limit = conn.execute(
            "SELECT inflight_limit FROM shifts WHERE id = ?",
            (h["to_shift_id"],),
        ).fetchone()["inflight_limit"]
        # 事后在途实数：与班次/预检预览同一条批次表派生口径
        actual_inflight = _inflight_count(conn, h["to_shift_id"])
        snapshot = dict(pre_row) if pre_row else None
        actual = {
            "接班方在途实数": actual_inflight,
            "当前上限": limit,
            "剩余差值": limit - actual_inflight,
        }
        comparison = None
        if snapshot:
            comparison = {
                "预检当时在途": snapshot["current_inflight"],
                "预检本单键数": snapshot["item_count"],
                "预检预判接班方在途": snapshot["current_inflight"] + snapshot["item_count"],
                "事后接班方在途实数": actual_inflight,
                "在途差值(事后-预判)": actual_inflight
                - (snapshot["current_inflight"] + snapshot["item_count"]),
                "预检上限": snapshot["capacity_limit"],
                "当前上限": limit,
                "上限是否被改动": snapshot["capacity_limit"] != limit,
                "事后是否超容": actual_inflight > limit,
            }
        return {
            "handover_id": handover_id,
            "交班单状态": h["status"],
            "to_shift_id": h["to_shift_id"],
            "to_shift_name": h["to_shift_name"],
            "预检快照": snapshot,
            "事后实数": actual,
            "对照": comparison,
        }


def list_prechecks() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT p.*, s.name AS to_shift_name
            FROM capacity_prechecks p
            JOIN shifts s ON s.id = p.to_shift_id
            ORDER BY p.id DESC
            """
        ).fetchall()
        return rows_to_dicts(rows)


def dashboard() -> dict:
    with connect() as conn:
        shifts = rows_to_dicts(
            conn.execute(
                """
                SELECT s.*,
                       (SELECT COUNT(*) FROM batches b
                         WHERE b.owner_shift_id = s.id AND b.status = '在途') AS inflight
                FROM shifts s
                ORDER BY s.id
                """
            ).fetchall()
        )
        inflight = conn.execute(
            "SELECT COUNT(*) AS c FROM batches WHERE status = '在途'"
        ).fetchone()["c"]
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM handovers WHERE status = '进行中'"
        ).fetchone()["c"]
        last = conn.execute(
            "SELECT * FROM handovers ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return {
            "班次数": len(shifts),
            "在途批次数": inflight,
            "进行中交班": active,
            "最近交班": dict(last) if last else None,
            "班次": shifts,
        }


def start_handover(from_shift_id: int, to_shift_id: int) -> dict:
    if from_shift_id == to_shift_id:
        raise HTTPException(400, "交班双方不能是同一班次")
    with connect() as conn:
        fs = conn.execute("SELECT * FROM shifts WHERE id = ?", (from_shift_id,)).fetchone()
        ts = conn.execute("SELECT * FROM shifts WHERE id = ?", (to_shift_id,)).fetchone()
        if not fs or not ts:
            raise HTTPException(404, "班次不存在")
        active = conn.execute(
            "SELECT id FROM handovers WHERE status = '进行中' LIMIT 1"
        ).fetchone()
        if active:
            raise HTTPException(409, f"已有进行中的交班单#{active['id']}，禁止并行交班")
        batches = conn.execute(
            "SELECT id FROM batches WHERE owner_shift_id = ? AND status = '在途' ORDER BY id",
            (from_shift_id,),
        ).fetchall()
        if not batches:
            raise HTTPException(400, "交班方没有在途批次可交接")
        cur = conn.execute(
            """
            INSERT INTO handovers(from_shift_id, to_shift_id, status, batch_count, started_at)
            VALUES (?, ?, '进行中', ?, ?)
            """,
            (from_shift_id, to_shift_id, len(batches), _now()),
        )
        hid = cur.lastrowid
        for b in batches:
            conn.execute(
                "INSERT INTO handover_items(handover_id, batch_id) VALUES (?, ?)",
                (hid, b["id"]),
            )
        conn.execute("UPDATE shifts SET status = '交班中' WHERE id = ?", (from_shift_id,))
        conn.execute("UPDATE shifts SET status = '接班中' WHERE id = ?", (to_shift_id,))
        conn.commit()
    return get_handover(hid)


def complete_handover(handover_id: int) -> dict:
    conn = connect()
    try:
        # 同一失败闭：BEGIN IMMEDIATE 先拿写锁，预检与过户在同一事务内完成
        conn.execute("BEGIN IMMEDIATE")
        h = conn.execute("SELECT * FROM handovers WHERE id = ?", (handover_id,)).fetchone()
        if not h:
            raise HTTPException(404, "交班单不存在")
        if h["status"] != "进行中":
            raise HTTPException(400, "只能完成进行中的交班单")
        items = conn.execute(
            "SELECT batch_id FROM handover_items WHERE handover_id = ? ORDER BY batch_id",
            (handover_id,),
        ).fetchall()
        before = len(items)
        limit = conn.execute(
            "SELECT inflight_limit FROM shifts WHERE id = ?",
            (h["to_shift_id"],),
        ).fetchone()["inflight_limit"]
        current_to = _inflight_count(conn, h["to_shift_id"])
        headroom = limit - current_to - before
        # 裁决必须按当前在途与本单键数实时算出；禁止写死通过导致超容仍过户
        decision = "通过" if headroom >= 0 else "拒绝"
        reason = "" if decision == "通过" else (
            f"接班方在途容量超限：当前在途{current_to} + 本单{before}键 > 上限{limit}"
            f"（差值{headroom}），整单拒绝、零过户"
        )
        # 容量裁决依据固化可查：独立预检报告表，按交班单 id 落库（与过户同事务）
        conn.execute(
            """
            INSERT INTO capacity_prechecks(
              handover_id, to_shift_id, current_inflight, item_count,
              capacity_limit, headroom, decision, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                handover_id,
                h["to_shift_id"],
                current_to,
                before,
                limit,
                headroom,
                decision,
                reason,
                _now(),
            ),
        )
        if decision == "拒绝":
            # 先拒后改：零过户，禁止先过户再报超容、禁止超容静默成功
            conn.execute(
                "UPDATE handovers SET status = '已拒绝', reason = ?, finished_at = ? WHERE id = ?",
                (reason, _now(), handover_id),
            )
            conn.execute("UPDATE shifts SET status = '值班中' WHERE id = ?", (h["from_shift_id"],))
            conn.execute("UPDATE shifts SET status = '空闲' WHERE id = ?", (h["to_shift_id"],))
            conn.commit()
            return get_handover(handover_id)
        # 裁决通过：同事务内整批过户，禁止只改交班单状态不改归属
        transferred = 0
        for it in items:
            cur = conn.execute(
                "UPDATE batches SET owner_shift_id = ? WHERE id = ? AND status = '在途'",
                (h["to_shift_id"], it["batch_id"]),
            )
            # 每行必须恰好命中一条在途批次；中途被外部结清/删除导致漏过户即判异常
            if cur.rowcount != 1:
                conn.rollback()
                raise HTTPException(
                    409,
                    "过户校验未通过（清单批次缺失或已非在途），已整单回滚到完成前归属",
                )
            transferred += 1
        after_from = _inflight_count(conn, h["from_shift_id"])
        after_to = _inflight_count(conn, h["to_shift_id"])
        # 过户键数须与清单一致，且接班方事后在途恰为预检在途 + 本单键数，
        # 中途插入导致超容或部分过户都过不了这道复核
        consistent = (
            transferred == before
            and after_from == 0
            and after_to == current_to + before
            and after_to <= limit
        )
        if not consistent:
            conn.rollback()
            raise HTTPException(409, "过户校验未通过（归属不一致），已整单回滚到完成前归属")
        conn.execute(
            "UPDATE handovers SET status = '已完成', finished_at = ?, batch_count = ? WHERE id = ?",
            (_now(), before, handover_id),
        )
        conn.execute("UPDATE shifts SET status = '已交班' WHERE id = ?", (h["from_shift_id"],))
        conn.execute("UPDATE shifts SET status = '值班中' WHERE id = ?", (h["to_shift_id"],))
        detail = {
            "交班前在途数": before,
            "交班后交班方在途": after_from,
            "交班后接班方在途": after_to,
            "接班方在途上限": limit,
        }
        conn.execute(
            """
            INSERT INTO reconcile_reports(
              handover_id, before_count, after_from_count, after_to_count,
              consistent, detail_json, created_at
            ) VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (
                handover_id,
                before,
                after_from,
                after_to,
                json.dumps(detail, ensure_ascii=False),
                _now(),
            ),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except sqlite3.Error:
        # 写锁竞争、约束失败等任何数据库异常：整单回滚到完成前归属，禁止留下半截过户
        conn.rollback()
        raise HTTPException(409, "过户事务异常，已整单回滚到完成前归属")
    finally:
        conn.close()
    return get_handover(handover_id)


def list_reconcile() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM reconcile_reports ORDER BY id DESC"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["detail"] = json.loads(d.pop("detail_json"))
            d["一致"] = bool(d.pop("consistent"))
            out.append(d)
        return out
