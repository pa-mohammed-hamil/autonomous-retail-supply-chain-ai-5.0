# SupplyChainAI — Live Project Demonstration Script

**Project:** Retail Supply Chain Optimization & Agentic AI Platform  
**Demo duration:** 8–12 minutes  
**Audience:** AI Engineers, ML Engineers, Recruiters, Technical Interviewers

## 1. Introduction — 45 seconds

SupplyChainAI is a portfolio project designed to demonstrate how machine learning, data engineering, supply chain analytics, and agentic AI can work together in a retail operations platform.

The project includes demand forecasting, inventory intelligence, supplier risk analysis, logistics optimization, sentiment analysis, simulated corporate escalations, and operational dashboards.

**Important:** The demonstrations use synthetic datasets and simulated operational events.

## 2. Executive Dashboard — 1 minute

Open `index.html`.

Demonstrate:
- Inventory and warehouse KPI cards
- Sales and demand charts
- Supplier and logistics summaries
- Simulated alert indicators
- Navigation to operational modules

Explain the difference between sample dashboard data and actual API-connected results.

## 3. Demand Forecasting — 1 minute

Open `demand-forecasting.html`.

Explain:
- Historical sales ingestion
- Lag and rolling-window feature engineering
- Chronological model evaluation
- Demand forecast visualization
- Forecast error metrics

Run:

`python scripts/train_models.py --model demand`

The current training pipeline forecasts aggregate daily demand rather than individual product demand.

## 4. Inventory and Stockout Intelligence — 1 minute

Open `inventory-intelligence.html`.

Run:

`python scripts/simulate_inventory_updates.py --events 500`

Show:
- Simulated stock changes
- Stockout risk
- Low-stock alerts
- Replenishment recommendations
- Inventory transaction audit logs

Explain that source inventory is not modified.

## 5. Supplier Failure Simulation — 1 minute

Open `supplier-risk.html`.

Run:

`python scripts/simulate_supplier_failure.py --scenario production_shutdown`

Show:
- Affected products and warehouses
- Potential supply shortages
- Estimated revenue exposure
- Alternative supplier screening
- Simulated procurement escalation

Explain that alternative suppliers require compatibility and capacity verification.

## 6. Demand Spike Simulation — 1 minute

Open `demand-spike-detection.html`.

Run:

`python scripts/simulate_demand_spike.py --scenario festival --duration 14`

Demonstrate:
- Demand increase
- Inventory depletion
- Unfulfilled units
- Warehouse pressure
- Replenishment estimates

## 7. Customer Feedback Intelligence — 1 minute

Open `negative-feedback-alerts.html`.

Run:

`python scripts/simulate_negative_feedback.py --complaints 100`

Show:
- Complaint classification
- Negative sentiment
- Product quality complaints
- SLA breaches
- Simulated corporate escalation

## 8. Logistics Optimization — 1 minute

Open `logistics-optimization.html`.

Explain:
- Delivery orders
- Vehicle capacities
- Time-window constraints
- Route optimization
- Estimated delivery schedules

Use the logistics notebook outputs if available.

## 9. Agentic AI and RAG — 1 minute

Open `multi-agent-control.html` and `rag-copilot.html`.

Present the proposed or implemented architecture accurately:

- Specialized agents for inventory, supplier risk, logistics, analytics, and escalation
- Retrieval-augmented document assistance
- Human approval for consequential actions
- Audit logs and access controls
- Monitoring and evaluation

Do not describe simulated workflows as autonomous production operations.

## 10. Deployment Architecture — 1 minute

Explain the development architecture:

- FastAPI backend
- PostgreSQL database
- Redis message broker
- Celery background workers
- Nginx frontend
- Docker Compose
- Kubernetes and Terraform deployment configurations

Demonstrate only services that have been configured and successfully started.

## 11. Closing — 30 seconds

SupplyChainAI demonstrates my approach to combining machine learning, Python backend engineering, analytics, and agent-oriented system design.

The next engineering steps are to validate models using real operational outcomes, integrate live data pipelines, implement secure production workflows, and test reliability under realistic workloads.

**Portfolio focus:** Python, SQL, ML, GenAI, Agentic AI, FastAPI, Docker, Cloud, MLOps and LLMOps.