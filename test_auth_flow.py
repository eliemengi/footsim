import requests

session = requests.Session()
response = session.get('http://127.0.0.1:5000/')
import re
match = re.search(r'<meta name="csrf-token" content="([^"]+)">', response.text)
if not match:
    print("No CSRF token found in HTML")
    exit(1)

csrf_token = match.group(1)
print(f"Got CSRF token: {csrf_token}")

headers = {
    'X-CSRFToken': csrf_token,
    'Content-Type': 'application/json'
}

data = {
    'first_name': 'Test',
    'last_name': 'User2',
    'email': 'test2@test.com',
    'password': 'password123'
}

post_response = session.post('http://127.0.0.1:5000/api/auth/register', json=data, headers=headers)
print(f"Register status: {post_response.status_code}")
print(f"Register response: {post_response.text}")

