"""
Pydantic schemas — request/response models for all three roles.
"""

from __future__ import annotations
from datetime import date
from decimal import Decimal
from typing import List, Optional
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# Shared
# ─────────────────────────────────────────────

class PaginationParams(BaseModel):
    page: int = Field(1, ge=1)
    page_size: int = Field(20, ge=1, le=100)


# ─────────────────────────────────────────────
# SALES MANAGER schemas
# ─────────────────────────────────────────────

class SalesSummary(BaseModel):
    store_id: int
    store_name: str
    sale_date: date
    total_transactions: int
    total_revenue: Decimal
    total_units_sold: Decimal
    avg_transaction_value: Decimal


class TransactionOut(BaseModel):
    sale_id: int
    sale_number: str
    store_id: int
    customer_id: Optional[int]
    cashier_id: str
    sale_date: date
    subtotal: Decimal
    tax_amount: Decimal
    discount_amount: Decimal
    total_amount: Decimal
    payment_method: str
    payment_status: str
    is_returned: bool
    notes: Optional[str]

    class Config:
        from_attributes = True


class SaleItemOut(BaseModel):
    sale_item_id: int
    sale_id: int
    product_id: int
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_percent: Decimal
    discount_amount: Decimal
    total_price: Decimal

    class Config:
        from_attributes = True


class StockAlertOut(BaseModel):
    alert_id: int
    store_id: int
    store_name: str
    product_id: int
    product_name: str
    alert_type: str
    threshold_value: Optional[Decimal]
    current_value: Optional[Decimal]
    alert_status: str
    created_at: date

    class Config:
        from_attributes = True


class AlertStatusUpdate(BaseModel):
    alert_status: str = Field(..., pattern="^(PENDING|ACKNOWLEDGED|RESOLVED)$")
    resolution_notes: Optional[str] = None


class PromotionOut(BaseModel):
    promotion_id: int
    promotion_code: Optional[str]
    promotion_name: str
    promotion_type: str
    discount_percent: Optional[Decimal]
    discount_amount: Optional[Decimal]
    start_date: date
    end_date: date
    is_active: bool

    class Config:
        from_attributes = True


class StoreKPIOut(BaseModel):
    store_id: int
    store_name: str
    period_start: date
    period_end: date
    total_revenue: Decimal
    total_transactions: int
    total_units_sold: Decimal
    avg_daily_revenue: Decimal
    top_product: str
    return_rate_pct: Decimal


class TopProductOut(BaseModel):
    product_id: int
    product_name: str
    category_name: str
    total_quantity_sold: Decimal
    total_revenue: Decimal
    transaction_count: int


class CustomerSalesOut(BaseModel):
    customer_id: int
    customer_name: str
    customer_type: str
    loyalty_points: int
    total_purchases: Decimal
    last_purchase_date: Optional[date]
    transaction_count: int


# ─────────────────────────────────────────────
# SUPPLIER MANAGER schemas
# ─────────────────────────────────────────────

class SupplierOut(BaseModel):
    supplier_id: int
    supplier_code: str
    supplier_name: str
    contact_person: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    payment_terms: Optional[str]
    credit_limit: Optional[Decimal]
    rating: Optional[Decimal]
    is_active: bool

    class Config:
        from_attributes = True


class SupplierPerformanceOut(BaseModel):
    supplier_id: int
    supplier_name: str
    rating: Optional[Decimal]
    total_pos: int
    delivered_pos: int
    cancelled_pos: int
    on_time_delivery_pct: Decimal
    avg_lead_time_days: Optional[Decimal]
    total_order_value: Decimal


class PurchaseOrderOut(BaseModel):
    po_id: int
    po_number: str
    store_id: int
    store_name: str
    supplier_id: int
    supplier_name: str
    order_date: date
    expected_delivery_date: date
    actual_delivery_date: Optional[date]
    order_status: str
    total_amount: Optional[Decimal]
    tax_amount: Optional[Decimal]
    discount_amount: Optional[Decimal]
    shipping_cost: Optional[Decimal]
    created_by: Optional[str]
    approved_by: Optional[str]

    class Config:
        from_attributes = True


class POCreateRequest(BaseModel):
    store_id: int
    supplier_id: int
    expected_delivery_date: date
    notes: Optional[str] = None
    items: List[POItemRequest]


class POItemRequest(BaseModel):
    product_id: int
    quantity_ordered: Decimal = Field(..., gt=0)
    unit_cost: Decimal = Field(..., gt=0)


class POStatusUpdate(BaseModel):
    order_status: str = Field(
        ..., pattern="^(PENDING|APPROVED|IN_TRANSIT|DELIVERED|CANCELLED)$"
    )
    actual_delivery_date: Optional[date] = None
    notes: Optional[str] = None


class POItemOut(BaseModel):
    po_item_id: int
    po_id: int
    product_id: int
    product_name: str
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_cost: Decimal
    total_cost: Optional[Decimal]
    received_date: Optional[date]
    notes: Optional[str]

    class Config:
        from_attributes = True


class ReplenishmentSuggestionOut(BaseModel):
    store_id: int
    store_name: str
    product_id: int
    product_name: str
    current_qty: Decimal
    reorder_point: Decimal
    reorder_quantity: Decimal
    suggested_supplier_id: int
    suggested_supplier_name: str
    estimated_unit_cost: Decimal
    estimated_lead_time_days: int
    estimated_delivery_cost: Decimal
    urgency: str


class StockMovementOut(BaseModel):
    movement_id: int
    store_id: int
    product_id: int
    product_name: str
    movement_type: str
    quantity: Decimal
    previous_quantity: Decimal
    new_quantity: Decimal
    reference_type: Optional[str]
    reference_id: Optional[int]
    notes: Optional[str]
    created_by: str
    created_at: date

    class Config:
        from_attributes = True


# ─────────────────────────────────────────────
# BUSINESS ANALYST schemas
# ─────────────────────────────────────────────

class ForecastOut(BaseModel):
    forecast_id: int
    product_id: int
    product_name: str
    store_id: int
    store_name: str
    forecast_date: date
    predicted_quantity: Optional[Decimal]
    confidence_lower: Optional[Decimal]
    confidence_upper: Optional[Decimal]
    actual_quantity: Optional[Decimal]
    forecast_method: Optional[str]
    mape_pct: Optional[Decimal]

    class Config:
        from_attributes = True


class ForecastCreateRequest(BaseModel):
    product_id: int
    store_id: int
    forecast_date: date
    predicted_quantity: Decimal = Field(..., gt=0)
    confidence_lower: Decimal
    confidence_upper: Decimal
    forecast_method: str = Field(..., pattern="^(Prophet|ARIMA|LightGBM|Moving_Average)$")


class AnomalyOut(BaseModel):
    anomaly_id: int
    store_id: int
    store_name: str
    product_id: int
    product_name: str
    anomaly_date: date
    expected_sales_quantity: Optional[Decimal]
    actual_sales_quantity: Optional[Decimal]
    deviation_percentage: Optional[Decimal]
    associated_event_id: Optional[int]
    event_name: Optional[str]
    notes: Optional[str]

    class Config:
        from_attributes = True


class DailySalesAggregateOut(BaseModel):
    aggregate_id: int
    store_id: int
    store_name: str
    product_id: int
    product_name: str
    sale_date: date
    total_quantity: Optional[Decimal]
    total_sales_amount: Optional[Decimal]
    total_transactions: Optional[int]
    average_unit_price: Optional[Decimal]
    promotion_id: Optional[int]
    promotion_name: Optional[str]

    class Config:
        from_attributes = True


class RevenueTrendOut(BaseModel):
    period: str
    store_id: Optional[int]
    store_name: Optional[str]
    total_revenue: Decimal
    total_units: Decimal
    total_transactions: int
    yoy_growth_pct: Optional[Decimal]
    mom_growth_pct: Optional[Decimal]


class CategoryRevenueOut(BaseModel):
    category_id: int
    category_name: str
    total_revenue: Decimal
    total_units: Decimal
    revenue_share_pct: Decimal


class EventImpactOut(BaseModel):
    event_id: int
    event_name: str
    event_type: str
    severity_level: Optional[int]
    affected_region: Optional[str]
    start_date: date
    end_date: Optional[date]
    anomaly_count: int
    avg_deviation_pct: Optional[Decimal]
    total_revenue_impact: Optional[Decimal]


class ForecastAccuracyOut(BaseModel):
    forecast_method: str
    total_forecasts: int
    forecasts_with_actuals: int
    avg_mape_pct: Optional[Decimal]
    within_ci_pct: Optional[Decimal]


class PromotionEffectivenessOut(BaseModel):
    promotion_id: int
    promotion_name: str
    promotion_type: str
    discount_percent: Optional[Decimal]
    stores_active: int
    total_revenue_during: Decimal
    total_units_during: Decimal
    avg_daily_revenue_lift_pct: Optional[Decimal]
