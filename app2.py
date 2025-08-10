from flask import Flask, render_template, request, send_from_directory, redirect, url_for
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException
from bs4 import BeautifulSoup
import re, sqlite3, os, time
from urllib.parse import urljoin
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet

app = Flask(__name__)

# Database setup
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
    "petitioner", "respondent", "party", "hearing", "judgment", "order"
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
    return data

def perform_search_and_fetch(case_type, case_number, case_year, timeout=30):
    """
    Fetches Delhi High Court case status page by performing Selenium-driven form submission.
    """
    url = "https://delhihighcourt.nic.in/case.asp"
    options = uc.ChromeOptions()
    options.headless = False  # Set True once debugging completes
    options.add_argument("--window-size=1920,1080")
    driver = uc.Chrome(options=options)
    driver.get(url)
    try:
        wait = WebDriverWait(driver, timeout)
        wait.until(EC.presence_of_element_located((By.NAME, "ctype")))
        driver.find_element(By.NAME, "ctype").send_keys(case_type)
        driver.find_element(By.NAME, "cno").clear()
        driver.find_element(By.NAME, "cno").send_keys(case_number)
        driver.find_element(By.NAME, "cyear").clear()
        driver.find_element(By.NAME, "cyear").send_keys(case_year)
        driver.find_element(By.NAME, "submit").click()
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        time.sleep(2)
        html = driver.page_source
    except Exception as e:
        os.makedirs("error_screens", exist_ok=True)
        try:
            driver.save_screenshot(f"error_screens/error_{case_type}_{case_number}_{case_year}.png")
        except WebDriverException:
            pass
        html = f"ERROR: {e}"
    finally:
        driver.quit()
    return html

def generate_pdf(parsed, path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4)
    story = [Paragraph("Case Details", styles["Title"]), Spacer(1, 12)]
    for k, v in parsed.items():
        story.append(Paragraph(f"<b>{k.capitalize()}:</b>", styles["Heading3"]))
        items = v if isinstance(v, list) else [v]
        for item in items:
            story.append(Paragraph(str(item), styles["Normal"]))
        story.append(Spacer(1, 6))
    doc.build(story)

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        ct = request.form.get("case_type")
        cn = request.form.get("case_number")
        cy = request.form.get("case_year")
        html = perform_search_and_fetch(ct, cn, cy)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("INSERT INTO queries (court, case_type, case_number, case_year, raw_html) VALUES (?, ?, ?, ?, ?)",
                  ("Delhi High Court", ct, cn, cy, html[:10000]))
        qid = c.lastrowid
        conn.commit()
        conn.close()
        return redirect(url_for("result", query_id=qid))
    return render_template("index.html")

@app.route("/result/<int:query_id>")
def result(query_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT court, case_type, case_number, case_year, raw_html FROM queries WHERE id=?", (query_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return "Record not found", 404
    court, ct, cn, cy, html = row
    parsed = extract_fields_from_html(html, base_url=court)
    pdf_dir = "downloads"; os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, f"case_{ct}_{cn}_{cy}.pdf")
    generate_pdf(parsed, pdf_path)
    return render_template("result.html", parsed=parsed, raw_html=html,
                           pdf_file=url_for("download_pdf", filename=os.path.basename(pdf_path)))

@app.route("/download/<filename>")
def download_pdf(filename):
    return send_from_directory("downloads", filename, as_attachment=True)

if __name__ == "__main__":
    init_db()
    print("Running at http://localhost:7860/")
    app.run(host="0.0.0.0", port=7860, debug=True)
