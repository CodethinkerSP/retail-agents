"""
Supplier Manager Router
Covers: suppliers, purchase orders, replenishment suggestions,
        supplier performance, stock movements, proximity routing.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from schemas.schemas import (
    POCreateRequest,
    POItemOut,
    POStatusUpdate,
    PurchaseOrderOut,
    ReplenishmentSuggestionOut,
    StockMovementOut,
    SupplierOut,
    SupplierPerformanceOut,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# SUPPLIERS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/suppliers",
    response_model=List[SupplierOut],
    summary="List all suppliers",
    description="Returns all suppliers, optionally filtered by active status.",
)
async def list_suppliers(
    active_only: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE is_active = B'1'::bit(1)" if active_only else ""
    q = f"""
        SELECT *,
               (is_active = B'1'::bit(1)) AS is_active
        FROM suppliers
        {where}
        ORDER BY rating DESC NULLS LAST, supplier_name
    """
    result = await db.execute(text(q))
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/suppliers/{supplier_id}",
    response_model=SupplierOut,
    summary="Get supplier detail",
)
async def get_supplier(supplier_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT *, (is_active = B'1'::bit(1)) AS is_active
        FROM suppliers WHERE supplier_id = :sid
    """
    result = await db.execute(text(q), {"sid": supplier_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    return dict(row)


@router.get(
    "/suppliers/{supplier_id}/products",
    summary="Products supplied by a supplier",
    description="All products this supplier can supply, with unit cost and lead time.",
)
async def supplier_products(supplier_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT ps.product_id, p.product_name, p.product_code,
               pc.category_name,
               ps.lead_time_days, ps.unit_cost,
               (ps.is_primary_supplier = B'1'::bit(1)) AS is_primary,
               ps.last_order_date
        FROM product_suppliers ps
        JOIN products p          ON p.product_id  = ps.product_id
        JOIN product_categories pc ON pc.category_id = p.category_id
        WHERE ps.supplier_id = :sid
        ORDER BY pc.category_name, p.product_name
    """
    result = await db.execute(text(q), {"sid": supplier_id})
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/suppliers/{supplier_id}/performance",
    response_model=SupplierPerformanceOut,
    summary="Supplier performance metrics",
    description=(
        "Calculates on-time delivery rate, average lead time, "
        "total order value and PO status breakdown for a supplier."
    ),
)
async def supplier_performance(supplier_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT
            sup.supplier_id,
            sup.supplier_name,
            sup.rating,
            COUNT(po.po_id)                                                  AS total_pos,
            COUNT(po.po_id) FILTER (WHERE po.order_status = 'DELIVERED')     AS delivered_pos,
            COUNT(po.po_id) FILTER (WHERE po.order_status = 'CANCELLED')     AS cancelled_pos,
            COALESCE(ROUND(
                COUNT(po.po_id) FILTER (
                    WHERE po.order_status = 'DELIVERED'
                    AND po.actual_delivery_date <= po.expected_delivery_date
                ) * 100.0
                / NULLIF(COUNT(po.po_id) FILTER (WHERE po.order_status='DELIVERED'),0)
            , 2), 0)                                                          AS on_time_delivery_pct,
            AVG(ps.lead_time_days)                                            AS avg_lead_time_days,
            COALESCE(SUM(po.total_amount), 0)                                AS total_order_value
        FROM suppliers sup
        LEFT JOIN purchase_orders po   ON po.supplier_id = sup.supplier_id
        LEFT JOIN product_suppliers ps ON ps.supplier_id = sup.supplier_id
        WHERE sup.supplier_id = :sid
        GROUP BY sup.supplier_id, sup.supplier_name, sup.rating
    """
    result = await db.execute(text(q), {"sid": supplier_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# PURCHASE ORDERS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/purchase-orders",
    response_model=List[PurchaseOrderOut],
    summary="List purchase orders",
    description="Filterable by store, supplier, status, and date range.",
)
async def list_purchase_orders(
    store_id: Optional[int] = Query(None),
    supplier_id: Optional[int] = Query(None),
    order_status: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if store_id:
        filters.append("po.store_id = :store_id")
        params["store_id"] = store_id
    if supplier_id:
        filters.append("po.supplier_id = :supplier_id")
        params["supplier_id"] = supplier_id
    if order_status:
        filters.append("po.order_status = :order_status")
        params["order_status"] = order_status
    if date_from:
        filters.append("po.order_date >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("po.order_date <= :dt")
        params["dt"] = date_to
    where = " AND ".join(filters)
    q = f"""
        SELECT po.*, s.store_name, sup.supplier_name
        FROM purchase_orders po
        JOIN stores    s   ON s.store_id    = po.store_id
        JOIN suppliers sup ON sup.supplier_id = po.supplier_id
        WHERE {where}
        ORDER BY po.order_date DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/purchase-orders/{po_id}",
    response_model=PurchaseOrderOut,
    summary="Get purchase order detail",
)
async def get_purchase_order(po_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT po.*, s.store_name, sup.supplier_name
        FROM purchase_orders po
        JOIN stores    s   ON s.store_id    = po.store_id
        JOIN suppliers sup ON sup.supplier_id = po.supplier_id
        WHERE po.po_id = :po_id
    """
    result = await db.execute(text(q), {"po_id": po_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"PO {po_id} not found")
    return dict(row)


@router.get(
    "/purchase-orders/{po_id}/items",
    response_model=List[POItemOut],
    summary="Line items of a purchase order",
)
async def get_po_items(po_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT poi.*, p.product_name
        FROM purchase_order_items poi
        JOIN products p ON p.product_id = poi.product_id
        WHERE poi.po_id = :po_id
        ORDER BY poi.po_item_id
    """
    result = await db.execute(text(q), {"po_id": po_id})
    rows = result.mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No items found for PO {po_id}")
    return [dict(r) for r in rows]


@router.patch(
    "/purchase-orders/{po_id}/status",
    summary="Update PO status",
    description=(
        "Transition a PO through its lifecycle: "
        "PENDING → APPROVED → IN_TRANSIT → DELIVERED (or CANCELLED). "
        "actual_delivery_date required when setting DELIVERED."
    ),
)
async def update_po_status(
    po_id: int,
    payload: POStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    if payload.order_status == "DELIVERED" and not payload.actual_delivery_date:
        raise HTTPException(
            status_code=422,
            detail="actual_delivery_date is required when marking DELIVERED",
        )
    q = """
        UPDATE purchase_orders
        SET order_status         = :status,
            actual_delivery_date = COALESCE(:delivery_date, actual_delivery_date),
            notes                = COALESCE(:notes, notes),
            updated_at           = CURRENT_DATE
        WHERE po_id = :po_id
        RETURNING po_id, po_number, order_status, actual_delivery_date
    """
    result = await db.execute(
        text(q),
        {
            "status": payload.order_status,
            "delivery_date": payload.actual_delivery_date,
            "notes": payload.notes,
            "po_id": po_id,
        },
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"PO {po_id} not found")
    return dict(row)


@router.get(
    "/purchase-orders/overdue",
    response_model=List[PurchaseOrderOut],
    summary="Overdue purchase orders",
    description=(
        "IN_TRANSIT or APPROVED POs where expected_delivery_date < today. "
        "Critical for escalation."
    ),
)
async def overdue_purchase_orders(db: AsyncSession = Depends(get_db)):
    q = """
        SELECT po.*, s.store_name, sup.supplier_name
        FROM purchase_orders po
        JOIN stores    s   ON s.store_id     = po.store_id
        JOIN suppliers sup ON sup.supplier_id = po.supplier_id
        WHERE po.order_status IN ('IN_TRANSIT', 'APPROVED')
          AND po.expected_delivery_date < CURRENT_DATE
        ORDER BY po.expected_delivery_date ASC
    """
    result = await db.execute(text(q))
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# REPLENISHMENT SUGGESTIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/replenishment/suggestions",
    response_model=List[ReplenishmentSuggestionOut],
    summary="Replenishment suggestions",
    description=(
        "Products at or below reorder_point, paired with the optimal active supplier "
        "from store_supplier_proximity (nearest + fastest). "
        "Returns urgency: CRITICAL (qty=0), HIGH (below min), MEDIUM (at reorder point)."
    ),
)
async def replenishment_suggestions(
    store_id: Optional[int] = Query(None, description="Filter by store"),
    urgency: Optional[str] = Query(None, pattern="^(CRITICAL|HIGH|MEDIUM)$"),
    db: AsyncSession = Depends(get_db),
):
    store_filter = "AND sl.store_id = :store_id" if store_id else ""
    params: dict = {}
    if store_id:
        params["store_id"] = store_id
    q = f"""
        WITH ranked_suppliers AS (
            SELECT
                ps.product_id,
                ssp.store_id,
                ps.supplier_id,
                sup.supplier_name,
                ps.unit_cost,
                ps.lead_time_days,
                ssp.transportation_cost,
                ssp.estimated_delivery_time_hours,
                ROW_NUMBER() OVER (
                    PARTITION BY ps.product_id, ssp.store_id
                    ORDER BY ssp.estimated_delivery_time_hours ASC, ssp.transportation_cost ASC
                ) AS rn
            FROM product_suppliers ps
            JOIN store_supplier_proximity ssp ON ssp.supplier_id = ps.supplier_id
            JOIN suppliers sup ON sup.supplier_id = ps.supplier_id
            WHERE sup.is_active = B'1'::bit(1)
              AND ps.is_primary_supplier = B'1'::bit(1)
        )
        SELECT
            sl.store_id,
            s.store_name,
            sl.product_id,
            p.product_name,
            sl.quantity           AS current_qty,
            sl.reorder_point,
            p.reorder_quantity,
            rs.supplier_id        AS suggested_supplier_id,
            rs.supplier_name      AS suggested_supplier_name,
            rs.unit_cost          AS estimated_unit_cost,
            rs.lead_time_days     AS estimated_lead_time_days,
            rs.transportation_cost AS estimated_delivery_cost,
            CASE
                WHEN sl.quantity = 0                  THEN 'CRITICAL'
                WHEN sl.quantity < sl.reorder_point   THEN 'HIGH'
                ELSE 'MEDIUM'
            END AS urgency
        FROM stock_levels sl
        JOIN stores   s ON s.store_id   = sl.store_id
        JOIN products p ON p.product_id = sl.product_id
        LEFT JOIN ranked_suppliers rs
            ON rs.product_id = sl.product_id
           AND rs.store_id   = sl.store_id
           AND rs.rn = 1
        WHERE sl.quantity <= sl.reorder_point
          {store_filter}
        ORDER BY
            CASE WHEN sl.quantity=0 THEN 1 WHEN sl.quantity<sl.reorder_point THEN 2 ELSE 3 END,
            (sl.reorder_point - sl.quantity) DESC
    """
    result = await db.execute(text(q), params)
    rows = [dict(r) for r in result.mappings().all()]
    if urgency:
        rows = [r for r in rows if r["urgency"] == urgency]
    return rows


# ─────────────────────────────────────────────────────────────────────────────
# STOCK MOVEMENTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/stock-movements",
    response_model=List[StockMovementOut],
    summary="Stock movement history",
    description=(
        "Full movement ledger. Filter by store, product, movement type or date. "
        "Useful for GRN reconciliation and shrinkage audits."
    ),
)
async def list_stock_movements(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    movement_type: Optional[str] = Query(
        None, description="sale|purchase|adjustment|transfer|return"
    ),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if store_id:
        filters.append("sm.store_id = :store_id")
        params["store_id"] = store_id
    if product_id:
        filters.append("sm.product_id = :product_id")
        params["product_id"] = product_id
    if movement_type:
        filters.append("sm.movement_type = :mt")
        params["mt"] = movement_type
    if date_from:
        filters.append("sm.created_at >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("sm.created_at <= :dt")
        params["dt"] = date_to
    where = " AND ".join(filters)
    q = f"""
        SELECT sm.*, p.product_name
        FROM stock_movements sm
        JOIN products p ON p.product_id = sm.product_id
        WHERE {where}
        ORDER BY sm.created_at DESC, sm.movement_id DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/stock-movements/transfers",
    summary="Inter-store transfer pairs",
    description="Returns matched OUT + IN transfer pairs grouped by transfer_order reference.",
)
async def transfer_pairs(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {}
    date_clause = ""
    if date_from:
        date_clause += " AND sm_out.created_at >= :df"
        params["df"] = date_from
    if date_to:
        date_clause += " AND sm_out.created_at <= :dt"
        params["dt"] = date_to
    q = f"""
        SELECT
            sm_out.reference_id   AS transfer_order_id,
            sm_out.store_id       AS from_store_id,
            s_out.store_name      AS from_store_name,
            sm_in.store_id        AS to_store_id,
            s_in.store_name       AS to_store_name,
            sm_out.product_id,
            p.product_name,
            ABS(sm_out.quantity)  AS quantity_transferred,
            sm_out.created_at     AS dispatch_date,
            sm_in.created_at      AS receipt_date
        FROM stock_movements sm_out
        JOIN stock_movements sm_in
            ON sm_in.reference_id   = sm_out.reference_id
           AND sm_in.reference_type = 'transfer_order'
           AND sm_in.quantity > 0
        JOIN stores   s_out ON s_out.store_id   = sm_out.store_id
        JOIN stores   s_in  ON s_in.store_id    = sm_in.store_id
        JOIN products p     ON p.product_id     = sm_out.product_id
        WHERE sm_out.movement_type = 'transfer'
          AND sm_out.quantity < 0
          AND sm_out.reference_type = 'transfer_order'
          {date_clause}
        ORDER BY sm_out.created_at DESC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/supplier-proximity/{store_id}",
    summary="Supplier proximity for a store",
    description=(
        "Ranked list of suppliers reachable from a store with distance, "
        "transportation mode, cost and estimated delivery time."
    ),
)
async def supplier_proximity(
    store_id: int,
    max_hours: Optional[int] = Query(None, description="Filter by max delivery hours"),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"store_id": store_id}
    hours_filter = ""
    if max_hours:
        hours_filter = "AND ssp.estimated_delivery_time_hours <= :max_hours"
        params["max_hours"] = max_hours
    q = f"""
        SELECT ssp.store_id,
               sup.supplier_id,
               sup.supplier_name,
               sup.rating,
               (sup.is_active = B'1'::bit(1))  AS supplier_active,
               ssp.distance_km,
               ssp.transportation_mode,
               ssp.transportation_cost,
               ssp.estimated_delivery_time_hours
        FROM store_supplier_proximity ssp
        JOIN suppliers sup ON sup.supplier_id = ssp.supplier_id
        WHERE ssp.store_id = :store_id
          {hours_filter}
        ORDER BY ssp.estimated_delivery_time_hours ASC, ssp.transportation_cost ASC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]
