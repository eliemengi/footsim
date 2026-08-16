import requests
import re

session = requests.Session()

# 1. Load page and get CSRF token
response = session.get('http://127.0.0.1:5000/')
csrf_token = re.search(r'<meta name="csrf-token" content="([^"]+)">', response.text).group(1)
headers = {'X-CSRFToken': csrf_token, 'Content-Type': 'application/json'}

# 2. Login (let's assume we use the first account we just made)
login_data = {'email': 'test2@test.com', 'password': 'password123'}
r1 = session.post('http://127.0.0.1:5000/api/auth/login', json=login_data, headers=headers)
print("Login 1:", r1.status_code, r1.text[:50])

# 3. Logout
r2 = session.post('http://127.0.0.1:5000/api/auth/logout', headers=headers)
print("Logout:", r2.status_code, r2.text[:50])

# 4. Try to login again using the SAME CSRF token from the meta tag
r3 = session.post('http://127.0.0.1:5000/api/auth/login', json=login_data, headers=headers)
print("Login 2:", r3.status_code)
if r3.status_code == 400:
    print("Login 2 response HTML snippet:", r3.text[:100])

