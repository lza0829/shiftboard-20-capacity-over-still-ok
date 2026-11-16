from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import handover as svc

router = APIRouter(prefix="/handovers", tags=["交班"])


class StartBody(BaseModel):
    from_shift_id: int = Field(..., description="交班班次")
    to_shift_id: int = Field(..., description="接班班次")


@router.get("")
def get_handovers():
    return svc.list_handovers()


@router.get("/prechecks")
def get_prechecks():
    return svc.list_prechecks()


@router.get("/{handover_id}")
def get_one(handover_id: int):
    return svc.get_handover(handover_id)


@router.get("/{handover_id}/precheck")
def get_precheck(handover_id: int):
    return svc.precheck_handover(handover_id)


@router.get("/{handover_id}/capacity-verdict")
def get_capacity_verdict(handover_id: int):
    return svc.capacity_verdict(handover_id)


@router.post("/start")
def start(body: StartBody):
    return svc.start_handover(body.from_shift_id, body.to_shift_id)


@router.post("/{handover_id}/complete")
def complete(handover_id: int):
    return svc.complete_handover(handover_id)
