
from app import app

client = app.test_client()

# Test 1: Missing JSON request
response = client.post("/api/edit-text")
print("Missing JSON:", response.status_code)
assert response.status_code == 400

# Test 2: Empty prompt
response = client.post(
    "/api/edit-text",
    json={
        "project_id": "test-project",
        "prompt": "",
        "layers": [],
    },
)
print("Empty prompt:", response.status_code)
assert response.status_code == 400

# Test 3: Valid request, but AI is not connected
response = client.post(
    "/api/edit-text",
    json={
        "project_id": "test-project",
        "prompt": "Make the selected text larger",
        "selected_layer_id": None,
        "layers": [],
    },
)
print("Valid request:", response.status_code)
print("Response:", response.get_json())
assert response.status_code == 501

print("All API validation tests passed!")