"""
Predictive Maintenance API Endpoints
RESTful API for equipment monitoring and predictive maintenance.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from typing import List, Optional
from datetime import datetime

from backend.schemas.maintenance import (
    HealthCheckRequest,
    HealthCheckResponse,
    FailurePredictionRequest,
    FailurePredictionResponse,
    MaintenanceScheduleRequest,
    MaintenanceScheduleResponse,
    DiagnosisRequest,
    DiagnosisResponse,
    WorkOrderResponse,
    EquipmentListResponse
)
from backend.services.maintenance_service import MaintenanceService
from backend.api.dependencies import get_current_user, get_maintenance_service
from backend.core.permissions import require_permission

router = APIRouter(prefix="/maintenance", tags=["maintenance"])


@router.post(
    "/health-check",
    response_model=HealthCheckResponse,
    summary="Equipment Health Check"
)
async def equipment_health_check(
    request: HealthCheckRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Perform comprehensive equipment health check.
    
    Analyzes:
    - Real-time telemetry data
    - Maintenance history
    - Failure prediction
    - Remaining useful life
    - Recommended actions
    """
    
    require_permission(current_user, "maintenance:view")
    
    result = await service.perform_health_check(
        equipment_id=request.equipment_id,
        location=request.location
    )
    
    return result


@router.post(
    "/predict-failure",
    response_model=FailurePredictionResponse,
    summary="Predict Equipment Failure"
)
async def predict_failure(
    request: FailurePredictionRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Predict equipment failure probability and timing.
    
    Uses ML models trained on historical failure data.
    """
    
    require_permission(current_user, "maintenance:predict")
    
    prediction = await service.predict_failure(
        equipment_id=request.equipment_id,
        prediction_horizon_days=request.horizon_days
    )
    
    return prediction


@router.post(
    "/schedule",
    response_model=MaintenanceScheduleResponse,
    summary="Schedule Maintenance"
)
async def schedule_maintenance(
    request: MaintenanceScheduleRequest,
    background_tasks: BackgroundTasks,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Schedule preventive or corrective maintenance.
    
    Considers:
    - Equipment availability
    - Spare parts availability
    - Technician scheduling
    - Operational impact
    """
    
    require_permission(current_user, "maintenance:schedule")
    
    schedule_result = await service.schedule_maintenance(
        equipment_id=request.equipment_id,
        maintenance_type=request.maintenance_type,
        preferred_date=request.preferred_date,
        user_id=current_user.id
    )
    
    # Send notifications
    background_tasks.add_task(
        service.send_maintenance_notifications,
        schedule_result
    )
    
    return schedule_result


@router.post(
    "/diagnose",
    response_model=DiagnosisResponse,
    summary="Diagnose Equipment Failure"
)
async def diagnose_failure(
    request: DiagnosisRequest,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Perform root cause analysis for equipment failure.
    
    Provides:
    - Most likely root cause
    - Contributing factors
    - Failure sequence
    - Corrective actions
    - Preventive measures
    """
    
    require_permission(current_user, "maintenance:diagnose")
    
    diagnosis = await service.diagnose_failure(
        equipment_id=request.equipment_id,
        failure_description=request.failure_description
    )
    
    return diagnosis


@router.get(
    "/equipment/{equipment_id}",
    summary="Get Equipment Details"
)
async def get_equipment_details(
    equipment_id: str,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get detailed information about specific equipment."""
    
    equipment = await service.get_equipment(equipment_id)
    
    if not equipment:
        raise HTTPException(status_code=404, detail=f"Equipment {equipment_id} not found")
    
    return equipment


@router.get(
    "/equipment/{equipment_id}/telemetry",
    summary="Get Equipment Telemetry"
)
async def get_equipment_telemetry(
    equipment_id: str,
    hours: int = Query(24, ge=1, le=168),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get recent telemetry data for equipment."""
    
    telemetry = await service.get_telemetry(equipment_id, hours)
    
    return telemetry


@router.get(
    "/equipment/{equipment_id}/history",
    summary="Get Maintenance History"
)
async def get_maintenance_history(
    equipment_id: str,
    days: int = Query(90, ge=1, le=365),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get maintenance and repair history."""
    
    history = await service.get_maintenance_history(equipment_id, days)
    
    return history


@router.get(
    "/work-orders",
    response_model=List[WorkOrderResponse],
    summary="List Work Orders"
)
async def list_work_orders(
    status: Optional[str] = None,
    location: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """List maintenance work orders with filters."""
    
    work_orders = await service.get_work_orders(
        status=status,
        location=location,
        priority=priority,
        limit=limit
    )
    
    return work_orders


@router.get(
    "/work-orders/{work_order_id}",
    response_model=WorkOrderResponse,
    summary="Get Work Order"
)
async def get_work_order(
    work_order_id: str,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get specific work order details."""
    
    work_order = await service.get_work_order(work_order_id)
    
    if not work_order:
        raise HTTPException(status_code=404, detail=f"Work order {work_order_id} not found")
    
    return work_order


@router.patch(
    "/work-orders/{work_order_id}/status",
    summary="Update Work Order Status"
)
async def update_work_order_status(
    work_order_id: str,
    status: str,
    notes: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Update work order status (e.g., in_progress, completed)."""
    
    require_permission(current_user, "maintenance:update")
    
    result = await service.update_work_order_status(
        work_order_id=work_order_id,
        status=status,
        notes=notes,
        user_id=current_user.id
    )
    
    return result


@router.get(
    "/equipment",
    response_model=EquipmentListResponse,
    summary="List Equipment"
)
async def list_equipment(
    location: Optional[str] = None,
    equipment_type: Optional[str] = None,
    health_status: Optional[str] = None,
    criticality: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """List all equipment with filters."""
    
    equipment_list = await service.list_equipment(
        location=location,
        equipment_type=equipment_type,
        health_status=health_status,
        criticality=criticality
    )
    
    return equipment_list


@router.get(
    "/dashboard/metrics",
    summary="Get Maintenance Dashboard Metrics"
)
async def get_dashboard_metrics(
    time_period_days: int = Query(30, ge=1, le=365),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Get key maintenance metrics for dashboard.
    
    Includes:
    - Equipment health distribution
    - Upcoming maintenance
    - Failure predictions
    - Downtime statistics
    - Cost metrics
    """
    
    metrics = await service.get_dashboard_metrics(time_period_days)
    
    return metrics


@router.get(
    "/analytics/mtbf",
    summary="Mean Time Between Failures"
)
async def get_mtbf_analytics(
    equipment_type: Optional[str] = None,
    location: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get MTBF analytics by equipment type or location."""
    
    analytics = await service.get_mtbf_analytics(
        equipment_type=equipment_type,
        location=location
    )
    
    return analytics


@router.get(
    "/analytics/downtime",
    summary="Downtime Analytics"
)
async def get_downtime_analytics(
    time_period_days: int = Query(90, ge=1, le=365),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get equipment downtime analytics."""
    
    analytics = await service.get_downtime_analytics(time_period_days)
    
    return analytics


@router.post(
    "/spare-parts/plan",
    summary="Generate Spare Parts Plan"
)
async def generate_spare_parts_plan(
    time_horizon_days: int = Query(90, ge=30, le=365),
    location: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """
    Generate spare parts inventory plan based on predicted maintenance needs.
    """
    
    require_permission(current_user, "maintenance:plan")
    
    parts_plan = await service.generate_spare_parts_plan(
        time_horizon_days=time_horizon_days,
        location=location
    )
    
    return parts_plan


@router.get(
    "/alerts",
    summary="Get Maintenance Alerts"
)
async def get_maintenance_alerts(
    severity: Optional[str] = None,
    acknowledged: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=200),
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Get active maintenance alerts and warnings."""
    
    alerts = await service.get_maintenance_alerts(
        severity=severity,
        acknowledged=acknowledged,
        limit=limit
    )
    
    return alerts


@router.post(
    "/alerts/{alert_id}/acknowledge",
    summary="Acknowledge Alert"
)
async def acknowledge_alert(
    alert_id: str,
    notes: Optional[str] = None,
    service: MaintenanceService = Depends(get_maintenance_service),
    current_user = Depends(get_current_user)
):
    """Acknowledge a maintenance alert."""
    
    result = await service.acknowledge_alert(
        alert_id=alert_id,
        user_id=current_user.id,
        notes=notes
    )
    
    return result
