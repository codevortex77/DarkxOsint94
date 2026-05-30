from flask import Flask, request, jsonify
import requests
import re
import time
import os
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

app = Flask(__name__)

# ─── API KEY CONFIG ───────────────────────────────────────────────
API_KEYS = {
    "Vortex": {
        "expires": os.environ.get("VORTEX_EXPIRY", "2026-06-30T00:00:00+00:00")
    }
}

def check_api_key():
    """Returns (valid: bool, error_msg: str|None)"""
    key = request.headers.get("X-API-Key") or request.args.get("api_key")
    if not key:
        return False, "Missing API key. Pass via X-API-Key header or ?api_key="
    
    key_data = API_KEYS.get(key)
    if not key_data:
        return False, "Invalid API key"
    
    expiry = datetime.fromisoformat(key_data["expires"])
    now = datetime.now(timezone.utc)
    
    if now > expiry:
        return False, f"API key expired on {expiry.strftime('%Y-%m-%d')}"
    
    days_left = (expiry - now).days
    return True, f"{days_left} days remaining"
# ──────────────────────────────────────────────────────────────────

CHASSIS_API_URL = "https://chassis-no-62jj.vercel.app/?vehicle={}"
HOMEPAGE_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml?statecd=Mzc2MzM2MzAzNjY0MzIzODM3NjIzNjY0MzY2MjM3NDQ0Yw=="
HOMEPAGE_BASE = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/statevalidation/homepage.xhtml"
LOGIN_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/usermgmt/login.xhtml"
FORM_URL = "https://vahan.parivahan.gov.in/vahanservice/vahan/ui/balanceservice/form_reschedule_fitness.xhtml"

def create_session():
    session = requests.Session()
    retry = Retry(total=1, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=10)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Connection': 'keep-alive',
    })
    return session

def get_chassis_last_5(vehicle_number):
    try:
        resp = requests.get(CHASSIS_API_URL.format(vehicle_number), timeout=10)
        data = resp.json()
        if data.get("success"):
            chassis = data.get("data", {}).get("chassis_no", "").replace(" ", "")
            if len(chassis) >= 5:
                return {"success": True, "chassis_last_5": chassis[-5:]}
            return {"success": False, "error": "Chassis too short"}
        return {"success": False, "error": "API returned success=false"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def extract_viewstate(html):
    soup = BeautifulSoup(html, 'html.parser')
    vs = soup.find('input', {'name': 'javax.faces.ViewState'})
    return vs.get('value') if vs else None

def extract_viewstate_from_ajax(text):
    m = re.search(r'<update id="j_id1:javax.faces.ViewState:0"><!\[CDATA\[(.*?)\]\]></update>', text)
    return m.group(1) if m else None

def find_checkbox_id(html):
    m = re.search(r'<div[^>]*id="(j_idt\d+)"[^>]*class="[^"]*ui-chkbox', html)
    if not m:
        m = re.search(r'PrimeFaces\.cw\("SelectBooleanCheckbox"[^}]*id:"(j_idt\d+)"', html)
    return m.group(1) if m else "j_idt193"

def fetch_mobile_number(vehicle_number, chassis_last_5):
    session = create_session()
    ajax_headers = {
        'Accept': 'application/xml, text/xml, */*; q=0.01',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'Faces-Request': 'partial/ajax',
        'X-Requested-With': 'XMLHttpRequest',
        'Origin': 'https://vahan.parivahan.gov.in',
    }

    for attempt in range(2):
        try:
            r1 = session.get(HOMEPAGE_URL, timeout=20)
            if r1.status_code != 200:
                continue
            viewstate = extract_viewstate(r1.text)
            if not viewstate:
                continue
            checkbox_id = find_checkbox_id(r1.text)

            ajax_headers['Referer'] = HOMEPAGE_URL
            r2 = session.post(HOMEPAGE_BASE, data={
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': 'fit_c_office_to',
                'javax.faces.partial.execute': 'fit_c_office_to',
                'javax.faces.behavior.event': 'change',
                'javax.faces.partial.event': 'change',
                'homepageformid': 'homepageformid',
                'fit_c_office_to_input': '1',
                'javax.faces.ViewState': viewstate,
            }, headers=ajax_headers, timeout=20)
            viewstate = extract_viewstate_from_ajax(r2.text) or viewstate

            r3 = session.post(HOMEPAGE_BASE, data={
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': checkbox_id,
                'javax.faces.partial.execute': checkbox_id,
                'javax.faces.partial.render': 'proccedHomeButtonId',
                'javax.faces.behavior.event': 'change',
                'homepageformid': 'homepageformid',
                f'{checkbox_id}_input': 'on',
                'javax.faces.ViewState': viewstate,
            }, headers=ajax_headers, timeout=20)
            viewstate = extract_viewstate_from_ajax(r3.text) or viewstate

            r4 = session.post(HOMEPAGE_BASE, data={
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': 'proccedHomeButtonId',
                'javax.faces.partial.execute': '@all',
                'proccedHomeButtonId': 'proccedHomeButtonId',
                'homepageformid': 'homepageformid',
                f'{checkbox_id}_input': 'on',
                'javax.faces.ViewState': viewstate,
            }, headers=ajax_headers, timeout=20)
            viewstate = extract_viewstate_from_ajax(r4.text) or viewstate

            dialog_match = re.search(r'id="(j_idt\d+)"[^>]*class="[^"]*ui-button', r4.text)
            dialog_btn = dialog_match.group(1) if dialog_match else "j_idt536"
            r5 = session.post(HOMEPAGE_BASE, data={
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': dialog_btn,
                'javax.faces.partial.execute': '@all',
                f'{dialog_btn}': dialog_btn,
                'homepageformid': 'homepageformid',
                f'{checkbox_id}_input': 'on',
                'javax.faces.ViewState': viewstate,
            }, headers=ajax_headers, timeout=20)
            viewstate = extract_viewstate_from_ajax(r5.text) or viewstate

            r6 = session.get(LOGIN_URL + "?faces-redirect=true", timeout=20, allow_redirects=True)
            viewstate = extract_viewstate(r6.text)
            if not viewstate:
                continue

            fit_match = re.search(r'id="(j_idt\d+)"[^>]*name="\1"[^>]*type="submit"', r6.text)
            fit_btn = fit_match.group(1) if fit_match else "j_idt506"
            post_headers = {
                **session.headers,
                'Content-Type': 'application/x-www-form-urlencoded',
                'Origin': 'https://vahan.parivahan.gov.in',
                'Referer': LOGIN_URL + "?faces-redirect=true",
            }
            r7 = session.post(LOGIN_URL, data={
                'loginForm': 'loginForm',
                f'{fit_btn}': fit_btn,
                'javax.faces.ViewState': viewstate,
                'fitbalcTest': 'fitbalcTest',
                'pur_cd': '86',
            }, headers=post_headers, timeout=20, allow_redirects=True)

            form_headers = {**session.headers, 'Referer': LOGIN_URL + "?faces-redirect=true"}
            r8 = session.get(FORM_URL, headers=form_headers, timeout=20)
            viewstate = extract_viewstate(r8.text)
            if not viewstate:
                continue

            ajax_headers['Referer'] = FORM_URL
            r9 = session.post(FORM_URL, data={
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': 'balanceFeesFine:validate_dtls',
                'javax.faces.partial.execute': '@all',
                'javax.faces.partial.render': 'balanceFeesFine:auth_panel',
                'balanceFeesFine:validate_dtls': 'balanceFeesFine:validate_dtls',
                'balanceFeesFine': 'balanceFeesFine',
                'balanceFeesFine:tf_reg_no': vehicle_number,
                'balanceFeesFine:tf_chasis_no': chassis_last_5,
                'javax.faces.ViewState': viewstate,
            }, headers=ajax_headers, timeout=20)

            text = r9.text
            for pat in [r'id="balanceFeesFine:tf_mobile"[^>]*value="(\d{10})"',
                        r'value="(\d{10})"[^>]*id="balanceFeesFine:tf_mobile"',
                        r'balanceFeesFine:tf_mobile[^>]*value="(\d{10})"']:
                m = re.search(pat, text, re.DOTALL)
                if m and m.group(1)[0] in '6789':
                    return {"success": True, "mobile_number": m.group(1)}

            fallback = re.findall(r'\b[6-9]\d{9}\b', text)
            if fallback:
                return {"success": True, "mobile_number": fallback[0]}

        except Exception as e:
            print(f"Attempt {attempt+1}: {e}")
        if attempt == 0:
            time.sleep(2)

    return {"success": False, "error": "Mobile number not found"}


@app.route("/fetch", methods=["GET"])
def fetch_contact():
    valid, msg = check_api_key()
    if not valid:
        return jsonify({"success": False, "error": msg}), 401

    vehicle_number = request.args.get("vehicle_number", "").strip().upper()
    vehicle_number = re.sub(r'[^A-Z0-9]', '', vehicle_number)

    if not vehicle_number or len(vehicle_number) < 6 or len(vehicle_number) > 12:
        return jsonify({"success": False, "error": "Invalid vehicle number"}), 400

    chassis_result = get_chassis_last_5(vehicle_number)
    if not chassis_result["success"]:
        return jsonify({"success": False, "error": chassis_result["error"]}), 400

    mobile_result = fetch_mobile_number(vehicle_number, chassis_result["chassis_last_5"])

    if mobile_result["success"]:
        return jsonify({
            "success": True,
            "mobile": mobile_result["mobile_number"],
            "reg_no": vehicle_number,
            "key_info": msg   # shows "X days remaining"
        })

    return jsonify({"success": False, "error": mobile_result["error"]}), 400


# Vercel needs the app object exposed at module level
# No app.run() block needed
