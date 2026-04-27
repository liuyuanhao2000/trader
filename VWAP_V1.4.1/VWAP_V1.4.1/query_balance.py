

import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timedelta, timezone


# API_KEY = "UR8n2tMndlGt5uGdni6RF2oKBGY9WIuEPkYYVvcvtOx0XohUUHH5eMJbcykATR75"
# API_SECRET = "kqbhNWdkN1lhOXP8ENjeVmDKRXk5Cpi7Y1uEYJboJ5FHrzLkM6dRjiR2Z2hyy0sm".encode()
# BASE_URL = "https://testnet.binance.vision"

API_KEY = "VuG06vAzyJ4ChynTEKiWSIkIg4NcpPW91eIutCBPdj29uUQLz2pxAswEl69JRoFj"
API_SECRET = "OrZi1xfOyNJIEz2MIndnRvAv4Br4I60XWKdmI32Ctyj3lemF5DJkpRlFBc4fqU4c".encode()
BASE_URL = "https://testnet.binance.vision"
# API Key: VuG06vAzyJ4ChynTEKiWSIkIg4NcpPW91eIutCBPdj29uUQLz2pxAswEl69JRoFj
# Secret Key: OrZi1xfOyNJIEz2MIndnRvAv4Br4I60XWKdmI32Ctyj3lemF5DJkpRlFBc4fqU4c

def sign(params):
    query = urlencode(params)
    return hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()

def signed_request(method, path, params):
    # params["timestamp"] = int(time.time() * 1000)
    # 更精确的毫秒级时间戳
    params["timestamp"] = time.time_ns() // 1000000
    params["signature"] = sign(params)

    headers = {"X-MBX-APIKEY": API_KEY}

    if method == "GET":
        r = requests.get(BASE_URL + path, params=params, headers=headers)
    else:
        r = requests.post(BASE_URL + path, params=params, headers=headers)

    return r.json()

def get_balance():
    account = signed_request("GET", "/api/v3/account", {})
    balances = []

    for b in account["balances"]:
        if float(b["free"]) > 0 or float(b["locked"]) > 0:
            balances.append({
                "asset": b["asset"],
                "free": b["free"],
                "locked": b["locked"]
            })

    return balances

balance = get_balance()
for one_balance in balance:
    print(one_balance)
# print(len(balance))

