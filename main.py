"""
Retail FastAPI — Business Operations API
Roles: Sales Manager | Supplier Manager | Business Analyst (Forecasting)
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import sales_manager, supplier_manager, analyst

app = FastAPI(
    title="Retail Business Operations API",
    description=(
        "Multi-role REST API for Retail retail platform.\n\n"
        "**Roles covered:**\n"
        "- Sales Manager — transactions, stock alerts, promotions, store KPIs\n"
        "- Supplier Manager — purchase orders, supplier performance, replenishment\n"
        "- Business Analyst — sales forecasts, anomaly detection, aggregates\n"
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sales_manager.router, prefix="/sales", tags=["Sales Manager"])
app.include_router(supplier_manager.router, prefix="/supply", tags=["Supplier Manager"])
app.include_router(analyst.router, prefix="/analytics", tags=["Business Analyst"])


@app.get("/", tags=["Health"])
def root():
    return {
        "service": "Retail Business Operations API",
        "version": "1.0.0",
        "roles": ["sales_manager", "supplier_manager", "business_analyst"],
        "docs": "/docs",
    }


@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok"}
