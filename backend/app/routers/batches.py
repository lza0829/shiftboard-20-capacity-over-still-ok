from fastapi import APIRouter, Query

from app.services import handover as svc

router = APIRouter(prefix="/batches", tags=["在途批次"])


@router.get("")
def get_batches(owner_shift_id: int | None = Query(default=None)):
    return svc.list_batches(owner_shift_id)
