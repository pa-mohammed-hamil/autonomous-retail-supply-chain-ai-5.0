"""
Automatic Stock Update Agent
Automatically updates inventory and completes stocking tasks in real-time.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.auto_stock_tools import (
    detect_stock_change,
    update_inventory_quantity,
    create_stock_task,
    complete_stock_task,
    verify_stock_completion,
    get_pending_stock_tasks,
    auto_reconcile_inventory,
    trigger_replenishment
)


class AutoStockAgent(BaseAgent):
    """
    Autonomous agent for automatic stock updates and task completion.
    
    Features:
    - Real-time stock change detection
    - Automatic inventory updates
    - Auto-complete stocking tasks
    - Barcode/RFID integration
    - Stock reconciliation
    - Exception handling
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="AutoStockAgent",
            role="automatic_stock_management",
            llm_client=llm_client,
            **kwargs
        )
        self.auto_complete_threshold = 0.95  # 95% confidence for auto-complete

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute automatic stock management workflow."""
        self.log_execution_start(context)
        
        action = context.get("action", "process_stock_event")
        
        try:
            if action == "process_stock_event":
                result = await self._process_stock_event(context)
            elif action == "auto_complete_tasks":
                result = await self._auto_complete_pending_tasks(context)
            elif action == "reconcile_inventory":
                result = await self._reconcile_inventory(context)
            elif action == "process_barcode_scan":
                result = await self._process_barcode_scan(context)
            elif action == "bulk_update":
                result = await self._bulk_stock_update(context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Auto stock agent execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _process_stock_event(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process stock change event and auto-update inventory."""
        
        event_type = context.get("event_type")  # received, sold, damaged, returned
        product_id = context.get("product_id")
        quantity_change = context.get("quantity_change", 0)
        location = context.get("location")
        store_id = context.get("store_id")
        scan_data = context.get("scan_data", {})
        
        # Detect and validate stock change
        validation = await detect_stock_change(
            product_id=product_id,
            quantity_change=quantity_change,
            location=location,
            scan_data=scan_data
        )
        
        if not validation["valid"]:
            return {
                "status": "validation_failed",
                "reason": validation["reason"],
                "requires_manual_review": True
            }
        
        # Update inventory automatically
        update_result = await update_inventory_quantity(
            product_id=product_id,
            quantity_change=quantity_change,
            location=location,
            store_id=store_id,
            event_type=event_type,
            auto_updated=True
        )
        
        # Find and complete related stock task
        task_result = await self._find_and_complete_related_task(
            product_id=product_id,
            location=location,
            quantity_change=quantity_change,
            event_type=event_type
        )
        
        # Check if replenishment needed
        replenishment_check = await self._check_replenishment_trigger(
            product_id=product_id,
            new_quantity=update_result["new_quantity"],
            store_id=store_id
        )
        
        return {
            "status": "completed",
            "event_type": event_type,
            "product_id": product_id,
            "quantity_change": quantity_change,
            "inventory_update": update_result,
            "task_completion": task_result,
            "replenishment_triggered": replenishment_check["triggered"],
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _find_and_complete_related_task(
        self,
        product_id: str,
        location: str,
        quantity_change: int,
        event_type: str
    ) -> Dict[str, Any]:
        """Find and auto-complete related stocking task."""
        
        # Get pending tasks for this product/location
        pending_tasks = await get_pending_stock_tasks(
            product_id=product_id,
            location=location
        )
        
        if not pending_tasks:
            return {
                "task_found": False,
                "message": "No pending task to complete"
            }
        
        # Find matching task
        matching_task = None
        for task in pending_tasks:
            if self._task_matches_event(task, event_type, quantity_change):
                matching_task = task
                break
        
        if not matching_task:
            return {
                "task_found": False,
                "message": f"No task matches event type: {event_type}"
            }
        
        # Verify completion
        verification = await verify_stock_completion(
            task_id=matching_task["task_id"],
            actual_quantity=abs(quantity_change),
            expected_quantity=matching_task["quantity"]
        )
        
        # Auto-complete if verified
        if verification["verified"] and verification["confidence"] >= self.auto_complete_threshold:
            completion_result = await complete_stock_task(
                task_id=matching_task["task_id"],
                completed_by="auto_stock_agent",
                verification_data=verification,
                auto_completed=True
            )
            
            return {
                "task_found": True,
                "task_completed": True,
                "task_id": matching_task["task_id"],
                "completion_result": completion_result,
                "confidence": verification["confidence"]
            }
        else:
            return {
                "task_found": True,
                "task_completed": False,
                "reason": "Verification confidence below threshold",
                "requires_manual_verification": True,
                "task_id": matching_task["task_id"]
            }

    def _task_matches_event(
        self,
        task: Dict[str, Any],
        event_type: str,
        quantity_change: int
    ) -> bool:
        """Check if task matches stock event."""
        
        task_type = task.get("task_type")
        
        # Match task type to event type
        matches = {
            "received": ["receiving", "putaway"],
            "sold": ["pick", "fulfillment"],
            "returned": ["returns_processing"],
            "damaged": ["damage_assessment"]
        }
        
        if task_type not in matches.get(event_type, []):
            return False
        
        # Check quantity matches (within tolerance)
        expected_qty = task.get("quantity", 0)
        actual_qty = abs(quantity_change)
        tolerance = 0.05  # 5% tolerance
        
        return abs(actual_qty - expected_qty) <= (expected_qty * tolerance)

    async def _check_replenishment_trigger(
        self,
        product_id: str,
        new_quantity: int,
        store_id: str
    ) -> Dict[str, Any]:
        """Check if stock level triggers replenishment."""
        
        should_trigger = await trigger_replenishment(
            product_id=product_id,
            current_quantity=new_quantity,
            store_id=store_id
        )
        
        return should_trigger

    async def _auto_complete_pending_tasks(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Auto-complete all eligible pending stock tasks."""
        
        store_id = context.get("store_id")
        location = context.get("location")
        time_threshold_minutes = context.get("time_threshold", 60)
        
        # Get all pending tasks
        pending_tasks = await get_pending_stock_tasks(
            store_id=store_id,
            location=location,
            older_than_minutes=time_threshold_minutes
        )
        
        completed_tasks = []
        failed_tasks = []
        
        for task in pending_tasks:
            # Check if task can be auto-completed
            can_complete = await self._can_auto_complete_task(task)
            
            if can_complete["eligible"]:
                try:
                    # Complete the task
                    result = await complete_stock_task(
                        task_id=task["task_id"],
                        completed_by="auto_stock_agent",
                        verification_data=can_complete["verification"],
                        auto_completed=True
                    )
                    
                    completed_tasks.append({
                        "task_id": task["task_id"],
                        "product_id": task["product_id"],
                        "result": result
                    })
                except Exception as e:
                    failed_tasks.append({
                        "task_id": task["task_id"],
                        "error": str(e)
                    })
        
        return {
            "status": "completed",
            "tasks_processed": len(pending_tasks),
            "tasks_completed": len(completed_tasks),
            "tasks_failed": len(failed_tasks),
            "completed_tasks": completed_tasks,
            "failed_tasks": failed_tasks,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _can_auto_complete_task(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Determine if task can be auto-completed."""
        
        # Check task age
        task_age_minutes = (
            datetime.utcnow() - datetime.fromisoformat(task["created_at"])
        ).total_seconds() / 60
        
        # Check if task has been started
        if task.get("status") != "in_progress":
            return {"eligible": False, "reason": "Task not in progress"}
        
        # Check if assigned employee checked in recently
        last_checkin = task.get("last_employee_checkin")
        if last_checkin:
            checkin_age = (
                datetime.utcnow() - datetime.fromisoformat(last_checkin)
            ).total_seconds() / 60
            
            if checkin_age > 15:  # No activity for 15+ minutes
                # Verify stock was actually updated
                verification = await verify_stock_completion(
                    task_id=task["task_id"],
                    actual_quantity=None,  # Check from inventory
                    expected_quantity=task["quantity"]
                )
                
                if verification["verified"]:
                    return {
                        "eligible": True,
                        "reason": "Stock verified, task appears complete",
                        "verification": verification
                    }
        
        return {"eligible": False, "reason": "No verification available"}

    async def _reconcile_inventory(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Automatically reconcile inventory discrepancies."""
        
        store_id = context.get("store_id")
        location = context.get("location")
        reconciliation_type = context.get("type", "daily")  # daily, weekly, cycle_count
        
        # Perform auto-reconciliation
        reconciliation_result = await auto_reconcile_inventory(
            store_id=store_id,
            location=location,
            reconciliation_type=reconciliation_type
        )
        
        # Auto-adjust small discrepancies
        auto_adjusted = []
        requires_review = []
        
        for discrepancy in reconciliation_result["discrepancies"]:
            variance_pct = abs(discrepancy["variance"]) / discrepancy["expected"] * 100
            
            if variance_pct <= 2:  # Auto-adjust up to 2% variance
                adjustment_result = await update_inventory_quantity(
                    product_id=discrepancy["product_id"],
                    quantity_change=discrepancy["variance"],
                    location=location,
                    store_id=store_id,
                    event_type="reconciliation_adjustment",
                    auto_updated=True
                )
                
                auto_adjusted.append({
                    "product_id": discrepancy["product_id"],
                    "variance": discrepancy["variance"],
                    "adjustment": adjustment_result
                })
            else:
                requires_review.append(discrepancy)
        
        return {
            "status": "completed",
            "reconciliation_type": reconciliation_type,
            "total_discrepancies": len(reconciliation_result["discrepancies"]),
            "auto_adjusted_count": len(auto_adjusted),
            "requires_review_count": len(requires_review),
            "auto_adjusted": auto_adjusted,
            "requires_review": requires_review,
            "accuracy_pct": reconciliation_result["accuracy_pct"],
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _process_barcode_scan(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process barcode/RFID scan for automatic stock update."""
        
        barcode = context.get("barcode")
        scan_location = context.get("scan_location")
        store_id = context.get("store_id")
        scanner_id = context.get("scanner_id")
        
        # Lookup product from barcode
        from ai.tools.product_tools import get_product_by_barcode
        product = await get_product_by_barcode(barcode)
        
        if not product:
            return {
                "status": "error",
                "message": f"Product not found for barcode: {barcode}"
            }
        
        # Determine scan intent (receiving, picking, cycle count)
        scan_intent = await self._determine_scan_intent(
            product_id=product["product_id"],
            scan_location=scan_location,
            scanner_id=scanner_id
        )
        
        # Process based on intent
        if scan_intent["intent"] == "receiving":
            result = await self._process_stock_event({
                "event_type": "received",
                "product_id": product["product_id"],
                "quantity_change": 1,  # Assume 1 unit per scan
                "location": scan_location,
                "store_id": store_id,
                "scan_data": {"barcode": barcode, "scanner_id": scanner_id}
            })
        elif scan_intent["intent"] == "picking":
            result = await self._process_stock_event({
                "event_type": "sold",
                "product_id": product["product_id"],
                "quantity_change": -1,
                "location": scan_location,
                "store_id": store_id,
                "scan_data": {"barcode": barcode, "scanner_id": scanner_id}
            })
        elif scan_intent["intent"] == "cycle_count":
            result = {
                "status": "cycle_count_recorded",
                "product_id": product["product_id"],
                "location": scan_location,
                "message": "Scan recorded for cycle count"
            }
        else:
            result = {
                "status": "unknown_intent",
                "message": "Could not determine scan intent"
            }
        
        return {
            **result,
            "barcode": barcode,
            "product": product,
            "scan_intent": scan_intent
        }

    async def _determine_scan_intent(
        self,
        product_id: str,
        scan_location: str,
        scanner_id: str
    ) -> Dict[str, Any]:
        """Determine intent of barcode scan."""
        
        # Check scanner location/type
        if "receiving" in scan_location.lower():
            return {"intent": "receiving", "confidence": 0.95}
        elif "shipping" in scan_location.lower() or "fulfillment" in scan_location.lower():
            return {"intent": "picking", "confidence": 0.95}
        elif "cycle" in scan_location.lower():
            return {"intent": "cycle_count", "confidence": 0.95}
        
        # Check for active tasks
        active_tasks = await get_pending_stock_tasks(
            product_id=product_id,
            location=scan_location
        )
        
        if active_tasks:
            task_type = active_tasks[0].get("task_type")
            if task_type in ["receiving", "putaway"]:
                return {"intent": "receiving", "confidence": 0.85}
            elif task_type in ["pick", "fulfillment"]:
                return {"intent": "picking", "confidence": 0.85}
        
        return {"intent": "unknown", "confidence": 0.0}

    async def _bulk_stock_update(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process bulk stock updates from external system."""
        
        updates = context.get("updates", [])
        store_id = context.get("store_id")
        source_system = context.get("source", "external")
        
        processed = []
        failed = []
        
        for update in updates:
            try:
                result = await self._process_stock_event({
                    "event_type": update.get("event_type", "adjustment"),
                    "product_id": update["product_id"],
                    "quantity_change": update["quantity_change"],
                    "location": update.get("location"),
                    "store_id": store_id,
                    "scan_data": {"source": source_system}
                })
                
                processed.append({
                    "product_id": update["product_id"],
                    "result": result
                })
            except Exception as e:
                failed.append({
                    "product_id": update["product_id"],
                    "error": str(e)
                })
        
        return {
            "status": "completed",
            "total_updates": len(updates),
            "processed": len(processed),
            "failed": len(failed),
            "processed_updates": processed,
            "failed_updates": failed,
            "timestamp": datetime.utcnow().isoformat()
        }
