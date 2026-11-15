"""Private, explicitly consented financial inventory endpoints."""
from fastapi import APIRouter, Depends, HTTPException, Response

from auth.deps import current_user
from auth.store import User
from financial import inventory as inventory_store
from financial.inventory_schema import InventoryReplacement
from trust import consent

router = APIRouter(prefix="/financial/inventory", tags=["Financial inventory"])


@router.get("")
async def get_inventory(user: User = Depends(current_user)):
    enabled = consent.is_active(user.subject, "financial_profile")
    if enabled:
        items = await inventory_store.list_for(user.id)
    else:
        await inventory_store.forget(user.id)
        items = []
    return {"consent": enabled, "consent_text": consent.required("financial_profile"), "items": items}


@router.put("")
async def replace_inventory(body: InventoryReplacement, user: User = Depends(current_user)):
    if not body.confirmed:
        raise HTTPException(409, {"code": "confirmation_required", "message":
                                  "Review the complete inventory and set confirmed=true to save it."})
    if not consent.is_active(user.subject, "financial_profile"):
        raise HTTPException(403, {"code": "consent_required", "consent": consent.required("financial_profile")})
    items = await inventory_store.replace_for(
        user.id,
        [item.model_dump(exclude_none=True) for item in body.credit_cards],
        [item.model_dump(exclude_none=True) for item in body.loans],
    )
    return {"items": items}


@router.delete("/{item_id}", status_code=204)
async def delete_inventory_item(item_id: str, user: User = Depends(current_user)):
    if not await inventory_store.delete_one(user.id, item_id):
        raise HTTPException(404, "No financial inventory item with that ID belongs to you.")
    return Response(status_code=204)
