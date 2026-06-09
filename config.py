BASE_URL = "https://services.flhsmv.gov/mvcheckpersonalplate/"

REQUEST_DELAY_MIN = 2.0
REQUEST_DELAY_MAX = 4.0
MAX_RETRIES = 3
SESSION_REFRESH_INTERVAL = 50
MAX_PLATE_LENGTH = 7
BATCH_SIZE = 5

DATABASE_PATH = "plates.db"
WORDLIST_PATH = "data/wordlist.txt"

# HTTP headers to mimic a real browser
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": BASE_URL,
    "Origin": "https://services.flhsmv.gov",
    "Content-Type": "application/x-www-form-urlencoded",
    "Connection": "keep-alive",
}

# ASP.NET form field names for the 5 plate inputs
PLATE_INPUT_FIELDS = [
    "ctl00$MainContent$txtInputRowOne",
    "ctl00$MainContent$txtInputRowTwo",
    "ctl00$MainContent$txtInputRowThree",
    "ctl00$MainContent$txtInputRowFour",
    "ctl00$MainContent$txtInputRowFive",
]

# Result span IDs for the 5 output rows (note: row 5 has different capitalization)
PLATE_RESULT_IDS = [
    "MainContent_lblOutPutRowOne",
    "MainContent_lblOutPutRowTwo",
    "MainContent_lblOutPutRowThree",
    "MainContent_lblOutPutRowFour",
    "MainContent_lblOutputRowFive",
]
