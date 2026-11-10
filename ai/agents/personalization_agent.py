"""
Personalized Customer Experience Agent
Delivers hyper-personalized shopping experiences using AI-driven recommendations and real-time personalization.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.personalization_tools import (
    get_customer_profile,
    get_customer_behavior,
    get_product_recommendations,
    get_customer_segments,
    calculate_customer_lifetime_value,
    predict_next_purchase,
    generate_personalized_content,
    track_customer_journey,
    get_similar_customers
)


class PersonalizationAgent(BaseAgent):
    """
    Autonomous agent for personalized customer experience optimization.
    
    Features:
    - Real-time product recommendations
    - Dynamic content personalization
    - Customer journey optimization
    - Predictive engagement timing
    - Churn prevention
    - Loyalty program optimization
    - Omnichannel personalization
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="PersonalizationAgent",
            role="customer_personalization",
            llm_client=llm_client,
            **kwargs
        )
        self.recommendation_limit = 10
        self.personalization_threshold = 0.6  # Minimum confidence for personalization

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute personalization workflow."""
        self.log_execution_start(context)
        
        action = context.get("action", "recommend_products")
        
        try:
            if action == "recommend_products":
                result = await self._generate_product_recommendations(context)
            elif action == "personalize_content":
                result = await self._personalize_content(context)
            elif action == "optimize_journey":
                result = await self._optimize_customer_journey(context)
            elif action == "predict_churn":
                result = await self._predict_churn_risk(context)
            elif action == "segment_customer":
                result = await self._segment_customer(context)
            elif action == "calculate_clv":
                result = await self._calculate_lifetime_value(context)
            elif action == "next_best_action":
                result = await self._determine_next_best_action(context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Personalization agent execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _generate_product_recommendations(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Generate personalized product recommendations."""
        
        customer_id = context.get("customer_id")
        session_context = context.get("session_context", {})
        channel = context.get("channel", "web")  # web, mobile, email, in-store
        
        # Gather customer intelligence
        profile, behavior = await asyncio.gather(
            get_customer_profile(customer_id),
            get_customer_behavior(customer_id, days=90)
        )
        
        # Get base recommendations from ML model
        recommendations = await get_product_recommendations(
            customer_id=customer_id,
            profile=profile,
            behavior=behavior,
            session_context=session_context,
            limit=self.recommendation_limit * 2  # Get more for filtering
        )
        
        # Enhance recommendations with LLM reasoning
        enhanced_recommendations = await self._enhance_recommendations(
            recommendations,
            profile,
            behavior,
            session_context
        )
        
        # Personalize recommendation presentation
        presentation = await self._personalize_recommendation_display(
            enhanced_recommendations,
            channel,
            profile
        )
        
        return {
            "customer_id": customer_id,
            "recommendations": enhanced_recommendations[:self.recommendation_limit],
            "presentation": presentation,
            "reasoning": {
                "primary_factors": self._identify_recommendation_factors(profile, behavior),
                "customer_segment": profile.get("segment"),
                "confidence": enhanced_recommendations[0].get("confidence", 0) if enhanced_recommendations else 0
            },
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _enhance_recommendations(
        self,
        recommendations: List[Dict[str, Any]],
        profile: Dict[str, Any],
        behavior: Dict[str, Any],
        session_context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Enhance ML recommendations with LLM reasoning."""
        
        # Create context for LLM
        prompt = f"""
        Enhance and explain these product recommendations for a customer.
        
        Customer Profile:
        - Segment: {profile.get('segment', 'Unknown')}
        - Age Group: {profile.get('age_group', 'Unknown')}
        - Preferences: {profile.get('preferences', [])}
        - Purchase History: {behavior.get('total_purchases', 0)} orders, ${behavior.get('total_spent', 0):.2f} spent
        - Favorite Categories: {behavior.get('favorite_categories', [])}
        - Last Purchase: {behavior.get('last_purchase_date', 'Never')}
        
        Current Session Context:
        - Current Page: {session_context.get('current_page', 'homepage')}
        - Viewed Products: {session_context.get('viewed_products', [])}
        - Cart Items: {session_context.get('cart_items', [])}
        
        Candidate Recommendations:
        {recommendations[:20]}  # Top 20 candidates
        
        For each recommendation, provide:
        1. Relevance score (0-1)
        2. Personalized reason ("Because you...")
        3. Urgency factor (low/medium/high)
        4. Cross-sell/upsell opportunities
        
        Rank and return top {self.recommendation_limit} recommendations.
        Format as JSON array with keys: product_id, name, relevance_score, reason, urgency, related_products
        """
        
        enhanced = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert e-commerce personalization specialist with deep understanding of customer psychology and buying behavior.",
            temperature=0.4
        )
        
        return enhanced

    def _identify_recommendation_factors(
        self,
        profile: Dict[str, Any],
        behavior: Dict[str, Any]
    ) -> List[str]:
        """Identify key factors driving recommendations."""
        
        factors = []
        
        if behavior.get("total_purchases", 0) > 10:
            factors.append("Purchase History")
        
        if behavior.get("favorite_categories"):
            factors.append("Category Preferences")
        
        if profile.get("browsing_patterns"):
            factors.append("Browsing Behavior")
        
        if behavior.get("seasonal_patterns"):
            factors.append("Seasonal Trends")
        
        if profile.get("demographic_segment"):
            factors.append("Demographic Match")
        
        return factors[:3]  # Top 3 factors

    async def _personalize_recommendation_display(
        self,
        recommendations: List[Dict[str, Any]],
        channel: str,
        profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Personalize how recommendations are displayed."""
        
        # Adapt presentation to channel and customer
        if channel == "email":
            layout = "grid_2x3"
            title = f"Picked Just for You, {profile.get('first_name', 'Valued Customer')}"
            cta = "Shop Now"
        elif channel == "mobile":
            layout = "carousel"
            title = "You Might Love These"
            cta = "View"
        elif channel == "in_store":
            layout = "kiosk_fullscreen"
            title = "Recommended for You"
            cta = "Add to Cart"
        else:  # web
            layout = "grid_4x2"
            title = "Recommended For You"
            cta = "Quick View"
        
        return {
            "layout": layout,
            "title": title,
            "subtitle": self._generate_subtitle(profile, recommendations),
            "call_to_action": cta,
            "urgency_indicators": self._should_show_urgency(profile),
            "social_proof": self._should_show_social_proof(profile)
        }

    def _generate_subtitle(
        self,
        profile: Dict[str, Any],
        recommendations: List[Dict[str, Any]]
    ) -> str:
        """Generate personalized subtitle."""
        
        if profile.get("segment") == "high_value":
            return "Curated selections for our VIP members"
        elif profile.get("recency") == "new":
            return "Popular items our customers love"
        else:
            return "Based on your browsing and shopping history"

    def _should_show_urgency(self, profile: Dict[str, Any]) -> bool:
        """Determine if urgency indicators should be shown."""
        return profile.get("responds_to_urgency", False)

    def _should_show_social_proof(self, profile: Dict[str, Any]) -> bool:
        """Determine if social proof should be shown."""
        return profile.get("segment") != "early_adopter"

    async def _personalize_content(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Personalize website/app content for customer."""
        
        customer_id = context.get("customer_id")
        page_type = context.get("page_type", "homepage")
        
        # Get customer data
        profile = await get_customer_profile(customer_id)
        behavior = await get_customer_behavior(customer_id, days=30)
        
        # Generate personalized content using LLM
        personalized_content = await generate_personalized_content(
            customer_id=customer_id,
            page_type=page_type,
            profile=profile,
            behavior=behavior
        )
        
        # Optimize content presentation
        content_optimization = await self._optimize_content_presentation(
            personalized_content,
            profile
        )
        
        return {
            "customer_id": customer_id,
            "page_type": page_type,
            "content": personalized_content,
            "optimization": content_optimization,
            "ab_test_variant": self._assign_ab_test_variant(customer_id, profile),
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _optimize_content_presentation(
        self,
        content: Dict[str, Any],
        profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Optimize content presentation based on customer preferences."""
        
        return {
            "hero_banner": {
                "image_style": "lifestyle" if profile.get("prefers_lifestyle") else "product",
                "message_tone": "aspirational" if profile.get("segment") == "premium" else "value-focused"
            },
            "category_highlights": self._prioritize_categories(profile),
            "promotional_banners": self._select_promotions(profile),
            "content_density": "minimal" if profile.get("mobile_primary") else "rich"
        }

    def _prioritize_categories(self, profile: Dict[str, Any]) -> List[str]:
        """Prioritize category display based on preferences."""
        
        favorite_categories = profile.get("favorite_categories", [])
        trending_categories = profile.get("trending_interests", [])
        
        # Combine with 70% weight on favorites, 30% on trending
        prioritized = []
        prioritized.extend(favorite_categories[:3])
        prioritized.extend([c for c in trending_categories if c not in prioritized][:2])
        
        return prioritized[:5]

    def _select_promotions(self, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Select most relevant promotions for customer."""
        
        promotions = []
        
        if profile.get("responds_to_discounts"):
            promotions.append({
                "type": "percentage_off",
                "message": "Exclusive: Save 20% on Your Favorites"
            })
        
        if profile.get("loyalty_member"):
            promotions.append({
                "type": "loyalty_points",
                "message": "Double Points on All Purchases Today"
            })
        
        if profile.get("cart_abandoner"):
            promotions.append({
                "type": "free_shipping",
                "message": "Free Shipping on Orders Over $50"
            })
        
        return promotions[:2]

    def _assign_ab_test_variant(
        self,
        customer_id: str,
        profile: Dict[str, Any]
    ) -> str:
        """Assign customer to A/B test variant."""
        
        # Simple hash-based assignment
        hash_val = hash(customer_id) % 100
        
        if hash_val < 50:
            return "control"
        else:
            return "variant_a"

    async def _optimize_customer_journey(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize customer journey based on behavior patterns."""
        
        customer_id = context.get("customer_id")
        
        # Track current journey
        journey = await track_customer_journey(customer_id)
        
        # Identify journey stage
        stage = self._identify_journey_stage(journey)
        
        # Generate stage-specific optimizations
        optimizations = await self._generate_journey_optimizations(
            customer_id,
            stage,
            journey
        )
        
        return {
            "customer_id": customer_id,
            "current_stage": stage,
            "journey_map": journey,
            "optimizations": optimizations,
            "predicted_next_action": journey.get("predicted_next_action"),
            "intervention_opportunities": self._identify_interventions(journey, stage),
            "timestamp": datetime.utcnow().isoformat()
        }

    def _identify_journey_stage(self, journey: Dict[str, Any]) -> str:
        """Identify current stage in customer journey."""
        
        if journey.get("is_new_visitor"):
            return "awareness"
        elif journey.get("browsing_count", 0) > 0 and journey.get("cart_count", 0) == 0:
            return "consideration"
        elif journey.get("cart_count", 0) > 0 and journey.get("purchase_count", 0) == 0:
            return "decision"
        elif journey.get("purchase_count", 0) > 0:
            return "retention"
        else:
            return "unknown"

    async def _generate_journey_optimizations(
        self,
        customer_id: str,
        stage: str,
        journey: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate optimizations for specific journey stage."""
        
        prompt = f"""
        Generate customer journey optimizations for a customer in the {stage} stage.
        
        Journey Data:
        - Stage: {stage}
        - Sessions: {journey.get('session_count', 0)}
        - Pages Viewed: {journey.get('pages_viewed', 0)}
        - Time on Site: {journey.get('total_time_minutes', 0)} minutes
        - Cart Value: ${journey.get('cart_value', 0):.2f}
        - Friction Points: {journey.get('friction_points', [])}
        
        Provide:
        1. Top 3 optimization actions
        2. Personalized messaging for each action
        3. Optimal timing for interventions
        4. Expected impact on conversion
        
        Format as JSON with keys: actions, messaging, timing, expected_impact
        """
        
        optimizations = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are a conversion rate optimization expert specializing in customer journey analytics.",
            temperature=0.3
        )
        
        return optimizations

    def _identify_interventions(
        self,
        journey: Dict[str, Any],
        stage: str
    ) -> List[Dict[str, Any]]:
        """Identify intervention opportunities to improve journey."""
        
        interventions = []
        
        # Cart abandonment
        if journey.get("cart_value", 0) > 50 and journey.get("minutes_since_cart_update", 0) > 30:
            interventions.append({
                "type": "cart_recovery",
                "timing": "immediate",
                "channel": "email",
                "message": "Complete your purchase - items in cart are going fast!",
                "incentive": "10% discount"
            })
        
        # Browse abandonment
        if journey.get("pages_viewed", 0) > 5 and journey.get("time_on_site_minutes", 0) < 2:
            interventions.append({
                "type": "engagement",
                "timing": "next_visit",
                "channel": "web_popup",
                "message": "Can we help you find something?",
                "action": "live_chat_offer"
            })
        
        # Post-purchase
        if journey.get("days_since_purchase", 0) == 7:
            interventions.append({
                "type": "feedback_request",
                "timing": "7_days_post_purchase",
                "channel": "email",
                "message": "How are you enjoying your purchase?",
                "incentive": "loyalty_points"
            })
        
        return interventions

    async def _predict_churn_risk(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Predict customer churn risk and recommend retention actions."""
        
        customer_id = context.get("customer_id")
        
        # Get customer data
        profile = await get_customer_profile(customer_id)
        behavior = await get_customer_behavior(customer_id, days=180)
        
        # Calculate churn indicators
        churn_indicators = self._calculate_churn_indicators(profile, behavior)
        
        # Predict churn probability
        churn_probability = self._calculate_churn_probability(churn_indicators)
        
        # Generate retention strategy
        if churn_probability > 0.5:
            retention_strategy = await self._generate_retention_strategy(
                customer_id,
                churn_probability,
                churn_indicators,
                profile
            )
        else:
            retention_strategy = {"status": "low_risk", "actions": []}
        
        return {
            "customer_id": customer_id,
            "churn_probability": churn_probability,
            "risk_level": self._classify_churn_risk(churn_probability),
            "churn_indicators": churn_indicators,
            "retention_strategy": retention_strategy,
            "estimated_clv_at_risk": profile.get("lifetime_value", 0) * churn_probability,
            "timestamp": datetime.utcnow().isoformat()
        }

    def _calculate_churn_indicators(
        self,
        profile: Dict[str, Any],
        behavior: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Calculate indicators of potential churn."""
        
        indicators = {
            "days_since_last_purchase": behavior.get("days_since_last_purchase", 999),
            "purchase_frequency_declining": behavior.get("purchase_trend", "") == "declining",
            "email_engagement_low": behavior.get("email_open_rate", 1.0) < 0.2,
            "support_tickets_increasing": behavior.get("support_ticket_trend", "") == "increasing",
            "discount_dependency": behavior.get("discount_purchase_pct", 0) > 0.8,
            "competitor_browsing": behavior.get("competitor_visits", 0) > 3
        }
        
        # Count active indicators
        indicators["active_indicators_count"] = sum(
            1 for v in indicators.values() if isinstance(v, bool) and v
        )
        
        return indicators

    def _calculate_churn_probability(self, indicators: Dict[str, Any]) -> float:
        """Calculate overall churn probability from indicators."""
        
        # Simple weighted scoring
        score = 0.0
        
        days_since_purchase = indicators.get("days_since_last_purchase", 0)
        if days_since_purchase > 180:
            score += 0.4
        elif days_since_purchase > 90:
            score += 0.2
        elif days_since_purchase > 60:
            score += 0.1
        
        if indicators.get("purchase_frequency_declining"):
            score += 0.2
        
        if indicators.get("email_engagement_low"):
            score += 0.15
        
        if indicators.get("support_tickets_increasing"):
            score += 0.1
        
        if indicators.get("discount_dependency"):
            score += 0.1
        
        if indicators.get("competitor_browsing"):
            score += 0.15
        
        return min(score, 1.0)

    def _classify_churn_risk(self, probability: float) -> str:
        """Classify churn risk level."""
        if probability < 0.3:
            return "low"
        elif probability < 0.5:
            return "medium"
        elif probability < 0.7:
            return "high"
        else:
            return "critical"

    async def _generate_retention_strategy(
        self,
        customer_id: str,
        churn_probability: float,
        indicators: Dict[str, Any],
        profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate personalized retention strategy."""
        
        prompt = f"""
        Generate a customer retention strategy for a high-risk churn customer.
        
        Churn Risk: {churn_probability:.1%}
        Customer Value: ${profile.get('lifetime_value', 0):.2f}
        Segment: {profile.get('segment', 'Unknown')}
        
        Churn Indicators:
        {indicators}
        
        Customer Preferences:
        {profile.get('preferences', {})}
        
        Generate:
        1. Top 3 retention actions (prioritized)
        2. Personalized messaging for each
        3. Incentives to offer (if any)
        4. Timeline for execution
        5. Success metrics
        
        Format as JSON.
        """
        
        strategy = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are a customer retention specialist with expertise in churn prevention and customer loyalty.",
            temperature=0.3
        )
        
        return strategy

    async def _segment_customer(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Segment customer for targeted campaigns."""
        
        customer_id = context.get("customer_id")
        
        # Get customer data
        profile = await get_customer_profile(customer_id)
        behavior = await get_customer_behavior(customer_id, days=365)
        
        # Get available segments
        segments = await get_customer_segments()
        
        # Assign to segments
        assigned_segments = self._assign_segments(profile, behavior, segments)
        
        # Find similar customers
        similar_customers = await get_similar_customers(customer_id, top_n=10)
        
        return {
            "customer_id": customer_id,
            "primary_segment": assigned_segments[0] if assigned_segments else None,
            "secondary_segments": assigned_segments[1:3],
            "segment_characteristics": self._describe_segments(assigned_segments),
            "similar_customers": similar_customers,
            "campaign_recommendations": self._recommend_campaigns(assigned_segments),
            "timestamp": datetime.utcnow().isoformat()
        }

    def _assign_segments(
        self,
        profile: Dict[str, Any],
        behavior: Dict[str, Any],
        segments: List[Dict[str, Any]]
    ) -> List[str]:
        """Assign customer to relevant segments."""
        
        assigned = []
        
        # RFM-based segments
        recency = behavior.get("days_since_last_purchase", 999)
        frequency = behavior.get("total_purchases", 0)
        monetary = behavior.get("total_spent", 0)
        
        if recency < 30 and frequency > 10 and monetary > 1000:
            assigned.append("champions")
        elif recency < 60 and monetary > 500:
            assigned.append("loyal_customers")
        elif recency > 180:
            assigned.append("at_risk")
        
        # Behavioral segments
        if behavior.get("average_order_value", 0) > 200:
            assigned.append("high_value")
        
        if behavior.get("discount_purchase_pct", 0) > 0.7:
            assigned.append("discount_seekers")
        
        if profile.get("mobile_sessions_pct", 0) > 0.8:
            assigned.append("mobile_first")
        
        return assigned

    def _describe_segments(self, segments: List[str]) -> Dict[str, str]:
        """Describe characteristics of assigned segments."""
        
        descriptions = {
            "champions": "Highest value customers who buy frequently and recently",
            "loyal_customers": "Regular buyers with consistent purchase patterns",
            "at_risk": "Previously engaged customers showing signs of disengagement",
            "high_value": "Customers with above-average order values",
            "discount_seekers": "Price-sensitive customers who primarily buy on promotion",
            "mobile_first": "Customers who primarily shop via mobile devices"
        }
        
        return {seg: descriptions.get(seg, "Unknown segment") for seg in segments}

    def _recommend_campaigns(self, segments: List[str]) -> List[Dict[str, Any]]:
        """Recommend marketing campaigns for segments."""
        
        campaigns = []
        
        if "at_risk" in segments:
            campaigns.append({
                "campaign": "win_back",
                "message": "We miss you! Here's 25% off your next order",
                "timing": "immediate",
                "channel": ["email", "sms"]
            })
        
        if "champions" in segments:
            campaigns.append({
                "campaign": "vip_exclusive",
                "message": "Early access to new arrivals - just for you",
                "timing": "weekly",
                "channel": ["email", "app_push"]
            })
        
        if "discount_seekers" in segments:
            campaigns.append({
                "campaign": "flash_sales",
                "message": "24-hour flash sale - up to 50% off",
                "timing": "bi_weekly",
                "channel": ["email", "sms"]
            })
        
        return campaigns

    async def _calculate_lifetime_value(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate customer lifetime value."""
        
        customer_id = context.get("customer_id")
        
        # Calculate CLV
        clv_result = await calculate_customer_lifetime_value(customer_id)
        
        return {
            "customer_id": customer_id,
            **clv_result,
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _determine_next_best_action(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Determine next best action for customer engagement."""
        
        customer_id = context.get("customer_id")
        
        # Get comprehensive customer data
        profile, behavior, journey = await asyncio.gather(
            get_customer_profile(customer_id),
            get_customer_behavior(customer_id, days=90),
            track_customer_journey(customer_id)
        )
        
        # Predict next purchase
        next_purchase = await predict_next_purchase(customer_id, profile, behavior)
        
        # Use LLM to determine best action
        prompt = f"""
        Determine the next best action for customer engagement.
        
        Customer Profile:
        - Segment: {profile.get('segment')}
        - CLV: ${profile.get('lifetime_value', 0):.2f}
        - Last Purchase: {behavior.get('days_since_last_purchase')} days ago
        
        Current Behavior:
        - Recent Activity: {behavior.get('recent_activity', 'None')}
        - Cart Value: ${journey.get('cart_value', 0):.2f}
        - Journey Stage: {self._identify_journey_stage(journey)}
        
        Next Purchase Prediction:
        - Predicted Date: {next_purchase.get('predicted_date')}
        - Predicted Category: {next_purchase.get('predicted_category')}
        - Confidence: {next_purchase.get('confidence', 0):.1%}
        
        Recommend the single best action to take right now, considering:
        1. Customer's current needs and interests
        2. Optimal timing for engagement
        3. Channel preference
        4. Expected impact on revenue/retention
        
        Format as JSON with keys: action, rationale, timing, channel, expected_impact
        """
        
        nba = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are a customer engagement specialist optimizing for both short-term conversion and long-term customer value.",
            temperature=0.3
        )
        
        return {
            "customer_id": customer_id,
            "next_best_action": nba,
            "next_purchase_prediction": next_purchase,
            "timestamp": datetime.utcnow().isoformat()
        }
