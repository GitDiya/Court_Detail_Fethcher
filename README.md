#  Court-Data Fetcher

A simple **Flask web app** that searches Indian court case details using **Selenium automation**, extracts important information with **BeautifulSoup**, and generates a **PDF report**.

---

## What’s Installed

- **Flask** → Runs the web application
- **Selenium + undetected-chromedriver** → Opens court websites & fills forms automatically
- **BeautifulSoup4 + lxml** → Extracts case details from HTML
- **ReportLab** → Generates PDF reports
- **SQLite3** → Stores all search queries in a database

---

##  Installation

1. **Clone the project**
```bash
git clone https://github.com/GitDiya/court-data-fetcher.git
cd court-data-fetcher
