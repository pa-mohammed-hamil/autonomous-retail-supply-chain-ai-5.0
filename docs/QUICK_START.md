# Quick Start Guide

## Get Started in 5 Minutes

This guide will help you quickly understand and use the new AI features in the Autonomous Retail Supply Chain system.

## 🚀 Quick Overview

7 new AI-powered features:
1. **Dynamic Pricing** - Intelligent price optimization
2. **Sustainability** - Carbon tracking & green optimization
3. **Predictive Maintenance** - Equipment failure prediction
4. **Assortment Planning** - Smart product selection
5. **Personalization** - Customer-specific experiences
6. **Voice Assistant** - Hands-free operations
7. **Auto Stock** - Automatic inventory updates

## 📦 Installation

```bash
# Clone repository
git clone https://github.com/your-org/autonomous-retail-supply-chain-ai-5.0.git
cd autonomous-retail-supply-chain-ai-5.0

# Install dependencies
pip install -r requirements.txt

# Set up environment
cp .env.example .env
# Edit .env with your API keys

# Run database migrations
alembic upgrade head

# Start the server
uvicorn backend.main:app --reload
```

## 🔑 API Keys Required

```bash
# .env file
OPENAI_API_KEY=sk-...          # For LLM capabilities
ANTHROPIC_API_KEY=sk-ant-...   # Alternative LLM
ELEVENLABS_API_KEY=...         # For voice synthesis
```

## 💡 Basic Usage Examples

### 1. Dynamic Pricing

```python
import requests

# Optimize price for a product
response = requests.post(
    "http://localhost:8000/api/v1/pricing/optimize",
    json={
        "product_id": "PROD-001",
        "strategy": "dynamic",
        "objective": "revenue"
    }
)

result = response.json()
print(f"Recommended price: ${result['recommended_price']}")
print(f"Expected impact: {result['expected_impact']}")
```

### 2. Auto Stock Management

```python
# Process a barcode scan
response = requests.post(
    "http://localhost:8000/api/v1/auto-stock/scan-event",
    json={
        "scanner_id": "SCANNER-001",
        "barcode": "1234567890123",
        "location_id": "LOC-A1"
    }
)

result = response.json()
print(f"Task status: {result['task_status']}")
print(f"Confidence: {result['confidence']}")
```

### 3. Voice Commands

```python
# Process voice command
with open("command.wav", "rb") as audio:
    files = {"audio": audio}
    response = requests.post(
        "http://localhost:8000/api/v1/voice-assistant/process",
        files=files,
        data={"language": "en"}
    )

result = response.json()
print(f"Command: {result['transcript']}")
print(f"Action: {result['action_taken']}")
```

### 4. Personalized Recommendations

```python
# Get personalized recommendations
response = requests.get(
    "http://localhost:8000/api/v1/personalization/recommend",
    params={
        "customer_id": "CUST-123",
        "limit": 10
    }
)

recommendations = response.json()
for rec in recommendations['products']:
    print(f"{rec['name']}: {rec['score']}")
```

### 5. Predictive Maintenance

```python
# Check equipment health
response = requests.get(
    "http://localhost:8000/api/v1/maintenance/equipment/FORKLIFT-001"
)

status = response.json()
print(f"Health score: {status['health_score']}")
print(f"Days until maintenance: {status['days_until_maintenance']}")
if status['failure_risk'] > 0.7:
    print("⚠️ High failure risk!")
```

### 6. Sustainability Tracking

```python
# Get carbon footprint
response = requests.post(
    "http://localhost:8000/api/v1/sustainability/carbon-footprint",
    json={
        "scope": "product",
        "product_id": "PROD-001"
    }
)

footprint = response.json()
print(f"Total carbon: {footprint['total_kg_co2']} kg CO2")
print(f"Rating: {footprint['rating']}")
```

### 7. Assortment Planning

```python
# Optimize store assortment
response = requests.post(
    "http://localhost:8000/api/v1/assortment/optimize",
    json={
        "store_id": "STORE-001",
        "category": "electronics",
        "space_available_sqft": 1000
    }
)

plan = response.json()
print(f"Recommended SKUs: {len(plan['products'])}")
print(f"Expected revenue: ${plan['projected_revenue']}")
```

## 🔗 API Endpoints Quick Reference

### Pricing
- `POST /api/v1/pricing/optimize` - Optimize price
- `GET /api/v1/pricing/monitor` - Monitor competitor prices
- `POST /api/v1/pricing/simulate` - Simulate pricing scenarios

### Auto Stock
- `POST /api/v1/auto-stock/scan-event` - Process scan
- `GET /api/v1/auto-stock/tasks` - Get stock tasks
- `POST /api/v1/auto-stock/reconcile` - Reconcile inventory

### Voice Assistant
- `POST /api/v1/voice-assistant/process` - Process voice command
- `POST /api/v1/voice-assistant/text-to-speech` - Convert text to speech

### Personalization
- `GET /api/v1/personalization/recommend` - Get recommendations
- `GET /api/v1/personalization/clv` - Predict customer lifetime value
- `GET /api/v1/personalization/segment` - Get customer segment

### Maintenance
- `GET /api/v1/maintenance/equipment/{id}` - Get equipment status
- `POST /api/v1/maintenance/predict` - Predict failures
- `GET /api/v1/maintenance/schedule` - Get maintenance schedule

### Sustainability
- `POST /api/v1/sustainability/carbon-footprint` - Calculate footprint
- `GET /api/v1/sustainability/suppliers` - Get green suppliers
- `POST /api/v1/sustainability/optimize` - Optimize for sustainability

### Assortment
- `POST /api/v1/assortment/optimize` - Optimize assortment
- `GET /api/v1/assortment/segments` - Get customer segments
- `POST /api/v1/assortment/analyze` - Analyze category

## 🎯 Common Use Cases

### Use Case 1: New Product Launch
```python
# Step 1: Forecast demand
demand = requests.post("/api/v1/demand/forecast", json={
    "product_id": "NEW-PROD-001",
    "horizon_days": 90
})

# Step 2: Optimize launch price
price = requests.post("/api/v1/pricing/optimize", json={
    "product_id": "NEW-PROD-001",
    "strategy": "penetration"
})

# Step 3: Identify target customers
customers = requests.post("/api/v1/personalization/target", json={
    "product_id": "NEW-PROD-001"
})

# Step 4: Set initial stock
inventory = requests.post("/api/v1/inventory/set-target", json={
    "product_id": "NEW-PROD-001",
    "quantity": demand['forecast']['total']
})
```

### Use Case 2: Warehouse Operations
```python
# Morning: Check equipment health
equipment = requests.get("/api/v1/maintenance/warehouse/WH-001")

# Process incoming shipments (auto-complete with barcode scanning)
for item in shipment:
    requests.post("/api/v1/auto-stock/scan-event", json={
        "barcode": item.barcode,
        "location_id": item.destination
    })

# End of day: Reconcile inventory
reconciliation = requests.post("/api/v1/auto-stock/reconcile", json={
    "warehouse_id": "WH-001",
    "auto_adjust": True
})
```

### Use Case 3: Store Manager Daily Tasks
```python
# Voice command: "Check inventory for top selling products"
# System automatically:
# 1. Identifies top sellers
# 2. Checks stock levels
# 3. Flags low stock items
# 4. Suggests reorder quantities

# Voice command: "What's our carbon footprint this week?"
# System automatically:
# 1. Calculates weekly emissions
# 2. Compares to targets
# 3. Suggests improvements
```

## 📊 Real-Time Monitoring

### WebSocket Connection
```javascript
// Connect to real-time event stream
const ws = new WebSocket('ws://localhost:8000/api/v1/auto-stock/events/stream');

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Real-time event:', data);
  
  // Update UI based on event type
  switch(data.event_type) {
    case 'task_completed':
      updateTaskList(data);
      break;
    case 'inventory_updated':
      updateInventoryDisplay(data);
      break;
    case 'alert':
      showAlert(data);
      break;
  }
};
```

## 🧪 Testing

### Run Tests
```bash
# All tests
pytest tests/ -v

# Specific feature
pytest tests/features/pricing/ -v

# With coverage
pytest tests/ --cov=ai --cov=backend --cov-report=html
```

### Test with curl
```bash
# Test pricing optimization
curl -X POST http://localhost:8000/api/v1/pricing/optimize \
  -H "Content-Type: application/json" \
  -d '{
    "product_id": "PROD-001",
    "strategy": "dynamic"
  }'

# Test auto stock scan
curl -X POST http://localhost:8000/api/v1/auto-stock/scan-event \
  -H "Content-Type: application/json" \
  -d '{
    "scanner_id": "SCANNER-001",
    "barcode": "1234567890123",
    "location_id": "LOC-A1"
  }'
```

## 📱 Mobile Integration

### React Native Example
```javascript
import { AutoStockAPI } from './api';
import { BarcodeScanner } from 'react-native-barcode-scanner';

const ScannerScreen = () => {
  const handleScan = async (barcode) => {
    try {
      const result = await AutoStockAPI.processScan({
        scanner_id: deviceId,
        barcode: barcode,
        location_id: currentLocation
      });
      
      if (result.task_status === 'completed') {
        Alert.alert('Success', 'Task auto-completed!');
      }
    } catch (error) {
      Alert.alert('Error', error.message);
    }
  };
  
  return <BarcodeScanner onScan={handleScan} />;
};
```

## 🔧 Configuration

### Feature Flags
```python
# config.py
FEATURES = {
    "pricing_optimization": True,
    "sustainability_tracking": True,
    "predictive_maintenance": True,
    "assortment_planning": True,
    "personalization": True,
    "voice_assistant": True,
    "auto_stock": True
}

# Thresholds
AUTO_COMPLETION_THRESHOLD = 0.95
MAINTENANCE_ALERT_THRESHOLD = 0.7
PRICE_CHANGE_LIMIT = 0.20  # 20% max change
```

### Agent Configuration
```python
from ai.agents import PricingAgent

# Configure agent
agent = PricingAgent(
    model="gpt-4",
    temperature=0.7,
    max_retries=3,
    timeout=30
)

# Custom tools
agent.register_tool(my_custom_tool)

# Run analysis
result = await agent.optimize_price(
    product_id="PROD-001",
    context={"season": "holiday"}
)
```

## 🐛 Troubleshooting

### Common Issues

**Issue**: API returns 500 error
```bash
# Check logs
tail -f logs/app.log

# Verify database connection
python scripts/check_db.py

# Restart services
systemctl restart app-server
```

**Issue**: Low auto-completion confidence
```python
# Check configuration
config = requests.get("/api/v1/auto-stock/config/WH-001")

# Adjust threshold if needed
requests.put("/api/v1/auto-stock/config/WH-001", json={
    "auto_completion_threshold": 0.90  # Lower threshold
})
```

**Issue**: Voice commands not recognized
```bash
# Check microphone
arecord -l

# Test audio processing
python scripts/test_audio.py

# Verify API key
echo $ELEVENLABS_API_KEY
```

## 📚 Additional Resources

- **Full Documentation**: See `docs/` directory
- **API Reference**: Visit `/docs` endpoint when server is running
- **Integration Guide**: `docs/INTEGRATION_GUIDE.md`
- **Implementation Checklist**: `IMPLEMENTATION_CHECKLIST.md`

## 💬 Support

- GitHub Issues: Report bugs and feature requests
- Documentation: Comprehensive guides in `docs/`
- Examples: Code examples in `examples/`

## 🎓 Next Steps

1. **Explore Features**: Try each API endpoint
2. **Read Documentation**: Deep dive into specific features
3. **Run Examples**: Execute example scripts in `examples/`
4. **Integrate**: Connect your applications
5. **Monitor**: Set up dashboards and alerts

---

**Happy Building! 🚀**
