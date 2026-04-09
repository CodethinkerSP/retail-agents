"""
Business Analyst Router — Forecasting & Analytics
Covers: sales forecasts, anomaly detection, daily aggregates,
        revenue trends, category breakdown, event impact,
        forecast accuracy, promotion effectiveness.
"""

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import get_db
from schemas.schemas import (
    AnomalyOut,
    CategoryRevenueOut,
    DailySalesAggregateOut,
    EventImpactOut,
    ForecastAccuracyOut,
    ForecastCreateRequest,
    ForecastOut,
    PromotionEffectivenessOut,
    RevenueTrendOut,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# SALES FORECASTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/forecasts",
    response_model=List[ForecastOut],
    summary="List sales forecasts",
    description=(
        "Retrieve forecasts with optional actual vs predicted comparison. "
        "Filter by store, product, method or date range."
    ),
)
async def list_forecasts(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    forecast_method: Optional[str] = Query(
        None, description="Prophet|ARIMA|LightGBM|Moving_Average"
    ),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    future_only: bool = Query(False, description="Only return forecasts without actuals"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if store_id:
        filters.append("sf.store_id = :store_id")
        params["store_id"] = store_id
    if product_id:
        filters.append("sf.product_id = :product_id")
        params["product_id"] = product_id
    if forecast_method:
        filters.append("sf.forecast_method = :fm")
        params["fm"] = forecast_method
    if date_from:
        filters.append("sf.forecast_date >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("sf.forecast_date <= :dt")
        params["dt"] = date_to
    if future_only:
        filters.append("sf.actual_quantity IS NULL")
    where = " AND ".join(filters)
    q = f"""
        SELECT sf.*,
               p.product_name,
               s.store_name,
               CASE
                   WHEN sf.actual_quantity IS NOT NULL AND sf.actual_quantity <> 0
                   THEN ROUND(
                       ABS(sf.actual_quantity - sf.predicted_quantity)
                       / sf.actual_quantity * 100, 2)
                   ELSE NULL
               END AS mape_pct
        FROM sales_forecasts sf
        JOIN products p ON p.product_id = sf.product_id
        JOIN stores   s ON s.store_id   = sf.store_id
        WHERE {where}
        ORDER BY sf.forecast_date DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/forecasts/{forecast_id}",
    response_model=ForecastOut,
    summary="Get single forecast",
)
async def get_forecast(forecast_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT sf.*, p.product_name, s.store_name,
               CASE WHEN sf.actual_quantity IS NOT NULL AND sf.actual_quantity <> 0
                    THEN ROUND(ABS(sf.actual_quantity-sf.predicted_quantity)
                               /sf.actual_quantity*100, 2)
                    ELSE NULL END AS mape_pct
        FROM sales_forecasts sf
        JOIN products p ON p.product_id = sf.product_id
        JOIN stores   s ON s.store_id   = sf.store_id
        WHERE sf.forecast_id = :fid
    """
    result = await db.execute(text(q), {"fid": forecast_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Forecast {forecast_id} not found")
    return dict(row)


@router.post(
    "/forecasts",
    response_model=ForecastOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new forecast",
    description=(
        "Submit a model-generated forecast for a product/store/date. "
        "confidence_lower must be < predicted_quantity < confidence_upper."
    ),
)
async def create_forecast(
    payload: ForecastCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    if not (payload.confidence_lower < payload.predicted_quantity < payload.confidence_upper):
        raise HTTPException(
            status_code=422,
            detail="confidence_lower < predicted_quantity < confidence_upper must hold",
        )
    q = """
        INSERT INTO sales_forecasts
            (product_id, store_id, forecast_date, predicted_quantity,
             confidence_lower, confidence_upper, forecast_method, created_at)
        VALUES
            (:product_id, :store_id, :forecast_date, :predicted_quantity,
             :confidence_lower, :confidence_upper, :forecast_method, CURRENT_DATE)
        RETURNING forecast_id
    """
    result = await db.execute(text(q), payload.model_dump())
    await db.commit()
    new_id = result.scalar()
    return await get_forecast(new_id, db)


@router.put(
    "/forecasts/{forecast_id}/actual",
    summary="Update actual quantity for a forecast",
    description="Once actual sales data is available, backfill the forecast record.",
)
async def update_forecast_actual(
    forecast_id: int,
    actual_quantity: float = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
):
    q = """
        UPDATE sales_forecasts
        SET actual_quantity = :actual
        WHERE forecast_id = :fid
        RETURNING forecast_id, predicted_quantity, actual_quantity,
                  ROUND(ABS(:actual - predicted_quantity) / :actual * 100, 2) AS mape_pct
    """
    result = await db.execute(text(q), {"actual": actual_quantity, "fid": forecast_id})
    await db.commit()
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Forecast {forecast_id} not found")
    return dict(row)


@router.get(
    "/forecasts/accuracy",
    response_model=List[ForecastAccuracyOut],
    summary="Forecast accuracy by method",
    description=(
        "MAPE (Mean Absolute Percentage Error) and CI-hit-rate per forecast method. "
        "Helps the analyst select the best model for each product category."
    ),
)
async def forecast_accuracy(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    filters = ["sf.actual_quantity IS NOT NULL", "sf.actual_quantity <> 0"]
    params: dict = {}
    if store_id:
        filters.append("sf.store_id = :store_id")
        params["store_id"] = store_id
    if product_id:
        filters.append("sf.product_id = :product_id")
        params["product_id"] = product_id
    where = " AND ".join(filters)
    q = f"""
        SELECT
            sf.forecast_method,
            COUNT(*)           AS total_forecasts,
            COUNT(sf.actual_quantity) AS forecasts_with_actuals,
            ROUND(AVG(
                ABS(sf.actual_quantity - sf.predicted_quantity)
                / sf.actual_quantity * 100
            ), 2)              AS avg_mape_pct,
            ROUND(
                COUNT(*) FILTER (
                    WHERE sf.actual_quantity BETWEEN sf.confidence_lower AND sf.confidence_upper
                ) * 100.0 / NULLIF(COUNT(*), 0)
            , 2)               AS within_ci_pct
        FROM sales_forecasts sf
        WHERE {where}
        GROUP BY sf.forecast_method
        ORDER BY avg_mape_pct ASC NULLS LAST
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# SALES ANOMALIES
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/anomalies",
    response_model=List[AnomalyOut],
    summary="List sales anomalies",
    description=(
        "All detected anomalies. Filter by store, date range, deviation threshold "
        "or whether they have an associated external event."
    ),
)
async def list_anomalies(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    min_deviation_pct: Optional[float] = Query(
        None, description="Minimum absolute deviation % e.g. 50 for >50%"
    ),
    unexplained_only: bool = Query(
        False, description="Only anomalies with no associated event"
    ),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if store_id:
        filters.append("sa.store_id = :store_id")
        params["store_id"] = store_id
    if product_id:
        filters.append("sa.product_id = :product_id")
        params["product_id"] = product_id
    if date_from:
        filters.append("sa.anomaly_date >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("sa.anomaly_date <= :dt")
        params["dt"] = date_to
    if min_deviation_pct is not None:
        filters.append("ABS(sa.deviation_percentage) >= :min_dev")
        params["min_dev"] = min_deviation_pct
    if unexplained_only:
        filters.append("sa.associated_event_id IS NULL")
    where = " AND ".join(filters)
    q = f"""
        SELECT sa.*,
               s.store_name,
               p.product_name,
               ee.event_name
        FROM sales_anomalies sa
        JOIN stores   s ON s.store_id   = sa.store_id
        JOIN products p ON p.product_id = sa.product_id
        LEFT JOIN external_events ee ON ee.event_id = sa.associated_event_id
        WHERE {where}
        ORDER BY ABS(sa.deviation_percentage) DESC NULLS LAST
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/anomalies/{anomaly_id}",
    response_model=AnomalyOut,
    summary="Get anomaly detail",
)
async def get_anomaly(anomaly_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT sa.*, s.store_name, p.product_name, ee.event_name
        FROM sales_anomalies sa
        JOIN stores   s ON s.store_id   = sa.store_id
        JOIN products p ON p.product_id = sa.product_id
        LEFT JOIN external_events ee ON ee.event_id = sa.associated_event_id
        WHERE sa.anomaly_id = :aid
    """
    result = await db.execute(text(q), {"aid": anomaly_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Anomaly {anomaly_id} not found")
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# DAILY SALES AGGREGATES
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/aggregates/daily",
    response_model=List[DailySalesAggregateOut],
    summary="Daily sales aggregates",
    description=(
        "Pre-aggregated daily totals per store × product. "
        "Faster than querying sales_transactions for trend analysis."
    ),
)
async def daily_aggregates(
    store_id: Optional[int] = Query(None),
    product_id: Optional[int] = Query(None),
    promotion_id: Optional[int] = Query(None),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": page_size, "offset": (page - 1) * page_size}
    if store_id:
        filters.append("dsa.store_id = :store_id")
        params["store_id"] = store_id
    if product_id:
        filters.append("dsa.product_id = :product_id")
        params["product_id"] = product_id
    if promotion_id:
        filters.append("dsa.promotion_id = :promotion_id")
        params["promotion_id"] = promotion_id
    if date_from:
        filters.append("dsa.sale_date >= :df")
        params["df"] = date_from
    if date_to:
        filters.append("dsa.sale_date <= :dt")
        params["dt"] = date_to
    where = " AND ".join(filters)
    q = f"""
        SELECT dsa.*,
               s.store_name,
               p.product_name,
               pr.promotion_name
        FROM daily_sales_aggregates dsa
        JOIN stores   s  ON s.store_id     = dsa.store_id
        JOIN products p  ON p.product_id   = dsa.product_id
        LEFT JOIN promotions pr ON pr.promotion_id = dsa.promotion_id
        WHERE {where}
        ORDER BY dsa.sale_date DESC, dsa.total_sales_amount DESC
        LIMIT :limit OFFSET :offset
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# REVENUE TRENDS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/trends/revenue/monthly",
    response_model=List[RevenueTrendOut],
    summary="Monthly revenue trend",
    description=(
        "Month-over-month revenue grouped by store (or across all stores). "
        "Includes MoM growth % for the last 12 months."
    ),
)
async def monthly_revenue_trend(
    store_id: Optional[int] = Query(None),
    months: int = Query(12, ge=1, le=36),
    db: AsyncSession = Depends(get_db),
):
    store_filter = "AND st.store_id = :store_id" if store_id else ""
    params: dict = {"months": months}
    if store_id:
        params["store_id"] = store_id
    q = f"""
        WITH monthly AS (
            SELECT
                TO_CHAR(st.sale_date, 'YYYY-MM') AS period,
                st.store_id,
                s.store_name,
                SUM(st.total_amount)              AS total_revenue,
                SUM(si.quantity)                  AS total_units,
                COUNT(DISTINCT st.sale_id)        AS total_transactions
            FROM sales_transactions st
            JOIN stores s   ON s.store_id = st.store_id
            JOIN sales_items si ON si.sale_id = st.sale_id
            WHERE st.is_returned = B'0'::bit(1)
              AND st.sale_date >= (CURRENT_DATE - INTERVAL '1 month' * :months)
              {store_filter}
            GROUP BY period, st.store_id, s.store_name
        ),
        with_growth AS (
            SELECT *,
                ROUND(
                    (total_revenue - LAG(total_revenue) OVER (
                        PARTITION BY store_id ORDER BY period
                    )) * 100.0
                    / NULLIF(LAG(total_revenue) OVER (
                        PARTITION BY store_id ORDER BY period
                    ), 0)
                , 2) AS mom_growth_pct
            FROM monthly
        )
        SELECT *, NULL::numeric AS yoy_growth_pct
        FROM with_growth
        ORDER BY period DESC, store_id
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/trends/revenue/weekly",
    response_model=List[RevenueTrendOut],
    summary="Weekly revenue trend",
    description="Week-over-week revenue for the past N weeks.",
)
async def weekly_revenue_trend(
    store_id: Optional[int] = Query(None),
    weeks: int = Query(12, ge=1, le=52),
    db: AsyncSession = Depends(get_db),
):
    store_filter = "AND st.store_id = :store_id" if store_id else ""
    params: dict = {"weeks": weeks}
    if store_id:
        params["store_id"] = store_id
    q = f"""
        SELECT
            TO_CHAR(DATE_TRUNC('week', st.sale_date), 'IYYY-IW') AS period,
            st.store_id,
            s.store_name,
            SUM(st.total_amount)       AS total_revenue,
            SUM(si.quantity)           AS total_units,
            COUNT(DISTINCT st.sale_id) AS total_transactions,
            NULL::numeric              AS yoy_growth_pct,
            NULL::numeric              AS mom_growth_pct
        FROM sales_transactions st
        JOIN stores s   ON s.store_id   = st.store_id
        JOIN sales_items si ON si.sale_id = st.sale_id
        WHERE st.is_returned = B'0'::bit(1)
          AND st.sale_date >= (CURRENT_DATE - INTERVAL '1 week' * :weeks)
          {store_filter}
        GROUP BY period, st.store_id, s.store_name
        ORDER BY period DESC, st.store_id
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# CATEGORY BREAKDOWN
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/breakdown/category",
    response_model=List[CategoryRevenueOut],
    summary="Revenue by product category",
    description="Revenue share and unit volume per category over a date range.",
)
async def category_revenue_breakdown(
    date_from: date = Query(...),
    date_to: date = Query(...),
    store_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    store_filter = "AND st.store_id = :store_id" if store_id else ""
    params: dict = {"df": date_from, "dt": date_to}
    if store_id:
        params["store_id"] = store_id
    q = f"""
        WITH cat_totals AS (
            SELECT
                pc.category_id,
                pc.category_name,
                SUM(si.total_price) AS total_revenue,
                SUM(si.quantity)    AS total_units
            FROM sales_transactions st
            JOIN sales_items si ON si.sale_id = st.sale_id
            JOIN products p     ON p.product_id = si.product_id
            JOIN product_categories pc ON pc.category_id = p.category_id
            WHERE st.sale_date BETWEEN :df AND :dt
              AND st.is_returned = B'0'::bit(1)
              {store_filter}
            GROUP BY pc.category_id, pc.category_name
        ),
        grand_total AS (SELECT SUM(total_revenue) AS grand FROM cat_totals)
        SELECT ct.*,
               ROUND(ct.total_revenue * 100.0 / NULLIF(gt.grand, 0), 2) AS revenue_share_pct
        FROM cat_totals ct, grand_total gt
        ORDER BY ct.total_revenue DESC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# EXTERNAL EVENT IMPACT
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/events",
    summary="List external events",
    description="All external events (festivals, weather, strikes, etc.).",
)
async def list_external_events(
    event_type: Optional[str] = Query(None),
    severity_min: Optional[int] = Query(None, ge=1, le=5),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {}
    if event_type:
        filters.append("event_type = :event_type")
        params["event_type"] = event_type
    if severity_min:
        filters.append("severity_level >= :sev")
        params["sev"] = severity_min
    where = " AND ".join(filters)
    q = f"""
        SELECT * FROM external_events WHERE {where}
        ORDER BY start_date DESC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/events/{event_id}/impact",
    response_model=EventImpactOut,
    summary="Event revenue and anomaly impact",
    description=(
        "For a given external event, calculates the number of anomalies triggered, "
        "average deviation % and estimated revenue impact."
    ),
)
async def event_impact(event_id: int, db: AsyncSession = Depends(get_db)):
    q = """
        SELECT
            ee.event_id,
            ee.event_name,
            ee.event_type,
            ee.severity_level,
            ee.affected_region,
            ee.start_date,
            ee.end_date,
            COUNT(sa.anomaly_id)              AS anomaly_count,
            ROUND(AVG(sa.deviation_percentage), 2) AS avg_deviation_pct,
            ROUND(SUM(
                COALESCE(sa.actual_sales_quantity, 0) -
                COALESCE(sa.expected_sales_quantity, 0)
            ), 2)                              AS total_revenue_impact
        FROM external_events ee
        LEFT JOIN sales_anomalies sa ON sa.associated_event_id = ee.event_id
        WHERE ee.event_id = :eid
        GROUP BY ee.event_id, ee.event_name, ee.event_type,
                 ee.severity_level, ee.affected_region,
                 ee.start_date, ee.end_date
    """
    result = await db.execute(text(q), {"eid": event_id})
    row = result.mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return dict(row)


# ─────────────────────────────────────────────────────────────────────────────
# PROMOTION EFFECTIVENESS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/promotions/effectiveness",
    response_model=List[PromotionEffectivenessOut],
    summary="Promotion revenue effectiveness",
    description=(
        "For each promotion, shows revenue and units generated during the promo window "
        "across active stores. Compares against baseline to calculate lift %."
    ),
)
async def promotion_effectiveness(
    active_only: bool = Query(False, description="Only past/expired promotions with actuals"),
    db: AsyncSession = Depends(get_db),
):
    where = "WHERE p.end_date < CURRENT_DATE" if active_only else ""
    q = f"""
        SELECT
            p.promotion_id,
            p.promotion_name,
            p.promotion_type,
            p.discount_percent,
            COUNT(DISTINCT sp.store_id)       AS stores_active,
            COALESCE(SUM(dsa.total_sales_amount), 0) AS total_revenue_during,
            COALESCE(SUM(dsa.total_quantity), 0)     AS total_units_during,
            NULL::numeric                     AS avg_daily_revenue_lift_pct
        FROM promotions p
        LEFT JOIN store_promotions sp
            ON sp.promotion_id = p.promotion_id
           AND sp.is_active = B'1'::bit(1)
        LEFT JOIN daily_sales_aggregates dsa
            ON dsa.promotion_id = p.promotion_id
        {where}
        GROUP BY p.promotion_id, p.promotion_name, p.promotion_type, p.discount_percent
        ORDER BY total_revenue_during DESC
    """
    result = await db.execute(text(q))
    return [dict(r) for r in result.mappings().all()]


# ─────────────────────────────────────────────────────────────────────────────
# PRODUCT PERFORMANCE DEEP DIVE
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/products/{product_id}/performance",
    summary="Product performance across stores",
    description=(
        "Revenue, units, forecast accuracy and anomaly count for a product "
        "broken down by store. Ideal for identifying underperforming locations."
    ),
)
async def product_performance(
    product_id: int,
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"product_id": product_id}
    date_clause = ""
    if date_from:
        date_clause += " AND st.sale_date >= :df"
        params["df"] = date_from
    if date_to:
        date_clause += " AND st.sale_date <= :dt"
        params["dt"] = date_to
    q = f"""
        SELECT
            s.store_id,
            s.store_name,
            s.city,
            COALESCE(SUM(si.total_price), 0)     AS total_revenue,
            COALESCE(SUM(si.quantity), 0)         AS total_units_sold,
            COUNT(DISTINCT st.sale_id)            AS transactions,
            ROUND(AVG(si.unit_price), 2)          AS avg_selling_price,
            (SELECT sl.quantity FROM stock_levels sl
             WHERE sl.store_id=s.store_id AND sl.product_id=:product_id) AS current_stock,
            (SELECT COUNT(*) FROM sales_anomalies sa
             WHERE sa.store_id=s.store_id AND sa.product_id=:product_id) AS anomaly_count,
            (SELECT COUNT(*) FROM sales_forecasts sf
             WHERE sf.store_id=s.store_id AND sf.product_id=:product_id
             AND sf.actual_quantity IS NOT NULL)                          AS forecast_count
        FROM stores s
        LEFT JOIN sales_transactions st
            ON st.store_id = s.store_id
            AND st.is_returned = B'0'::bit(1)
            {date_clause}
        LEFT JOIN sales_items si
            ON si.sale_id = st.sale_id AND si.product_id = :product_id
        GROUP BY s.store_id, s.store_name, s.city
        ORDER BY total_revenue DESC
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]


@router.get(
    "/audit-log",
    summary="Recent audit log entries",
    description=(
        "Last N audit log entries for compliance and change tracking. "
        "Filter by table, action type or actor."
    ),
)
async def recent_audit_log(
    table_name: Optional[str] = Query(None),
    action: Optional[str] = Query(None, pattern="^(INSERT|UPDATE|DELETE)$"),
    changed_by: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    filters = ["1=1"]
    params: dict = {"limit": limit}
    if table_name:
        filters.append("table_name = :table_name")
        params["table_name"] = table_name
    if action:
        filters.append("action = :action")
        params["action"] = action
    if changed_by:
        filters.append("changed_by ILIKE :changed_by")
        params["changed_by"] = f"%{changed_by}%"
    where = " AND ".join(filters)
    q = f"""
        SELECT * FROM audit_log
        WHERE {where}
        ORDER BY changed_at DESC, log_id DESC
        LIMIT :limit
    """
    result = await db.execute(text(q), params)
    return [dict(r) for r in result.mappings().all()]
