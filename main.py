import logging
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
import io
from filter import apply_filters
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import re
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/", response_class=HTMLResponse)
def root():
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()

SHEET_ID = "1CMU_8lXzLzijqVelZxxFOBj4408deFhP5Wf1PMPNIHs"
SHEET_RANGE = None  # None means append to first worksheet
CREDENTIALS_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "service_account.json")

# Mapping from input columns to Google Sheet columns
GSHEET_COLUMNS = [
    "Souce", "gpuid_Cal", "nameAtPanCard", "status", "createdAt", "Mob. No.", "PAN No"
]
INPUT_TO_GSHEET = {
    "Souce": "utm source",
    "gpuid_Cal": "C.GP ID", 
    "nameAtPanCard": "C.POS Name on PAN Card",
    "status": "C.POS Status",
    "createdAt": "C.Created Time",
    "Mob. No.": "C.Mobile",
    "PAN No": "C.POS PAN Number"
}

def normalize_row(row):
    # Convert to string, strip, and lowercase
    return tuple(str(cell).strip().lower() for cell in row)

# Helper to append rows to specific Google Sheet
def append_to_gsheet(rows, sheet_name="Google"):
    scopes = [
        'https://www.googleapis.com/auth/spreadsheets',
        'https://www.googleapis.com/auth/drive',
    ]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(SHEET_ID)
    
    # Get the specific worksheet
    if sheet_name == "Google":
        worksheet = sh.sheet1
    elif sheet_name == "Meta":
        worksheet = sh.worksheets()[1]  # Get Sheet2
    else:
        raise ValueError(f"Invalid sheet name: {sheet_name}")
    
    # Directly append all rows (no duplicate check)
    if rows:
        worksheet.append_rows(rows, value_input_option='USER_ENTERED')
    return len(rows)

# Both Google Sheet and input file use the same datetime format
DATETIME_FORMAT = "%b %d, %Y %I:%M %p"  # Format like "Jul 20, 2025 10:11 AM"

def get_most_recent_created_at(worksheet):
    """Get the most recent createdAt datetime from Google Sheet"""
    # Get all values in the createdAt column (5th column, index 4)
    all_values = worksheet.col_values(5)
    most_recent = None
    
    logger.info(f"Found {len(all_values)} values in createdAt column")
    
    for i, val in enumerate(all_values):
        if not val or val.strip() == "":
            continue
            
        try:
            # Parse the datetime in format "Jul 20, 2025 10:11 AM"
            dt = datetime.strptime(val.strip(), DATETIME_FORMAT)
            logger.debug(f"Row {i+1}: Parsed '{val}' as {dt}")
            
            if (most_recent is None) or (dt > most_recent):
                most_recent = dt
                logger.debug(f"New most recent: {most_recent}")
                
        except Exception as e:
            # Skip logging datetime parsing warnings since they're expected for some formats
            continue
    
    return most_recent

def filter_and_process_data(df, utm_source, sheet_name):
    """Filter data for specific utm source and process for specific sheet"""
    logger.info(f"Processing {utm_source} data for {sheet_name}")
    
    # Filter by utm source and PAN number
    filtered = df[
        (df["utm source"].str.lower() == utm_source.lower()) &
        (df["C.POS PAN Number"].notna()) & 
        (df["C.POS PAN Number"].astype(str).str.strip() != "")
    ]
    
    logger.info(f"After filtering for {utm_source} and PAN: {len(filtered)} rows")
    
    if filtered.empty:
        logger.info(f"No {utm_source} rows to process")
        return 0
    
    try:
        # Authenticate and get worksheet
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive',
        ]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(SHEET_ID)
        
        # Get the specific worksheet
        if sheet_name == "Google":
            worksheet = sh.sheet1
        elif sheet_name == "Meta":
            worksheet = sh.worksheets()[1]  # Get Sheet2
        else:
            raise ValueError(f"Invalid sheet name: {sheet_name}")
        
        most_recent_gsheet = get_most_recent_created_at(worksheet)
        logger.info(f"Most recent createdAt in {sheet_name}: {most_recent_gsheet}")
        
    except Exception as e:
        logger.error(f"Failed to get most recent createdAt from {sheet_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get most recent createdAt from {sheet_name}: {e}")

    # Filter rows based on datetime comparison
    if most_recent_gsheet is not None:
        logger.info(f"Filtering {utm_source} rows with C.Created Time after {most_recent_gsheet}")
        
        def is_newer_than_most_recent(created_time_str):
            parsed_dt = parse_input_datetime(created_time_str)
            if parsed_dt is None:
                return False  # Skip rows with unparseable datetime without logging
            return parsed_dt > most_recent_gsheet
        
        # Apply datetime filter
        filtered = filtered[filtered["C.Created Time"].apply(is_newer_than_most_recent)]
        logger.info(f"After datetime filtering for {utm_source}: {len(filtered)} rows remaining")
    else:
        logger.info(f"No existing createdAt found in {sheet_name}, will append all {utm_source} filtered rows")

    if filtered.empty:
        logger.info(f"No {utm_source} rows to append after filtering.")
        return 0

    # Map and extract only the required columns for Google Sheets
    mapped_rows = []
    for _, row in filtered.iterrows():
        mapped_row = []
        for col in GSHEET_COLUMNS:
            input_col = INPUT_TO_GSHEET[col]
            val = row.get(input_col, "")
            
            # Special handling for createdAt to convert to Google Sheet format
            if col == "createdAt":
                parsed_dt = parse_input_datetime(val)
                val = format_datetime_for_gsheet(parsed_dt)
            else:
                val = str(val).strip() if pd.notna(val) else ""
            
            mapped_row.append(val)
        mapped_rows.append(mapped_row)

    try:
        appended_count = append_to_gsheet(mapped_rows, sheet_name)
        logger.info(f"Successfully appended {appended_count} {utm_source} rows to {sheet_name}.")
        return appended_count
        
    except Exception as e:
        logger.error(f"Failed to append {utm_source} data to {sheet_name}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to append {utm_source} data to {sheet_name}: {e}")

def parse_input_datetime(datetime_str):
    """Parse datetime from input CSV/Excel format"""
    if pd.isna(datetime_str) or datetime_str == "":
        return None
    
    try:
        # Handle the format: "Jun 30, 2023 02:22 AM"
        return datetime.strptime(str(datetime_str).strip(), DATETIME_FORMAT)
    except Exception as e:
        # Skip logging datetime parsing warnings - they're expected for varied formats
        return None

def format_datetime_for_gsheet(dt):
    """Convert datetime to Google Sheet format for storage"""
    if dt is None:
        return ""
    # Keep the same format as input since Google Sheet uses the same format
    return dt.strftime(DATETIME_FORMAT)

@app.post("/upload")
def upload(file: UploadFile = File(...)):
    # Handle mixed types warning for CSV
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(file.file, low_memory=False)
        elif file.filename.endswith(".xlsx"):
            df = pd.read_excel(file.file, engine="openpyxl")
        else:
            logger.error("Unsupported file type")
            raise HTTPException(status_code=400, detail="Only .csv and .xlsx files are supported.")
    except Exception as e:
        logger.error(f"Failed to parse file: {e}")
        raise HTTPException(status_code=400, detail=f"Failed to parse file: {e}")

    # Check for required columns
    required_columns = ["C.Created Time", "C.POS PAN Number", "utm source"]
    missing = [col for col in required_columns if col not in df.columns]
    if missing:
        logger.error(f"Missing columns: {missing}")
        raise HTTPException(status_code=400, detail=f"Missing columns: {missing}")

    logger.info(f"Total rows in uploaded file: {len(df)}")

    # Process Google data (utm source = google) -> Sheet1
    google_count = filter_and_process_data(df, "google", "Google")
    
    # Process Meta data (utm source = meta) -> Sheet2  
    meta_count = filter_and_process_data(df, "meta", "Meta")

    # Create response message
    if google_count == 0 and meta_count == 0:
        message = "No rows matched the filters. Nothing appended."
    else:
        parts = []
        if google_count > 0:
            parts.append(f"{google_count} Google rows to Sheet1")
        if meta_count > 0:
            parts.append(f"{meta_count} Meta rows to Sheet2")
        message = f"Successfully appended {' and '.join(parts)}."

    logger.info(message)
    return JSONResponse({"message": message}, status_code=200)