import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from flask import Flask, render_template_string, request

# 运行 python query_balance.py,然后浏览器打开 http://127.0.0.1:5000。

#   要点:
#   - 顶部汇总: 资产数、Free 总值(USDT)、Locked 总值(USDT)、合计、无价资产数
#   - 表头点击排序 (asset/free/locked/price/free_usdt/locked_usdt),再次点击切换升降序
#   - 默认按 free_usdt 降序
#   - 估值: {ASSET}USDT 现价;USDT 与已知稳定币按 1 计;无对应交易对的资产显示 - 且不计入总值
#   - 依赖: pip install flask requests

API_KEY = "VuG06vAzyJ4ChynTEKiWSIkIg4NcpPW91eIutCBPdj29uUQLz2pxAswEl69JRoFj"
API_SECRET = "OrZi1xfOyNJIEz2MIndnRvAv4Br4I60XWKdmI32Ctyj3lemF5DJkpRlFBc4fqU4c".encode()
BASE_URL = "https://testnet.binance.vision"


def sign(params):
    query = urlencode(params)
    return hmac.new(API_SECRET, query.encode(), hashlib.sha256).hexdigest()


def signed_request(method, path, params):
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
        free = float(b["free"])
        locked = float(b["locked"])
        if free > 0 or locked > 0:
            balances.append({"asset": b["asset"], "free": free, "locked": locked})
    return balances


def get_price_map():
    r = requests.get(BASE_URL + "/api/v3/ticker/price")
    data = r.json()
    return {item["symbol"]: float(item["price"]) for item in data}


STABLES = {"USDT", "USDC", "BUSD", "TUSD", "DAI", "FDUSD", "USDP", "USD1", "USDE", "BFUSD", "AEUR", "EURI"}


def usdt_price(asset, price_map):
    if asset == "USDT":
        return 1.0
    sym = asset + "USDT"
    if sym in price_map:
        return price_map[sym]
    if asset in STABLES:
        return 1.0
    return None


def enrich(balances, price_map):
    rows = []
    for b in balances:
        p = usdt_price(b["asset"], price_map)
        free_usdt = b["free"] * p if p is not None else None
        locked_usdt = b["locked"] * p if p is not None else None
        rows.append({
            "asset": b["asset"],
            "free": b["free"],
            "locked": b["locked"],
            "price": p,
            "free_usdt": free_usdt,
            "locked_usdt": locked_usdt,
        })
    return rows


PAGE = """
<!doctype html>
<html><head><meta charset="utf-8"><title>Binance Balance</title>
<style>
body{font-family:-apple-system,Segoe UI,Arial,sans-serif;margin:20px;background:#0f172a;color:#e2e8f0}
h1{margin:0 0 8px 0}
.summary{margin:12px 0;padding:12px;background:#1e293b;border-radius:8px;display:flex;gap:32px}
.summary div{font-size:15px}
.summary b{color:#fbbf24;font-size:18px}
table{border-collapse:collapse;width:100%;background:#1e293b;border-radius:8px;overflow:hidden}
th,td{padding:8px 12px;text-align:right;border-bottom:1px solid #334155}
th:first-child,td:first-child{text-align:left}
th{background:#334155;cursor:pointer;user-select:none;position:sticky;top:0}
th a{color:#e2e8f0;text-decoration:none;display:block}
th.active{background:#475569;color:#fbbf24}
tr:hover{background:#293548}
.muted{color:#64748b}
.controls{margin:8px 0}
.controls a{color:#60a5fa;margin-right:12px;text-decoration:none}
</style></head>
<body>
<h1>Binance Testnet Balance</h1>
<div class="controls">
  <a href="/">Refresh</a>
  <span class="muted">Sort by clicking column header. Current: <b>{{sort_by}}</b> ({{order}})</span>
</div>
<div class="summary">
  <div>Assets: <b>{{rows|length}}</b></div>
  <div>Total Free (USDT): <b>{{ "%.2f"|format(total_free) }}</b></div>
  <div>Total Locked (USDT): <b>{{ "%.2f"|format(total_locked) }}</b></div>
  <div>Grand Total (USDT): <b>{{ "%.2f"|format(total_free + total_locked) }}</b></div>
  <div class="muted">Unpriced: {{unpriced}}</div>
</div>
<table>
<thead><tr>
{% for col,label in columns %}
<th class="{% if col==sort_by %}active{% endif %}">
<a href="?sort={{col}}&order={% if col==sort_by and order=='desc' %}asc{% else %}desc{% endif %}">{{label}}{% if col==sort_by %} {{ '▼' if order=='desc' else '▲' }}{% endif %}</a>
</th>
{% endfor %}
</tr></thead>
<tbody>
{% for r in rows %}
<tr>
<td>{{r.asset}}</td>
<td>{{ "%.8f"|format(r.free) }}</td>
<td>{{ "%.8f"|format(r.locked) }}</td>
<td>{% if r.price is not none %}{{ "%.6f"|format(r.price) }}{% else %}<span class="muted">-</span>{% endif %}</td>
<td>{% if r.free_usdt is not none %}{{ "%.2f"|format(r.free_usdt) }}{% else %}<span class="muted">-</span>{% endif %}</td>
<td>{% if r.locked_usdt is not none %}{{ "%.2f"|format(r.locked_usdt) }}{% else %}<span class="muted">-</span>{% endif %}</td>
</tr>
{% endfor %}
</tbody></table>
</body></html>
"""


app = Flask(__name__)


@app.route("/")
def index():
    sort_by = request.args.get("sort", "free_usdt")
    order = request.args.get("order", "desc")
    valid = {"asset", "free", "locked", "price", "free_usdt", "locked_usdt"}
    if sort_by not in valid:
        sort_by = "free_usdt"

    balances = get_balance()
    price_map = get_price_map()
    rows = enrich(balances, price_map)

    reverse = order == "desc"
    if sort_by == "asset":
        rows.sort(key=lambda r: r["asset"], reverse=reverse)
    else:
        rows.sort(key=lambda r: (r[sort_by] is None, r[sort_by] or 0), reverse=reverse)

    total_free = sum(r["free_usdt"] or 0 for r in rows)
    total_locked = sum(r["locked_usdt"] or 0 for r in rows)
    unpriced = sum(1 for r in rows if r["price"] is None)

    columns = [
        ("asset", "Asset"),
        ("free", "Free"),
        ("locked", "Locked"),
        ("price", "Price (USDT)"),
        ("free_usdt", "Free Value"),
        ("locked_usdt", "Locked Value"),
    ]

    return render_template_string(
        PAGE,
        rows=rows, sort_by=sort_by, order=order,
        total_free=total_free, total_locked=total_locked,
        unpriced=unpriced, columns=columns,
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
