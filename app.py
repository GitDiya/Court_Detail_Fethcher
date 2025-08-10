
from flask import Flask, render_template, request, send_from_directory, redirect, url_for
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
import re
import sqlite3
import os
import time
from urllib.parse import urljoin

app = Flask(__name__)

# DB setup
DB_DIR = "data"
DB_PATH = os.path.join(DB_DIR, "queries.db")
os.makedirs(DB_DIR, exist_ok=True)

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS queries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        court TEXT,
        case_type TEXT,
        case_number TEXT,
        case_year TEXT,
        raw_html TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)
    conn.commit()
    conn.close()

LABEL_KEYWORDS = [
    "petitioner", "respondent", "party", "parties", "next hearing", "next date",
    "hearing", "filing date", "filed on", "order", "judgment", "judgement", "order date"
]

def extract_fields_from_html(html, base_url=None):
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text(separator="\n", strip=True)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    data = {}
    for i, ln in enumerate(lines):
        low = ln.lower()
        for kw in LABEL_KEYWORDS:
            if kw in low:
                snippet = " ".join(lines[i:i+3])
                data.setdefault(kw, []).append(snippet)

    date_matches = re.findall(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b", text)
    if date_matches:
        data.setdefault("dates", date_matches[:5])

    pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().endswith(".pdf"):
            pdf_links.append(urljoin(base_url or "", href))
        elif "order" in (a.get_text() or "").lower() and ("pdf" in href or href.endswith(".pdf")):
            pdf_links.append(urljoin(base_url or "", href))
    if pdf_links:
        data["pdf_links"] = pdf_links

    vs_match = None
    for ln in lines[:400]:
        if re.search(r"\b(vs|v\.|versus|v)\b", ln, flags=re.I):
            vs_match = ln
            break
    if vs_match:
        data["parties_line"] = vs_match

    snippet_top = "\n".join(lines[:30])
    data.setdefault("top_text", snippet_top)
    return data

def perform_search_and_fetch(case_type, case_number, case_year, timeout=12):
    court_url = "https://delhihighcourt.nic.in/case.asp"
    options = uc.ChromeOptions()
    options.headless = True
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = uc.Chrome(options=options)
    driver.set_page_load_timeout(30)
    html_result = None
    try:
        driver.get(court_url)
        inputs = driver.find_elements(By.TAG_NAME, "input")
        selects = driver.find_elements(By.TAG_NAME, "select")

        def match_field(el, keywords):
            attrs = []
            try:
                attrs = [el.get_attribute("name") or "", el.get_attribute("id") or "",
                         el.get_attribute("placeholder") or "", el.get_attribute("aria-label") or ""]
            except Exception:
                pass
            attrs = " ".join([a.lower() for a in attrs if a])
            for kw in keywords:
                if kw in attrs:
                    return True
            return False

        type_keywords = ["type", "ctype", "casetype", "case_type"]
        number_keywords = ["case_no", "cno", "caseno", "number", "case_number"]
        year_keywords = ["year", "case_year", "cyear", "year_field"]

        for inp in inputs:
            try:
                itype = inp.get_attribute("type") or "text"
                if itype.lower() in ("text", "search", "tel", "number"):
                    if match_field(inp, type_keywords):
                        inp.clear()
                        inp.send_keys(case_type)
                    elif match_field(inp, number_keywords):
                        inp.clear()
                        inp.send_keys(case_number)
                    elif match_field(inp, year_keywords):
                        inp.clear()
                        inp.send_keys(case_year)
            except Exception:
                continue

        for sel in selects:
            try:
                if match_field(sel, type_keywords):
                    options_els = sel.find_elements(By.TAG_NAME, "option")
                    for opt in options_els:
                        if case_type.lower() in (opt.text or "").lower():
                            opt.click()
                            break
            except Exception:
                continue

        buttons = driver.find_elements(By.TAG_NAME, "button") + driver.find_elements(By.XPATH, "//input[@type='submit']") + driver.find_elements(By.XPATH, "//input[@type='button']")
        clicked = False
        for b in buttons:
            try:
                txt = (b.get_attribute("value") or b.text or "").strip().lower()
                if any(k in txt for k in ["search", "submit", "find", "go", "show", "get", "view"]):
                    b.click()
                    clicked = True
                    break
            except Exception:
                continue
        if not clicked:
            try:
                forms = driver.find_elements(By.TAG_NAME, "form")
                if forms:
                    forms[0].submit()
            except Exception:
                pass

        time.sleep(2)
        WebDriverWait(driver, timeout).until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        html_result = driver.page_source
    except Exception as e:
        html_result = getattr(driver, "page_source", f"ERROR: {e}")
    finally:
        try:
            driver.quit()
        except Exception:
            pass
    return html_result

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        case_type = request.form.get("case_type", "")
        case_number = request.form.get("case_number", "")
        case_year = request.form.get("case_year", "")

        html = perform_search_and_fetch(case_type, case_number, case_year)

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO queries (court, case_type, case_number, case_year, raw_html) VALUES (?, ?, ?, ?, ?)",
                  ("https://delhihighcourt.nic.in/case.asp", case_type, case_number, case_year, html[:10000]))
        query_id = c.lastrowid
        conn.commit()
        conn.close()

        return redirect(url_for('result', query_id=query_id))

    return render_template("index.html")

@app.route("/result/<int:query_id>")
def result(query_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT court, case_type, case_number, case_year, raw_html FROM queries WHERE id=?", (query_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "No record found", 404

    court_url, case_type, case_number, case_year, html = row
    parsed = extract_fields_from_html(html, base_url=court_url)
    return render_template("result.html", parsed=parsed, raw_html=html)

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

if __name__ == "__main__":
    init_db()
    print("App running at: http://localhost:7860/")
    app.run(host="0.0.0.0", port=7860, debug=True)



    