from __future__ import annotations

from pathlib import Path
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from engines.ingestion.inventory import inventory_pdf_directory

router = APIRouter(prefix="/api/v1/ingestion", tags=["ingestion"])


class InventoryRequest(BaseModel):
    path: str = "data/raw/jee_dataset"
    output_csv: str = "data/inventory/pdf_inventory.csv"


@router.post("/inventory")
def run_inventory(req: InventoryRequest):
    target = Path(req.path)
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")
    records, summary = inventory_pdf_directory(target, output_csv=Path(req.output_csv))
    return {"summary": summary, "sample_records": records[:20]}

