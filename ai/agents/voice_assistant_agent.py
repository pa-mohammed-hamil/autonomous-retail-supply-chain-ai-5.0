"""
Voice-Activated Store Assistant Agent
AI-powered voice assistant for in-store customer service and employee support.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
import asyncio

from ai.agents.base_agent import BaseAgent
from ai.llm.llm_client import LLMClient
from ai.tools.voice_assistant_tools import (
    get_product_information,
    search_products_by_voice,
    get_store_navigation,
    check_product_availability,
    get_store_hours,
    process_customer_request,
    get_employee_assistance,
    trigger_staff_alert,
    get_promotional_offers,
    process_voice_feedback
)


class VoiceAssistantAgent(BaseAgent):
    """
    Autonomous agent for voice-activated store assistance.
    
    Features:
    - Natural language product search
    - Store navigation assistance
    - Price and availability checks
    - Employee support requests
    - Promotional information
    - Multi-language support
    - Context-aware responses
    """

    def __init__(self, llm_client: LLMClient, **kwargs):
        super().__init__(
            name="VoiceAssistantAgent",
            role="voice_store_assistant",
            llm_client=llm_client,
            **kwargs
        )
        self.supported_languages = ["en", "es", "fr", "de", "zh", "ja"]
        self.conversation_context = {}

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute voice assistant workflow."""
        self.log_execution_start(context)
        
        action = context.get("action", "process_voice_query")
        
        try:
            if action == "process_voice_query":
                result = await self._process_voice_query(context)
            elif action == "product_search":
                result = await self._voice_product_search(context)
            elif action == "navigation_help":
                result = await self._provide_navigation(context)
            elif action == "employee_assistance":
                result = await self._handle_employee_request(context)
            elif action == "price_check":
                result = await self._check_price_availability(context)
            elif action == "promotions":
                result = await self._get_promotions(context)
            else:
                result = {"status": "error", "message": f"Unknown action: {action}"}
            
            self.log_execution_end(result)
            return result
            
        except Exception as e:
            self.logger.error(f"Voice assistant execution failed: {e}")
            return {"status": "error", "error": str(e)}

    async def _process_voice_query(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Process general voice query from customer or employee."""
        
        voice_input = context.get("voice_input", "")
        user_id = context.get("user_id")
        store_id = context.get("store_id")
        language = context.get("language", "en")
        user_type = context.get("user_type", "customer")  # customer or employee
        
        # Get or create conversation context
        session_id = context.get("session_id", f"session_{datetime.utcnow().timestamp()}")
        conversation_history = self.conversation_context.get(session_id, [])
        
        # Understand intent using LLM
        intent_analysis = await self._analyze_voice_intent(
            voice_input,
            conversation_history,
            user_type,
            language
        )
        
        # Route to appropriate handler
        if intent_analysis["intent"] == "product_search":
            response = await self._voice_product_search({
                "query": intent_analysis["extracted_query"],
                "store_id": store_id,
                "language": language
            })
        elif intent_analysis["intent"] == "navigation":
            response = await self._provide_navigation({
                "query": intent_analysis["extracted_query"],
                "store_id": store_id
            })
        elif intent_analysis["intent"] == "price_check":
            response = await self._check_price_availability({
                "product_name": intent_analysis.get("product_name"),
                "store_id": store_id
            })
        elif intent_analysis["intent"] == "employee_help":
            response = await self._handle_employee_request({
                "request": intent_analysis["extracted_query"],
                "store_id": store_id,
                "urgency": intent_analysis.get("urgency", "normal")
            })
        elif intent_analysis["intent"] == "store_info":
            response = await self._provide_store_information({
                "query": intent_analysis["extracted_query"],
                "store_id": store_id
            })
        elif intent_analysis["intent"] == "feedback":
            response = await self._handle_voice_feedback({
                "feedback": voice_input,
                "user_id": user_id,
                "store_id": store_id
            })
        else:
            response = await self._handle_general_query({
                "query": voice_input,
                "store_id": store_id,
                "language": language
            })
        
        # Update conversation history
        conversation_history.append({
            "user_input": voice_input,
            "intent": intent_analysis["intent"],
            "response": response.get("response_text"),
            "timestamp": datetime.utcnow().isoformat()
        })
        self.conversation_context[session_id] = conversation_history[-10:]  # Keep last 10
        
        return {
            "session_id": session_id,
            "intent": intent_analysis["intent"],
            "response": response,
            "conversation_context": conversation_history[-3:],  # Last 3 for context
            "timestamp": datetime.utcnow().isoformat()
        }

    async def _analyze_voice_intent(
        self,
        voice_input: str,
        conversation_history: List[Dict[str, Any]],
        user_type: str,
        language: str
    ) -> Dict[str, Any]:
        """Analyze voice input to determine intent."""
        
        # Build conversation context
        context_str = "\n".join([
            f"User: {turn['user_input']}\nAssistant: {turn['response']}"
            for turn in conversation_history[-3:]
        ])
        
        prompt = f"""
        Analyze this voice query from a {user_type} in a retail store.
        
        Current Query: "{voice_input}"
        Language: {language}
        
        Previous Conversation:
        {context_str if context_str else "No previous conversation"}
        
        Determine:
        1. Primary intent (product_search, navigation, price_check, employee_help, store_info, feedback, general)
        2. Extracted query/product name
        3. Urgency level (if applicable)
        4. Required actions
        
        Common intents:
        - product_search: "Where can I find milk?", "Do you have organic apples?"
        - navigation: "Where is the bakery section?", "How do I get to checkout?"
        - price_check: "How much is this?", "What's the price of bread?"
        - employee_help: "I need help", "Can someone assist me?", "Spill on aisle 3"
        - store_info: "When do you close?", "Do you have wifi?", "Where is the bathroom?"
        - feedback: "Great service", "This product is defective"
        
        Format as JSON with keys: intent, extracted_query, product_name, urgency, confidence
        """
        
        intent_result = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are an expert in understanding natural language queries in retail environments. Be helpful and accurate.",
            temperature=0.2
        )
        
        return intent_result

    async def _voice_product_search(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Search for products using voice query."""
        
        query = context.get("query", "")
        store_id = context.get("store_id")
        language = context.get("language", "en")
        
        # Search products
        products = await search_products_by_voice(query, store_id)
        
        if not products:
            response_text = self._generate_no_results_response(query, language)
            return {
                "response_text": response_text,
                "products": [],
                "suggestions": await self._get_alternative_suggestions(query, store_id)
            }
        
        # Generate natural language response
        response_text = await self._generate_product_response(
            products,
            query,
            language
        )
        
        return {
            "response_text": response_text,
            "products": products[:5],  # Top 5 matches
            "total_found": len(products),
            "voice_output": response_text
        }

    async def _generate_product_response(
        self,
        products: List[Dict[str, Any]],
        query: str,
        language: str
    ) -> str:
        """Generate natural language response for product search."""
        
        if len(products) == 1:
            product = products[0]
            prompt = f"""
            Generate a friendly, conversational response for a customer asking: "{query}"
            
            Product Found:
            - Name: {product['name']}
            - Location: {product.get('location', 'Unknown')}
            - Price: ${product.get('price', 0):.2f}
            - In Stock: {product.get('in_stock', True)}
            
            Language: {language}
            
            Keep it concise (2-3 sentences) and include:
            1. Confirmation you found it
            2. Location in store
            3. Price if relevant
            """
        else:
            products_info = "\n".join([
                f"- {p['name']}: {p.get('location', 'Unknown')} (${p.get('price', 0):.2f})"
                for p in products[:3]
            ])
            
            prompt = f"""
            Generate a friendly response for: "{query}"
            
            Found {len(products)} products:
            {products_info}
            
            Language: {language}
            
            Keep it conversational and mention the top 2-3 options.
            """
        
        response = await self.llm_client.generate(
            prompt=prompt,
            system_message="You are a helpful store assistant speaking naturally to customers.",
            temperature=0.7,
            max_tokens=150
        )
        
        return response.strip()

    def _generate_no_results_response(self, query: str, language: str) -> str:
        """Generate response when no products found."""
        
        responses = {
            "en": f"I'm sorry, I couldn't find '{query}' in our store. Would you like me to suggest similar items or check with a staff member?",
            "es": f"Lo siento, no pude encontrar '{query}' en nuestra tienda. ¿Te gustaría que sugiera artículos similares?",
            "fr": f"Désolé, je n'ai pas trouvé '{query}' dans notre magasin. Voulez-vous que je suggère des articles similaires?"
        }
        
        return responses.get(language, responses["en"])

    async def _get_alternative_suggestions(
        self,
        query: str,
        store_id: str
    ) -> List[Dict[str, Any]]:
        """Get alternative product suggestions."""
        
        # TODO: Use semantic search or category-based suggestions
        return []

    async def _provide_navigation(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Provide store navigation assistance."""
        
        query = context.get("query", "")
        store_id = context.get("store_id")
        
        # Get navigation information
        navigation = await get_store_navigation(query, store_id)
        
        if not navigation:
            return {
                "response_text": "I'm sorry, I couldn't find that location. Can you be more specific?",
                "navigation": None
            }
        
        # Generate walking directions
        response_text = await self._generate_navigation_response(navigation)
        
        return {
            "response_text": response_text,
            "navigation": navigation,
            "estimated_time": navigation.get("estimated_time_seconds", 60),
            "visual_map": navigation.get("map_url")
        }

    async def _generate_navigation_response(
        self,
        navigation: Dict[str, Any]
    ) -> str:
        """Generate natural language navigation instructions."""
        
        prompt = f"""
        Convert these navigation details into clear, spoken walking directions:
        
        Destination: {navigation.get('destination')}
        Current Location: {navigation.get('current_location', 'Store Entrance')}
        Aisle: {navigation.get('aisle')}
        Section: {navigation.get('section')}
        Distance: {navigation.get('distance_feet', 0)} feet
        
        Directions: {navigation.get('directions', [])}
        
        Make it conversational and easy to follow while walking.
        Example: "Head straight down the main aisle, then turn right at the dairy section..."
        """
        
        response = await self.llm_client.generate(
            prompt=prompt,
            system_message="You are giving clear walking directions in a store.",
            temperature=0.3,
            max_tokens=150
        )
        
        return response.strip()

    async def _check_price_availability(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Check product price and availability."""
        
        product_name = context.get("product_name", "")
        store_id = context.get("store_id")
        
        # Get product info
        product_info = await get_product_information(product_name, store_id)
        
        if not product_info:
            return {
                "response_text": f"I couldn't find pricing information for {product_name}. Would you like me to call a staff member?",
                "product": None
            }
        
        # Check availability
        availability = await check_product_availability(
            product_info["product_id"],
            store_id
        )
        
        # Generate response
        if availability["in_stock"]:
            response_text = f"{product_info['name']} is ${product_info['price']:.2f} and we have {availability['quantity']} in stock."
            
            # Add promotion if available
            if product_info.get("promotion"):
                response_text += f" It's currently on sale: {product_info['promotion']['description']}"
        else:
            response_text = f"{product_info['name']} is ${product_info['price']:.2f}, but it's currently out of stock. Would you like me to check when we'll have more?"
        
        return {
            "response_text": response_text,
            "product": product_info,
            "availability": availability
        }

    async def _handle_employee_request(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle employee assistance requests."""
        
        request = context.get("request", "")
        store_id = context.get("store_id")
        urgency = context.get("urgency", "normal")
        
        # Analyze request type
        request_analysis = await self._analyze_employee_request(request, urgency)
        
        # Trigger appropriate alert
        if request_analysis["requires_immediate_action"]:
            alert_result = await trigger_staff_alert(
                alert_type=request_analysis["alert_type"],
                location=context.get("location", "unknown"),
                message=request,
                store_id=store_id,
                urgency="high"
            )
            
            response_text = f"I've alerted staff immediately. Someone will be with you in just a moment."
        else:
            assistance = await get_employee_assistance(
                request_type=request_analysis["request_type"],
                store_id=store_id
            )
            
            response_text = f"I've notified {assistance['department']} staff. They'll arrive in approximately {assistance['estimated_minutes']} minutes."
        
        return {
            "response_text": response_text,
            "request_type": request_analysis["request_type"],
            "alert_triggered": request_analysis["requires_immediate_action"],
            "estimated_response_time": 3 if request_analysis["requires_immediate_action"] else 5
        }

    async def _analyze_employee_request(
        self,
        request: str,
        urgency: str
    ) -> Dict[str, Any]:
        """Analyze employee assistance request."""
        
        prompt = f"""
        Analyze this customer assistance request:
        
        Request: "{request}"
        Stated Urgency: {urgency}
        
        Determine:
        1. Request type (general_help, spill_cleanup, product_location, checkout_help, safety_issue, complaint)
        2. Alert type (if immediate action needed)
        3. Whether it requires immediate action
        4. Appropriate department
        
        Safety issues (spills, broken glass, medical) = immediate action required
        
        Format as JSON with keys: request_type, alert_type, requires_immediate_action, department
        """
        
        analysis = await self.llm_client.generate_structured_output(
            prompt=prompt,
            system_message="You are analyzing customer requests to ensure appropriate and timely staff response.",
            temperature=0.2
        )
        
        return analysis

    async def _provide_store_information(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Provide general store information."""
        
        query = context.get("query", "")
        store_id = context.get("store_id")
        
        # Get store hours
        store_hours = await get_store_hours(store_id)
        
        # Process query with LLM
        prompt = f"""
        Answer this store information question: "{query}"
        
        Store Information:
        - Hours: {store_hours['hours']}
        - Services: {store_hours.get('services', [])}
        - Amenities: Wifi, Restrooms, Customer Service Desk, Pharmacy
        - Phone: {store_hours.get('phone', '555-0100')}
        
        Provide a concise, helpful answer.
        """
        
        response_text = await self.llm_client.generate(
            prompt=prompt,
            system_message="You are providing store information to customers.",
            temperature=0.3,
            max_tokens=100
        )
        
        return {
            "response_text": response_text.strip(),
            "store_hours": store_hours
        }

    async def _get_promotions(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Get current promotional offers."""
        
        store_id = context.get("store_id")
        category = context.get("category")
        
        # Get promotions
        promotions = await get_promotional_offers(store_id, category)
        
        if not promotions:
            return {
                "response_text": "We don't have any special promotions right now, but check back soon!",
                "promotions": []
            }
        
        # Generate response
        promo_text = await self._generate_promotions_response(promotions)
        
        return {
            "response_text": promo_text,
            "promotions": promotions,
            "count": len(promotions)
        }

    async def _generate_promotions_response(
        self,
        promotions: List[Dict[str, Any]]
    ) -> str:
        """Generate natural language promotions response."""
        
        promo_list = "\n".join([
            f"- {p['title']}: {p['description']}"
            for p in promotions[:3]
        ])
        
        prompt = f"""
        Present these promotions in a friendly, conversational way:
        
        {promo_list}
        
        Keep it concise and mention the best deals first.
        """
        
        response = await self.llm_client.generate(
            prompt=prompt,
            system_message="You are announcing exciting deals to customers.",
            temperature=0.7,
            max_tokens=150
        )
        
        return response.strip()

    async def _handle_voice_feedback(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle voice feedback from customers."""
        
        feedback = context.get("feedback", "")
        user_id = context.get("user_id")
        store_id = context.get("store_id")
        
        # Process feedback
        feedback_result = await process_voice_feedback(
            feedback=feedback,
            user_id=user_id,
            store_id=store_id
        )
        
        # Generate thank you response
        if feedback_result["sentiment"] == "positive":
            response_text = "Thank you so much for the kind words! We really appreciate your feedback."
        elif feedback_result["sentiment"] == "negative":
            response_text = "I'm sorry to hear that. I've recorded your feedback and a manager will follow up with you soon."
        else:
            response_text = "Thank you for your feedback. We appreciate you taking the time to share your thoughts."
        
        return {
            "response_text": response_text,
            "feedback_recorded": True,
            "follow_up_required": feedback_result["sentiment"] == "negative"
        }

    async def _handle_general_query(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Handle general queries that don't fit specific intents."""
        
        query = context.get("query", "")
        store_id = context.get("store_id")
        language = context.get("language", "en")
        
        # Use LLM for general response
        prompt = f"""
        Respond to this customer query in a retail store: "{query}"
        
        Language: {language}
        
        You are a helpful store assistant. Provide a brief, friendly response.
        If you don't know something, offer to get a staff member to help.
        """
        
        response_text = await self.llm_client.generate(
            prompt=prompt,
            system_message="You are a helpful, friendly store assistant.",
            temperature=0.7,
            max_tokens=100
        )
        
        return {
            "response_text": response_text.strip(),
            "suggest_human_assistance": "don't know" in response_text.lower()
        }

    def clear_session_context(self, session_id: str):
        """Clear conversation context for a session."""
        if session_id in self.conversation_context:
            del self.conversation_context[session_id]
