"""
Predictive Maintenance Agent
Monitors equipment health and predicts maintenance needs to prevent failures.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.maintenance_tools import (
    get_equipment_telemetry,
    get_maintenance_history,
    get_equipment_specs,
    predict_equipment_failure,
    calculate_remaining_useful_life,
    schedule_maintenance,
    create_work_order,
    get_spare_parts_availability
)


class MaintenanceAgent(BaseAgent):
    """
    Autonomous agent for predictive equipment maintenance.
    
    Features:
    - Real-time equipment health monitoring
    - Failure prediction using ML models
    - Remaining Useful Life (RUL) estimation
    - Automated maintenance scheduling
    - Spare parts inventory optimization
    - Root cause analysis for failures
    - Maintenance cost optimization
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="MaintenanceAgent",
            role="predictive_maintenance",
            llm_client=llm_client,
            **kwargs
        )
        self.failure_threshold = 0.70  # 70% failure probability triggers action
        self.critical_rul_days = 7  # Critical if RUL < 7 days
        self.maintenance_window_hours = 4  # Standard maintenance window

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute predictive maintenance workflow."""
        self.log_execution_start(context)
        
        action = context.get("action", "health_check")
        
        try:
            if action == "health_check":
                result = await self._perform_health_check(context)
            elif action == "predict_failure":
                result = await self._predict_equipment_failure(context)
            elif action == "schedule_maintenance":
                result = await self._schedule_preventive_maintenance(context)
            elif action == "diagnose_failure":
                result = await self._diagnose_equipment_failure(context)
            elif action == "optimize_schedule":
                result = await self._optimize_maintenance_schedule(context)
            elif action == "parts_planning":
                result = await self._plan_spare_parts(context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Maintenance agent execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _perform_health_check(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform comprehensive equipment health check."""
        
        equipment_id = context.get("equipment_id")
        location = context.get("location")
        
        # Gather equipment data
        telemetry, history, specs = await asyncio.gather(
            get_equipment_telemetry(equipment_id, hours=24),
            get_maintenance_history(equipment_id, days=90),
            get_equipment_specs(equipment_id)
        )
        
        # Analyze equipment health using LLM
        health_analysis = await self._analyze_equipment_health(
            telemetry, history, specs
        )
        
        # Predict failure probability
        failure_prediction = await predict_equipment_failure(
            equipment_id=equipment_id,
            telemetry_data=telemetry,
            history=history
        )
        
        # Calculate remaining useful life
        rul = await calculate_remaining_useful_life(
            equipment_id=equipment_id,
            current_condition=telemetry,
            usage_pattern=history
        )
        
        # Determine health status
        health_status = self._determine_health_status(
            health_analysis,
            failure_prediction,
            rul
        )
        
        return {
            "equipment_id": equipment_id,
            "location": location,
            "health_status": health_status,
            "health_score": health_analysis.get("health_score", 0),
            "failure_probability": failure_prediction["probability"],
            "predicted_failure_date": failure_prediction.get("predicted_date"),
            "remaining_useful_life_days": rul["days"],
            "anomalies_detected": health_analysis.get("anomalies", []),
            "recommended_actions": health_analysis.get("recommendations", []),
            "urgency": self._calculate_urgency(failure_prediction, rul),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_equipment_health(
        self,
        telemetry: Dict[str, Any],
        history: Dict[str, Any],
        specs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Analyze equipment health using LLM reasoning."""
        
        prompt = f"""
        Analyze the health of the following equipment based on telemetry and maintenance history.
        
        Equipment Type: {specs.get('type', 'Unknown')}
        Model: {specs.get('model', 'Unknown')}
        Age: {specs.get('age_years', 'Unknown')} years
        Expected Lifespan: {specs.get('expected_lifespan_years', 'Unknown')} years
        
        Current Telemetry (Last 24 Hours):
        - Temperature: {telemetry.get('temperature', {}).get('avg', 'N/A')}°C (Normal: {specs.get('normal_temp_range', 'N/A')})
        - Vibration: {telemetry.get('vibration', {}).get('avg', 'N/A')} Hz (Normal: {specs.get('normal_vibration_range', 'N/A')})
        - Power Consumption: {telemetry.get('power_kwh', {}).get('avg', 'N/A')} kWh (Normal: {specs.get('normal_power_range', 'N/A')})
        - Operating Hours: {telemetry.get('operating_hours', 'N/A')}
        - Error Codes: {telemetry.get('error_codes', [])}
        - Performance Efficiency: {telemetry.get('efficiency_pct', 'N/A')}%
        
        Maintenance History (Last 90 Days):
        - Last Maintenance: {history.get('last_maintenance_date', 'Never')}
        - Maintenance Type: {history.get('last_maintenance_type', 'N/A')}
        - Recent Repairs: {history.get('recent_repairs', [])}
        - Failure Count: {history.get('failure_count', 0)}
        - Mean Time Between Failures (MTBF): {history.get('mtbf_hours', 'N/A')} hours
        
        Provide a detailed health analysis covering:
        1. Overall health score (0-100)
        2. Anomalies detected (out-of-range metrics, unusual patterns)
        3. Degradation indicators
        4. Failure risk assessment
        5. Recommended preventive actions
        6. Urgency level (low/medium/high/critical)
        
        Format as JSON with keys: health_score, anomalies, degradation_indicators,
        risk_assessment, recommendations, urgency, reasoning
        """
        
        analysis = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert maintenance engineer with deep knowledge of industrial equipment diagnostics and predictive maintenance.",
            temperature=0.3
        )
        
        return analysis

    async def _predict_equipment_failure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Predict equipment failure probability and timing."""
        
        equipment_id = context.get("equipment_id")
        
        # Get equipment data
        telemetry = await get_equipment_telemetry(equipment_id, hours=168)  # 1 week
        history = await get_maintenance_history(equipment_id, days=180)  # 6 months
        
        # ML-based failure prediction
        prediction = await predict_equipment_failure(
            equipment_id=equipment_id,
            telemetry_data=telemetry,
            history=history
        )
        
        # Calculate RUL
        rul = await calculate_remaining_useful_life(
            equipment_id=equipment_id,
            current_condition=telemetry,
            usage_pattern=history
        )
        
        # Identify failure indicators
        failure_indicators = self._identify_failure_indicators(telemetry, history)
        
        # Generate maintenance recommendation
        if prediction["probability"] >= self.failure_threshold:
            recommendation = await self._generate_maintenance_recommendation(
                equipment_id,
                prediction,
                rul,
                failure_indicators
            )
        else:
            recommendation = {
                "action": "continue_monitoring",
                "reason": "Failure probability below threshold"
            }
        
        return {
            "equipment_id": equipment_id,
            "failure_prediction": {
                "probability": prediction["probability"],
                "predicted_failure_date": prediction.get("predicted_date"),
                "confidence": prediction.get("confidence", 0.8),
                "failure_mode": prediction.get("failure_mode", "Unknown")
            },
            "remaining_useful_life": rul,
            "failure_indicators": failure_indicators,
            "recommendation": recommendation,
            "requires_action": prediction["probability"] >= self.failure_threshold,
            "timestamp": datetime.utcnow().isoformat()
        }

    def _identify_failure_indicators(
        self,
        telemetry: Dict[str, Any],
        history: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Identify specific indicators of impending failure."""
        
        indicators = []
        
        # Temperature anomalies
        temp_data = telemetry.get("temperature", {})
        if temp_data.get("max", 0) > temp_data.get("normal_max", 100):
            indicators.append({
                "indicator": "Temperature Spike",
                "severity": "high",
                "value": temp_data.get("max"),
                "threshold": temp_data.get("normal_max"),
                "description": "Temperature exceeded normal operating range"
            })
        
        # Vibration increase
        vib_data = telemetry.get("vibration", {})
        if vib_data.get("trend") == "increasing":
            indicators.append({
                "indicator": "Increasing Vibration",
                "severity": "medium",
                "trend": "upward",
                "description": "Vibration levels trending upward, possible bearing wear"
            })
        
        # Performance degradation
        efficiency = telemetry.get("efficiency_pct", 100)
        if efficiency < 85:
            indicators.append({
                "indicator": "Performance Degradation",
                "severity": "medium",
                "value": efficiency,
                "threshold": 85,
                "description": f"Operating efficiency at {efficiency}%, below optimal"
            })
        
        # Error codes
        error_codes = telemetry.get("error_codes", [])
        if error_codes:
            indicators.append({
                "indicator": "Error Codes",
                "severity": "high",
                "codes": error_codes,
                "description": f"Active error codes: {', '.join(error_codes)}"
            })
        
        # Frequent repairs
        if history.get("repair_frequency", 0) > 2:  # More than 2 repairs in period
            indicators.append({
                "indicator": "Frequent Repairs",
                "severity": "high",
                "count": history.get("repair_frequency"),
                "description": "Equipment requiring frequent repairs, possible systemic issue"
            })
        
        return indicators

    async def _generate_maintenance_recommendation(
        self,
        equipment_id: str,
        prediction: Dict[str, Any],
        rul: Dict[str, Any],
        indicators: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate specific maintenance recommendation using LLM."""
        
        prompt = f"""
        Generate a maintenance recommendation for equipment {equipment_id}.
        
        Failure Prediction:
        - Probability: {prediction['probability']:.1%}
        - Predicted Date: {prediction.get('predicted_date', 'Unknown')}
        - Failure Mode: {prediction.get('failure_mode', 'Unknown')}
        
        Remaining Useful Life: {rul['days']} days
        
        Failure Indicators:
        {indicators}
        
        Provide:
        1. Recommended maintenance action (inspect, service, replace)
        2. Urgency timeline (immediate, within 24h, within week)
        3. Specific tasks to perform
        4. Required spare parts
        5. Estimated downtime
        6. Risk if deferred
        
        Format as JSON.
        """
        
        recommendation = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are a maintenance planning expert.",
            temperature=0.3
        )
        
        return recommendation

    async def _schedule_preventive_maintenance(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Schedule preventive maintenance for equipment."""
        
        equipment_id = context.get("equipment_id")
        maintenance_type = context.get("maintenance_type", "routine")
        preferred_date = context.get("preferred_date")
        
        # Check spare parts availability
        spare_parts = await get_spare_parts_availability(equipment_id, maintenance_type)
        
        # Find optimal maintenance window
        optimal_window = await self._find_optimal_maintenance_window(
            equipment_id,
            preferred_date,
            self.maintenance_window_hours
        )
        
        # Create work order
        work_order = await create_work_order(
            equipment_id=equipment_id,
            maintenance_type=maintenance_type,
            scheduled_date=optimal_window["start_time"],
            estimated_duration_hours=optimal_window["duration"],
            spare_parts_needed=spare_parts["required_parts"]
        )
        
        # Schedule the maintenance
        schedule_result = await schedule_maintenance(
            work_order_id=work_order["id"],
            equipment_id=equipment_id,
            start_time=optimal_window["start_time"],
            end_time=optimal_window["end_time"]
        )
        
        return {
            "equipment_id": equipment_id,
            "work_order": work_order,
            "scheduled_window": optimal_window,
            "spare_parts": spare_parts,
            "schedule_result": schedule_result,
            "notifications_sent": True,
            "status": "scheduled",
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _find_optimal_maintenance_window(
        self,
        equipment_id: str,
        preferred_date: Optional[datetime],
        duration_hours: float
    ) -> Dict[str, Any]:
        """Find optimal time window for maintenance to minimize disruption."""
        
        # TODO: Integrate with operations schedule, demand forecast
        # For now, return simplified window
        
        if preferred_date:
            start_time = preferred_date
        else:
            # Schedule for next available low-demand period
            start_time = datetime.utcnow() + timedelta(days=2)
            # Set to overnight (2 AM)
            start_time = start_time.replace(hour=2, minute=0, second=0, microsecond=0)
        
        end_time = start_time + timedelta(hours=duration_hours)
        
        return {
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration": duration_hours,
            "reason": "Low demand period, minimal operational impact",
            "alternative_windows": []  # Could provide alternatives
        }

    async def _diagnose_equipment_failure(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Perform root cause analysis for equipment failure."""
        
        equipment_id = context.get("equipment_id")
        failure_description = context.get("failure_description", "")
        
        # Get relevant data
        telemetry = await get_equipment_telemetry(equipment_id, hours=48)
        history = await get_maintenance_history(equipment_id, days=180)
        specs = await get_equipment_specs(equipment_id)
        
        # LLM-based root cause analysis
        prompt = f"""
        Perform root cause analysis for equipment failure.
        
        Equipment: {equipment_id}
        Type: {specs.get('type')}
        Model: {specs.get('model')}
        
        Failure Description:
        {failure_description}
        
        Recent Telemetry (48 hours before failure):
        {telemetry}
        
        Maintenance History:
        {history}
        
        Provide:
        1. Most likely root cause
        2. Contributing factors
        3. Failure sequence (what happened first, second, etc.)
        4. Similar historical failures
        5. Preventive measures for future
        6. Recommended corrective actions
        
        Format as JSON with keys: root_cause, contributing_factors, failure_sequence,
        similar_failures, preventive_measures, corrective_actions, confidence
        """
        
        diagnosis = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert in equipment failure analysis and root cause determination.",
            temperature=0.3
        )
        
        return {
            "equipment_id": equipment_id,
            "diagnosis": diagnosis,
            "analysis_date": datetime.utcnow().isoformat(),
            "recommended_next_steps": self._generate_next_steps(diagnosis)
        }

    def _generate_next_steps(self, diagnosis: Dict[str, Any]) -> List[str]:
        """Generate actionable next steps from diagnosis."""
        
        next_steps = []
        
        # Add corrective actions
        for action in diagnosis.get("corrective_actions", []):
            next_steps.append(f"CORRECTIVE: {action}")
        
        # Add preventive measures
        for measure in diagnosis.get("preventive_measures", []):
            next_steps.append(f"PREVENTIVE: {measure}")
        
        # Add investigation tasks
        if diagnosis.get("confidence", 1.0) < 0.8:
            next_steps.append("INVESTIGATE: Confidence below 80%, perform additional diagnostics")
        
        return next_steps

    async def _optimize_maintenance_schedule(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize maintenance schedule across multiple equipment."""
        
        location = context.get("location", "all")
        time_horizon_days = context.get("time_horizon_days", 30)
        
        # TODO: Get all equipment at location and their maintenance needs
        # TODO: Optimize schedule considering:
        # - Operational constraints
        # - Technician availability
        # - Spare parts availability
        # - Cost optimization
        # - Risk minimization
        
        optimized_schedule = {
            "location": location,
            "time_horizon_days": time_horizon_days,
            "scheduled_maintenance": [
                {
                    "equipment_id": "EQ-001",
                    "maintenance_type": "preventive",
                    "scheduled_date": (datetime.utcnow() + timedelta(days=5)).isoformat(),
                    "priority": "high",
                    "estimated_cost": 1200
                }
            ],
            "optimization_metrics": {
                "total_downtime_hours": 12,
                "total_cost": 8500,
                "risk_reduction_pct": 85,
                "resource_utilization_pct": 78
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return optimized_schedule

    async def _plan_spare_parts(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Plan spare parts inventory based on predictive maintenance."""
        
        time_horizon_days = context.get("time_horizon_days", 90)
        location = context.get("location")
        
        # TODO: Analyze predicted failures and required parts
        # TODO: Optimize spare parts inventory
        
        parts_plan = {
            "time_horizon_days": time_horizon_days,
            "location": location,
            "recommended_stock": [
                {
                    "part_id": "PART-001",
                    "part_name": "Conveyor Belt Motor",
                    "current_stock": 2,
                    "recommended_stock": 4,
                    "expected_usage": 3,
                    "lead_time_days": 14,
                    "unit_cost": 450,
                    "total_cost": 900
                }
            ],
            "total_investment": 15000,
            "expected_savings": 8000,
            "risk_mitigation": "Prevents emergency orders and extended downtime",
            "timestamp": datetime.utcnow().isoformat()
        }
        
        return parts_plan

    def _determine_health_status(
        self,
        health_analysis: Dict[str, Any],
        failure_prediction: Dict[str, Any],
        rul: Dict[str, Any]
    ) -> str:
        """Determine overall equipment health status."""
        
        health_score = health_analysis.get("health_score", 100)
        failure_prob = failure_prediction.get("probability", 0)
        rul_days = rul.get("days", 365)
        
        # Critical conditions
        if failure_prob > 0.80 or rul_days < 3:
            return "critical"
        
        # Poor health
        if failure_prob > 0.70 or rul_days < 7 or health_score < 50:
            return "poor"
        
        # Fair health
        if failure_prob > 0.50 or rul_days < 30 or health_score < 70:
            return "fair"
        
        # Good health
        if health_score < 85:
            return "good"
        
        # Excellent health
        return "excellent"

    def _calculate_urgency(
        self,
        failure_prediction: Dict[str, Any],
        rul: Dict[str, Any]
    ) -> str:
        """Calculate maintenance urgency level."""
        
        failure_prob = failure_prediction.get("probability", 0)
        rul_days = rul.get("days", 365)
        
        if failure_prob > 0.90 or rul_days < 2:
            return "immediate"
        
        if failure_prob > 0.80 or rul_days < 7:
            return "urgent"
        
        if failure_prob > 0.70 or rul_days < 14:
            return "high"
        
        if failure_prob > 0.50 or rul_days < 30:
            return "medium"
        
        return "low"
