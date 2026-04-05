import requests
s = requests.Session()
r0 = s.get('http://127.0.0.1:5000/api/admin/captcha')
cap_text = s.cookies.get('session') # wait the solution is stored in session cookie
# It's hard to read the generated captcha image. I'll just skip that and temporarily disable captcha locally in app.py logic... wait no.
