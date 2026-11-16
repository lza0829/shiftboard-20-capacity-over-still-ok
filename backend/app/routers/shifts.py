from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services import handover as svc

router = APIRouter(prefix="/shifts", tags=["班次"])


class CapacityBody(BaseModel):
    inflight_limit: int = Field(..., gt=0, description="在途容量上限（正整数）")


@router.get("")
def get_shifts():
    return svc.list_shifts()


@router.put("/{shift_id}/capacity")
def set_capacity(shift_id: int, body: CapacityBody):
    return svc.set_shift_capacity(shift_id, body.inflight_limit)
