"""
Sales Manager Router
Covers: daily sales, transactions, stock alerts, promotions,
        store KPIs, top products, customer activity, returns.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from schemas.schemas import (
    AlertStatusUpdate,
    CustomerSalesOut,
    PromotionOut,
    SaleItemOut,
    SalesSummary,
    StockAlertOut,
    StoreKPIOut,
    TopProductOut,
    TransactionOut,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# DAILY SALES SUMMARY
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/summary/daily",
    response_model=List[SalesSummary],
    summary="Daily sales summary by store",
    description=(
        "Returns aggregated daily revenue, transaction count and unit volume "
        "for all stores or a specific store. Useful for the morning sales review."
    ),
)
async def daily_sales_summary(
    sale_date: date = Query(..., description="Target date e.g. 2024-10-28"),
    store_id: Optional[int] = Query(None, description="Filter by store. Omit for all."),
    db: AsyncSession = Depends(get_db),
):
    q = """
        SELECT
            s.store_id,
            s.store_name,
            st.sale_date,
            COUNT(st.sale_id)                            AS total_transactions,
            COALESCE(SUM(st.total_amount), 0)            AS total_revenue,
            COALESCE(SUM(si.quantity), 0)                AS total_units_sold,
            CASE WHEN COUNT(st.sale_id) > 0
                 THEN ROUND(SUM(st.total_amount) / COUNT(st.sale_id), 2)
                 ELSE 0 END                              AS avg_transaction_value
        FROM stores s
        LEFT JOIN sales_transactions st
            ON st.store_id = s.store_id
            AND st.sale_date = :sale_date
            AND st.is_returned = B'0'::bit(1)
        LEFT JOIN sales_items si ON si.sale_id = st.sale_id
        WHERE (:store_id IS NULL OR s.store_id = :store_id)
        GROUP BY s.store_id, s.store_name, st.sale_date
        ORDER BY total_revenue DESC
    """
    result = await db.execute(text(q), {"sale_date": sale_date, "store_id": store_id})
    rows = result.mappings().all()
    return [dict(r) | {"sale_date": sale_date} for r in rows]


@router.get(
    "/summary/range",
    response_model=List[SalesSummary],
    summary="Sales summary over a date range",
    description="Aggregated revenue and units for a given date window per store.",
)
async def sales_summary_range(
    date_from: date = Query(...),
    date_to: date = Query(...),
    store_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    if date_from > date_to:
        raise HTTPException(status_code=400, detail="date_from must be <= date_to")
    q = """
        SELECT
            s.store_id,
            s.store_name,
            st.sale_date,
            COUNT(st.sale_id)                AS total_transactions,
            COALESCE(SUM(st.total_amount),0) AS total_revenue,
            COALESCE(SUM(si.quantity),0)     AS total_units_sold,
            CASE WHEN COUNT(st.sale_id)>0
                 THEN ROUND(SUM(st.total_amount)/COUNT(st.sale_id),2)
                 ELSE 0 END                  AS avg_transaction_value
        FROM stores s
        LEFT JOIN sales_transactions st
            ON st.store_id = s.store_id
            AND st.sale_date BETWEEN :df AND :dt
            AND st.is_returned = B'0'::bit(1)
        LEFT JOIN sales_items si ON si.sale_id = st.sale_id
        WHERE (:store_id IS NULL OR s.store_id = :store_id)
        GROUP BY s.store_id, s.store_name, st.sale_date
        ORDER BY s.store_id, st.sale_date
    """
    result = await db.execute(
        text(q), {"df": date_from, "dt": date_to, "store_id": store_id}
    )
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# TRANSACTIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/transactions",
    response_model=List[TransactionOut],
    summary="List sales transactions",
    description=(
        "Paginated list of sales transactions. Filter by store, date range, "
        "payment method, or customer."
    ),
)
async def list_transactions(
    store_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    payment_method: Optional[str] = Query(None),
    customer_id: Optional[int] = Query(None),
    include_returns: bool = Query(False, description="Include return transactions"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    offset = (page - 1) * page_size
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": offset}
    if store_id:
        filters.append("st.store_id = :store_id")
        params["store_id"] = store_id
    if date_from:
        filters.append("st.sale_date >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("st.sale_date <= :date_to")
        params["date_to"] = date_to
    if payment_method:
        filters.append("st.payment_method = :pm")
        params["pm"] = payment_method
    if customer_id:
        filters.append("st.customer_id = :customer_id")
        params["customer_id"] = customer_id
    if not include_returns:
        filters.append("st.is_returned = B'0'::bit(1)")

    where = " AND ".join(filters)
    q = f"""
        SELECT st.*,
               (st.is_returned = B'1'::bit(1)) AS is_returned
        FROM sales_transactions st
        WHERE {where}
        ORDER BY st.sale_date DESC, st.sale_id DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/transactions/{sale_id}",
    response_model=TransactionOut,
    summary="Get single transaction",
)
async def get_transaction(sale_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT st.*, (st.is_returned = B'1'::bit(1)) AS is_returned
        FROM sales_transactions st WHERE st.sale_id = :sid
    """
    result = await db.execute(text(q), {"sid": sale_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Sale {sale_id} not found")
    return dict(row)


@router.get(
    "/transactions/{sale_id}/items",
    response_model=List[SaleItemOut],
    summary="Line items for a transaction",
)
async def get_transaction_items(sale_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT si.*, p.product_name
        FROM sales_items si
        JOIN products p ON p.product_id = si.product_id
        WHERE si.sale_id = :sid
        ORDER BY si.sale_item_id
    """
    result = await db.execute(text(q), {"sid": sale_id})
    rows = result.mappings().all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No items found for sale {sale_id}")
    return [dict(r) for r in rows]


@router.get(
    "/transactions/{sale_id}/returns",
    response_model=List[TransactionOut],
    summary="Return transactions linked to an original sale",
)
async def get_returns_for_sale(sale_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT st.*, (st.is_returned = B'1'::bit(1)) AS is_returned
        FROM sales_transactions st
        WHERE st.original_sale_id = :sid
    """
    result = await db.execute(text(q), {"sid": sale_id})
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# STOCK ALERTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/alerts",
    response_model=List[StockAlertOut],
    summary="List stock alerts",
    description=(
        "Returns active stock alerts. Filter by store, status or alert type. "
        "Ordered by urgency (PENDING first, then by shortfall)."
    ),
)
async def list_stock_alerts(
    store_id: Optional[int] = Query(None),
    alert_status: Optional[str] = Query(None, description="PENDING|ACKNOWLEDGED|RESOLVED"),
    alert_type: Optional[str] = Query(None, description="LOW_STOCK|REORDER_DUE|OVERSTOCK|EXPIRY_NEAR"),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {}
    if store_id:
        filters.append("sa.store_id = :store_id")
        params["store_id"] = store_id
    if alert_status:
        filters.append("sa.alert_status = :alert_status")
        params["alert_status"] = alert_status
    if alert_type:
        filters.append("sa.alert_type = :alert_type")
        params["alert_type"] = alert_type
    where = " AND ".join(filters)
    q = f"""
        SELECT sa.*,
               s.store_name,
               p.product_name
        FROM stock_alerts sa
        JOIN stores s   ON s.store_id   = sa.store_id
        JOIN products p ON p.product_id = sa.product_id
        WHERE {where}
        ORDER BY
            CASE sa.alert_status
                WHEN 'PENDING'      THEN 1
                WHEN 'ACKNOWLEDGED' THEN 2
                ELSE 3 END,
            (sa.threshold_value - sa.current_value) DESC NULLS LAST
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.patch(
    "/alerts/{alert_id}",
    summary="Acknowledge or resolve a stock alert",
    description="Sales manager updates alert status. Resolved alerts require resolution_notes.",
)
async def update_alert_status(
    alert_id: int,
    payload: AlertStatusUpdate,
    db: AsyncSession = Depends(get_db),
):
    if payload.alert_status == "RESOLVED" and not payload.resolution_notes:
        raise HTTPException(
            status_code=422,
            detail="resolution_notes required when resolving an alert",
        )
    resolved_at = "CURRENT_DATE" if payload.alert_status == "RESOLVED" else "NULL"
    q = f"""
        UPDATE stock_alerts
        SET alert_status       = :status,
            resolution_notes   = :notes,
            resolved_at        = CASE WHEN :status = 'RESOLVED' THEN CURRENT_DATE ELSE resolved_at END
        WHERE alert_id = :alert_id
        RETURNING alert_id, alert_status
    """
    result = await db.execute(
        text(q),
        {"status": payload.alert_status, "notes": payload.resolution_notes, "alert_id": alert_id},
    )
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# PROMOTIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/promotions",
    response_model=List[PromotionOut],
    summary="List promotions",
    description="Active promotions or all promotions. Optionally filter by store.",
)
async def list_promotions(
    active_only: bool = Query(True),
    store_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {}
    if active_only:
        filters.append("p.is_active = B'1'::bit(1)")
        filters.append("p.start_date <= CURRENT_DATE AND p.end_date >= CURRENT_DATE")
    if store_id:
        filters.append(
            "EXISTS (SELECT 1 FROM store_promotions sp "
            "WHERE sp.promotion_id = p.promotion_id AND sp.store_id = :store_id "
            "AND sp.is_active = B'1'::bit(1))"
        )
        params["store_id"] = store_id
    where = " AND ".join(filters)
    q = f"""
        SELECT p.*,
               (p.is_active = B'1'::bit(1)) AS is_active
        FROM promotions p
        WHERE {where}
        ORDER BY p.start_date DESC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/promotions/{promotion_id}/stores",
    summary="Stores running a promotion",
)
async def promotion_stores(promotion_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT sp.store_id, s.store_name, s.city,
               (sp.is_active = B'1'::bit(1)) AS is_active,
               sp.created_at
        FROM store_promotions sp
        JOIN stores s ON s.store_id = sp.store_id
        WHERE sp.promotion_id = :pid
        ORDER BY s.store_name
    """
    result = await db.execute(text(q), {"pid": promotion_id})
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# STORE KPIs
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/kpi/{store_id}",
    response_model=StoreKPIOut,
    summary="Store KPI dashboard",
    description=(
        "Key performance indicators for a store over a given period: "
        "revenue, transactions, units, avg daily revenue, top product, return rate."
    ),
)
async def store_kpi(
    store_id: int,
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    q = """
        WITH base AS (
            SELECT st.sale_id, st.total_amount, st.is_returned, si.quantity
            FROM sales_transactions st
            JOIN sales_items si ON si.sale_id = st.sale_id
            WHERE st.store_id = :store_id
              AND st.sale_date BETWEEN :df AND :dt
        ),
        top_product AS (
            SELECT p.product_name, SUM(si2.quantity) AS qty
            FROM sales_transactions st2
            JOIN sales_items si2 ON si2.sale_id = st2.sale_id
            JOIN products p ON p.product_id = si2.product_id
            WHERE st2.store_id = :store_id
              AND st2.sale_date BETWEEN :df AND :dt
              AND st2.is_returned = B'0'::bit(1)
            GROUP BY p.product_name
            ORDER BY qty DESC LIMIT 1
        )
        SELECT
            s.store_id, s.store_name,
            :df  AS period_start,
            :dt  AS period_end,
            COALESCE(SUM(CASE WHEN b.is_returned=B'0'::bit(1) THEN b.total_amount END),0) AS total_revenue,
            COUNT(DISTINCT CASE WHEN b.is_returned=B'0'::bit(1) THEN b.sale_id END)       AS total_transactions,
            COALESCE(SUM(CASE WHEN b.is_returned=B'0'::bit(1) THEN b.quantity END),0)     AS total_units_sold,
            COALESCE(
                ROUND(SUM(CASE WHEN b.is_returned=B'0'::bit(1) THEN b.total_amount END)
                      / NULLIF((:dt - :df + 1), 0), 2), 0)                                AS avg_daily_revenue,
            (SELECT product_name FROM top_product)                                         AS top_product,
            COALESCE(ROUND(
                COUNT(DISTINCT CASE WHEN b.is_returned=B'1'::bit(1) THEN b.sale_id END) * 100.0
                / NULLIF(COUNT(DISTINCT b.sale_id), 0), 2), 0)                            AS return_rate_pct
        FROM stores s
        LEFT JOIN base b ON TRUE
        WHERE s.store_id = :store_id
        GROUP BY s.store_id, s.store_name
    """
    result = await db.execute(
        text(q), {"store_id": store_id, "df": date_from, "dt": date_to}
    )
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Store {store_id} not found")
    return dict(row)


@router.get(
    "/top-products",
    response_model=List[TopProductOut],
    summary="Top selling products",
    description="Ranked by revenue or units sold over the given period.",
)
async def top_products(
    date_from: date = Query(...),
    date_to: date = Query(...),
    store_id: Optional[int] = Query(None),
    rank_by: str = Query("revenue", pattern="^(revenue|units)$"),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    order = "total_revenue" if rank_by == "revenue" else "total_quantity_sold"
    params = {"df": date_from, "dt": date_to, "limit": limit}
    store_filter = ""
    if store_id:
        store_filter = "AND st.store_id = :store_id"
        params["store_id"] = store_id
    q = f"""
        SELECT p.product_id, p.product_name,
               pc.category_name,
               SUM(si.quantity)    AS total_quantity_sold,
               SUM(si.total_price) AS total_revenue,
               COUNT(DISTINCT st.sale_id) AS transaction_count
        FROM sales_transactions st
        JOIN sales_items si ON si.sale_id = st.sale_id
        JOIN products p     ON p.product_id = si.product_id
        JOIN product_categories pc ON pc.category_id = p.category_id
        WHERE st.sale_date BETWEEN :df AND :dt
          AND st.is_returned = B'0'::bit(1)
          {store_filter}
        GROUP BY p.product_id, p.product_name, pc.category_name
        ORDER BY {order} DESC
        LIMIT :limit
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/customers/activity",
    response_model=List[CustomerSalesOut],
    summary="Customer purchase activity",
    description="Customers ranked by spend. Useful for loyalty tier review.",
)
async def customer_activity(
    store_id: Optional[int] = Query(None),
    customer_type: Optional[str] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = ["c.is_active = B'1'::bit(1)"]
    params: dict = {"limit": limit}
    if store_id:
        filters.append("st.store_id = :store_id")
        params["store_id"] = store_id
    if customer_type:
        filters.append("c.customer_type = :ctype")
        params["ctype"] = customer_type
    if date_from:
        filters.append("st.sale_date >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("st.sale_date <= :dt")
        params["dt"] = date_to
    where = " AND ".join(filters)
    q = f"""
        SELECT c.customer_id,
               c.first_name || ' ' || c.last_name AS customer_name,
               c.customer_type,
               c.loyalty_points,
               c.total_purchases,
               c.last_purchase_date,
               COUNT(DISTINCT st.sale_id) AS transaction_count
        FROM customers c
        LEFT JOIN sales_transactions st
            ON st.customer_id = c.customer_id
            AND st.is_returned = B'0'::bit(1)
        WHERE {where}
        GROUP BY c.customer_id, customer_name, c.customer_type,
                 c.loyalty_points, c.total_purchases, c.last_purchase_date
        ORDER BY c.total_purchases DESC
        LIMIT :limit
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]
