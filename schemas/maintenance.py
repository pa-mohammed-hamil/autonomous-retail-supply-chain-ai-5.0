"""
Pydantic schemas for Predictive Maintenance API
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class MaintenanceType(str, Enum):
    """Maintenance type options."""
    PREVENTIVE = "preventive"
    CORRECTIVE = "corrective"
    PREDICTIVE = "predictive"
    ROUTINE = "routine"
    EMERGENCY = "emergency"


class WorkOrderStatus(str, Enum):
    """Work order status options."""
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class HealthStatus(str, Enum):
    """Equipment health status."""
    EXCELLENT = "excellent"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    CRITICAL = "critical"


class Urgency(str, Enum):
    """Maintenance urgency level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
    IMMEDIATE = "immediate"


# Request Schemas

class HealthCheckRequest(BaseModel):
    """Request for equipment health check."""
    equipment_id: str = Field(..., description="Equipment identifier")
    location: Optional[str] = Field(None, description="Equipment location")
    
    class Config:
        json_schema_extra = {
            "example": {
                "equipment_id": "EQ-001",
                "location": "Warehouse-North"
            }
        }


class FailurePredictionRequest(BaseModel):
    """Request for failure prediction."""
    equipment_id: str = Field(..., description="Equipment identifier")
    horizon_days: int = Field(30, ge=1, le=365, description="Prediction horizon in days")
    
    class Config:
        json_schema_extra = {
            "example": {
                "equipment_id": "EQ-001",
                "horizon_days": 30
            }
        }


class MaintenanceScheduleRequest(BaseModel):
    """Request to schedule maintenance."""
    equipment_id: str = Field(..., description="Equipment identifier")
    maintenance_type: MaintenanceType = Field(..., description="Type of maintenance")
    preferred_date: Optional[datetime] = Field(None, description="Preferred maintenance date")
    notes: Optional[str] = Field(None, description="Additional notes")
    
    class Config:
        json_schema_extra = {
            "example": {
                "equipment_id": "EQ-001",
                "maintenance_type": "preventive",
                "preferred_date": "2024-12-15T02:00:00",
                "notes": "Check bearings and lubrication"
            }
        }


class DiagnosisRequest(BaseModel):
    """Request for failure diagnosis."""
    equipment_id: str = Field(..., description="Equipment identifier")
    failure_description: str = Field(..., description="Description of failure")
    failure_timestamp: Optional[datetime] = Field(None, description="When failure occurred")
    
    class Config:
        json_schema_extra = {
            "example": {
                "equipment_id": "EQ-001",
                "failure_description": "Conveyor stopped unexpectedly. Unusual noise before shutdown.",
                "failure_timestamp": "2024-10-28T14:30:00"
            }
        }


# Response Schemas

class TelemetryData(BaseModel):
    """Telemetry sensor data."""
    temperature: Dict[str, float]
    vibration: Dict[str, float]
    power_kwh: Dict[str, float]
    operating_hours: float
    efficiency_pct: float
    error_codes: List[str]
    timestamp: datetime


class FailureIndicator(BaseModel):
    """Indicator of potential failure."""
    indicator: str
    severity: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    description: str


class RULEstimate(BaseModel):
    """Remaining Useful Life estimate."""
    days: float
    hours: float
    confidence_interval: Dict[str, float]
    method: str
    confidence: float


class HealthCheckResponse(BaseModel):
    """Response from health check."""
    equipment_id: str
    location: Optional[str]
    health_status: HealthStatus
    health_score: float = Field(..., ge=0, le=100)
    failure_probability: float = Field(..., ge=0, le=1)
    predicted_failure_date: Optional[datetime]
    remaining_useful_life_days: float
    anomalies_detected: List[str]
    recommended_actions: List[str]
    urgency: Urgency
    timestamp: datetime


class FailurePredictionResponse(BaseModel):
    """Response from failure prediction."""
    equipment_id: str
    failure_prediction: Dict[str, Any]
    remaining_useful_life: RULEstimate
    failure_indicators: List[FailureIndicator]
    recommendation: Dict[str, Any]
    requires_action: bool
    timestamp: datetime


class SparePart(BaseModel):
    """Spare part information."""
    part_id: str
    part_name: str
    quantity: int
    available: bool
    unit_cost: float


class WorkOrder(BaseModel):
    """Work order details."""
    id: str
    equipment_id: str
    maintenance_type: MaintenanceType
    scheduled_date: datetime
    estimated_duration_hours: float
    priority: str
    status: WorkOrderStatus
    spare_parts: List[SparePart]
    estimated_cost: float
    created_by: str
    created_at: datetime


class MaintenanceWindow(BaseModel):
    """Maintenance time window."""
    start_time: datetime
    end_time: datetime
    duration: float
    reason: str
    alternative_windows: List[Dict[str, Any]]


class MaintenanceScheduleResponse(BaseModel):
    """Response from maintenance scheduling."""
    equipment_id: str
    work_order: WorkOrder
    scheduled_window: MaintenanceWindow
    spare_parts: Dict[str, Any]
    schedule_result: Dict[str, Any]
    notifications_sent: bool
    status: str
    timestamp: datetime


class RootCause(BaseModel):
    """Root cause analysis."""
    root_cause: str
    contributing_factors: List[str]
    failure_sequence: List[str]
    similar_failures: List[Dict[str, Any]]
    preventive_measures: List[str]
    corrective_actions: List[str]
    confidence: float


class DiagnosisResponse(BaseModel):
    """Response from failure diagnosis."""
    equipment_id: str
    diagnosis: RootCause
    analysis_date: datetime
    recommended_next_steps: List[str]


class WorkOrderResponse(BaseModel):
    """Work order response."""
    id: str
    equipment_id: str
    equipment_name: Optional[str]
    location: Optional[str]
    maintenance_type: MaintenanceType
    status: WorkOrderStatus
    priority: str
    scheduled_date: Optional[datetime]
    completed_date: Optional[datetime]
    estimated_duration_hours: float
    actual_duration_hours: Optional[float]
    estimated_cost: float
    actual_cost: Optional[float]
    assigned_technician: Optional[str]
    spare_parts: List[SparePart]
    notes: Optional[str]
    created_by: str
    created_at: datetime
    updated_at: datetime


class EquipmentSummary(BaseModel):
    """Equipment summary information."""
    equipment_id: str
    equipment_type: str
    model: str
    location: str
    health_status: HealthStatus
    criticality: str
    last_maintenance_date: Optional[datetime]
    next_maintenance_due: Optional[datetime]
    failure_probability: float
    rul_days: float


class EquipmentListResponse(BaseModel):
    """Response with list of equipment."""
    equipment: List[EquipmentSummary]
    total_count: int
    filters_applied: Dict[str, Any]
    timestamp: datetime


class DashboardMetrics(BaseModel):
    """Maintenance dashboard metrics."""
    total_equipment: int
    health_distribution: Dict[str, int]
    high_risk_equipment_count: int
    upcoming_maintenance_count: int
    overdue_maintenance_count: int
    active_work_orders: int
    completed_work_orders_this_month: int
    average_mtbf_hours: float
    average_mttr_hours: float
    total_downtime_hours: float
    maintenance_cost_this_month: float
    predicted_cost_next_month: float
    top_issues: List[Dict[str, Any]]
    timestamp: datetime


class MaintenanceAlert(BaseModel):
    """Maintenance alert."""
    alert_id: str
    equipment_id: str
    equipment_name: str
    location: str
    alert_type: str
    severity: str
    message: str
    failure_probability: Optional[float]
    rul_days: Optional[float]
    acknowledged: bool
    acknowledged_by: Optional[str]
    acknowledged_at: Optional[datetime]
    created_at: datetime
