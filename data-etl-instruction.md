# Data ETL Instructions
## Business Process Mining & Optimization Platform — Phase 1

---

## What this document covers

This document gives step-by-step instructions to set up and run the ETL (Extract, Transform, Load) pipeline for Phase 1 of the Business Process Mining & Optimization Platform. After following these instructions, your raw CSV and XES dataset files will be cleaned and stored in a PostgreSQL database, ready for process mining and analytics.

---

## Prerequisites

Before starting, confirm the following are installed and working on your machine:

| Requirement | Version | How to verify |
|---|---|---|
| Python | 3.9 or higher | `python --version` |
| PostgreSQL | 13 or higher | `psql --version` |
| pip | latest | `pip --version` |

You must also have a PostgreSQL server running locally. If you installed PostgreSQL but have not started it, run:

```bash
# macOS
brew services start postgresql

# Ubuntu / Debian
sudo service postgresql start

# Windows — open Services and start PostgreSQL
```

---

## Step 1 — Create the project folder structure

Create the following folder structure. Every file path in this document is relative to the project root folder.

```
process_mining/
├── data/
│   └── raw/                  ← place your dataset files here
├── etl/
│   ├── __init__.py
│   ├── extractor.py
│   ├── validator.py
│   ├── transformer.py
│   ├── loader.py
│   └── pipeline.py
├── database/
│   └── schema.sql
├── requirements.txt
└── main.py
```

Run these commands to create the structure:

```bash
mkdir -p process_mining/data/raw
mkdir -p process_mining/etl
mkdir -p process_mining/database
cd process_mining
touch etl/__init__.py etl/extractor.py etl/validator.py
touch etl/transformer.py etl/loader.py etl/pipeline.py
touch database/schema.sql requirements.txt main.py
```

---

## Step 2 — Install Python dependencies

Open `requirements.txt` and paste the following content exactly:

```
pandas==2.2.2
pm4py==2.7.11
sqlalchemy==2.0.30
psycopg2-binary==2.9.9
openpyxl==3.1.2
python-dotenv==1.0.1
```

Install all dependencies by running:

```bash
pip install -r requirements.txt
```

Confirm installation succeeded:

```bash
python -c "import pandas, pm4py, sqlalchemy, psycopg2; print('All dependencies OK')"
```

Expected output: `All dependencies OK`

If any import fails, re-run `pip install -r requirements.txt`.

---

## Step 3 — Download datasets

Download the following two datasets. These are the only datasets used in Phase 1.

### Dataset 1 — Helpdesk event log (CSV format)

1. Go to: `https://www.kaggle.com/datasets/ppriva/2016-helpdesk-event-log`
2. Click **Download**
3. Extract the ZIP file
4. Copy the `.csv` file into `data/raw/`
5. Rename it to exactly: `helpdesk.csv`

### Dataset 2 — BPI Challenge 2012 (XES format)

1. Go to: `https://data.4tu.nl/articles/dataset/BPI_Challenge_2012/12689204`
2. Click **Download** (the `.xes.gz` file)
3. Extract the `.gz` file to get the `.xes` file
4. Copy the `.xes` file into `data/raw/`
5. Rename it to exactly: `BPI_Challenge_2012.xes`

After this step, your `data/raw/` folder must contain exactly these two files:

```
data/raw/helpdesk.csv
data/raw/BPI_Challenge_2012.xes
```

---

## Step 4 — Create the PostgreSQL database

### 4a — Connect to PostgreSQL

```bash
psql -U postgres
```

If your PostgreSQL username is not `postgres`, replace it with your username. You will be prompted for a password.

### 4b — Create the database

Run this command inside the psql prompt:

```sql
CREATE DATABASE process_mining_db;
```

Verify it was created:

```sql
\l
```

You should see `process_mining_db` in the list. Exit psql:

```sql
\q
```

### 4c — Create the tables

Open `database/schema.sql` and paste the following content exactly:

```sql
-- Table 1: stores every cleaned event row from all datasets
CREATE TABLE IF NOT EXISTS event_log (
    id              SERIAL PRIMARY KEY,
    case_id         VARCHAR(100)  NOT NULL,
    activity        VARCHAR(200)  NOT NULL,
    timestamp       TIMESTAMPTZ   NOT NULL,
    resource        VARCHAR(200),
    wait_time_mins  FLOAT,
    cycle_time_mins FLOAT,
    source          VARCHAR(100),
    loaded_at       TIMESTAMPTZ DEFAULT NOW()
);

-- Table 2: stores one summary row per process case
CREATE TABLE IF NOT EXISTS cases (
    case_id         VARCHAR(100) PRIMARY KEY,
    source          VARCHAR(100),
    start_time      TIMESTAMPTZ,
    end_time        TIMESTAMPTZ,
    cycle_time_mins FLOAT,
    event_count     INTEGER
);

-- Table 3: stores one row per ETL run as an audit trail
CREATE TABLE IF NOT EXISTS etl_runs (
    id          SERIAL PRIMARY KEY,
    source      VARCHAR(100),
    file_path   VARCHAR(500),
    row_count   INTEGER,
    case_count  INTEGER,
    status      VARCHAR(50),
    error_msg   TEXT,
    run_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for fast queries on the event_log table
CREATE INDEX IF NOT EXISTS idx_event_case_id   ON event_log(case_id);
CREATE INDEX IF NOT EXISTS idx_event_activity  ON event_log(activity);
CREATE INDEX IF NOT EXISTS idx_event_timestamp ON event_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_event_source    ON event_log(source);
```

Run the schema file against your database:

```bash
psql -U postgres -d process_mining_db -f database/schema.sql
```

Expected output:

```
CREATE TABLE
CREATE TABLE
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
CREATE INDEX
```

---

## Step 5 — Configure the database connection

Create a file named `.env` in the project root folder:

```
process_mining/
└── .env          ← create this file
```

Paste the following into `.env`, replacing the values with your actual PostgreSQL credentials:

```env
DB_USER=postgres
DB_PASSWORD=your_password_here
DB_HOST=localhost
DB_PORT=5432
DB_NAME=process_mining_db
```

Do not add quotes around the values. Do not commit this file to Git. Add `.env` to your `.gitignore`.

---

## Step 6 — Write the ETL module files

Copy each code block below into the corresponding file exactly as written.

### 6a — `etl/extractor.py`

This file reads the raw file from disk and returns a raw Pandas DataFrame. It does not modify any data.

```python
import pandas as pd
import pm4py
import os


class Extractor:

    def extract(self, filepath: str) -> pd.DataFrame:
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        ext = os.path.splitext(filepath)[-1].lower()

        if ext == ".csv":
            return pd.read_csv(filepath)

        elif ext in (".xls", ".xlsx"):
            return pd.read_excel(filepath)

        elif ext == ".xes":
            log = pm4py.read_xes(filepath)
            return pm4py.convert_to_dataframe(log)

        else:
            raise ValueError(f"Unsupported file format: {ext}. Supported: csv, xlsx, xes")
```

### 6b — `etl/validator.py`

This file checks the extracted DataFrame for required columns, null values, and minimum row count. It returns a report dictionary, not an exception, so the pipeline can log failures cleanly.

```python
import pandas as pd

# XES files use these column names instead of the standard names
XES_REQUIRED = ["case:concept:name", "concept:name", "time:timestamp"]
STD_REQUIRED = ["case_id", "activity", "timestamp"]


class Validator:

    def validate(self, df: pd.DataFrame) -> dict:
        report = {
            "passed":    True,
            "errors":    [],
            "warnings":  [],
            "row_count": len(df)
        }

        # Check that at least one recognised column set exists
        has_standard = all(c in df.columns for c in STD_REQUIRED)
        has_xes      = all(c in df.columns for c in XES_REQUIRED)

        if not has_standard and not has_xes:
            report["passed"] = False
            report["errors"].append(
                "Missing required columns. File must contain either "
                "['case_id', 'activity', 'timestamp'] "
                "or XES columns ['case:concept:name', 'concept:name', 'time:timestamp']."
            )
            return report

        # Check for nulls in whichever column set is present
        key_cols = XES_REQUIRED if has_xes else STD_REQUIRED
        for col in key_cols:
            null_count = df[col].isnull().sum()
            if null_count > 0:
                report["warnings"].append(
                    f"Column '{col}' contains {null_count} null values. "
                    f"These rows will be dropped during transformation."
                )

        # Reject files with fewer than 10 rows
        if len(df) < 10:
            report["passed"] = False
            report["errors"].append(
                f"File contains only {len(df)} rows. Minimum required is 10."
            )

        return report
```

### 6c — `etl/transformer.py`

This file takes the raw DataFrame and returns a clean DataFrame with standardised columns, parsed timestamps, no duplicates, and two computed features: `wait_time_mins` and `cycle_time_mins`.

```python
import pandas as pd

XES_COLUMN_MAP = {
    "case:concept:name": "case_id",
    "concept:name":      "activity",
    "time:timestamp":    "timestamp",
    "org:resource":      "resource",
}


class Transformer:

    def transform(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # 1. Rename XES column names to standard names
        df = df.rename(columns=XES_COLUMN_MAP)

        # 2. Keep only the four standard columns that exist
        keep = [c for c in ["case_id", "activity", "timestamp", "resource"]
                if c in df.columns]
        df = df[keep]

        # 3. Add resource column with placeholder if not present in source
        if "resource" not in df.columns:
            df["resource"] = "unknown"

        # 4. Parse timestamp to datetime and force UTC timezone
        #    Rows with unparseable timestamps are dropped
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["case_id", "activity", "timestamp"])

        # 5. Sort all events by case then by time — required for feature engineering
        df = df.sort_values(["case_id", "timestamp"]).reset_index(drop=True)

        # 6. Remove rows that are exact duplicates on all three key columns
        df = df.drop_duplicates(subset=["case_id", "activity", "timestamp"])

        # 7. Compute wait_time_mins: time gap from the previous event in the same case
        #    The first event in each case will have NaN wait time — this is correct
        df["prev_timestamp"] = df.groupby("case_id")["timestamp"].shift(1)
        df["wait_time_mins"] = (
            (df["timestamp"] - df["prev_timestamp"])
            .dt.total_seconds() / 60
        ).round(2)
        df = df.drop(columns=["prev_timestamp"])

        # 8. Compute cycle_time_mins: total duration from first to last event per case
        bounds = df.groupby("case_id")["timestamp"].agg(
            case_start="min",
            case_end="max"
        )
        bounds["cycle_time_mins"] = (
            (bounds["case_end"] - bounds["case_start"])
            .dt.total_seconds() / 60
        ).round(2)
        df = df.merge(bounds[["cycle_time_mins"]], on="case_id", how="left")

        # 9. Normalise string fields
        df["activity"] = df["activity"].str.strip().str.lower()
        df["case_id"]  = df["case_id"].astype(str).str.strip()
        df["resource"] = df["resource"].astype(str).str.strip()

        return df
```

### 6d — `etl/loader.py`

This file takes the clean DataFrame and writes it to three PostgreSQL tables: `event_log`, `cases`, and `etl_runs`.

```python
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()


def get_engine():
    url = (
        f"postgresql://{os.getenv('DB_USER')}:{os.getenv('DB_PASSWORD')}"
        f"@{os.getenv('DB_HOST')}:{os.getenv('DB_PORT')}/{os.getenv('DB_NAME')}"
    )
    return create_engine(url)


class Loader:

    def __init__(self):
        self.engine = get_engine()

    def load(self, df: pd.DataFrame, source_name: str, filepath: str) -> dict:
        df = df.copy()
        df["source"]    = source_name
        df["loaded_at"] = datetime.now(timezone.utc)

        # Write all event rows to event_log table
        # if_exists="append" adds rows without dropping existing data
        df.to_sql(
            "event_log",
            self.engine,
            if_exists="append",
            index=False,
            method="multi",
            chunksize=1000
        )

        # Build one summary row per case and upsert into cases table
        # ON CONFLICT ensures re-running ETL does not create duplicate case rows
        cases_df = df.groupby("case_id").agg(
            start_time      = ("timestamp",       "min"),
            end_time        = ("timestamp",       "max"),
            cycle_time_mins = ("cycle_time_mins", "first"),
            event_count     = ("activity",        "count")
        ).reset_index()
        cases_df["source"] = source_name

        with self.engine.begin() as conn:
            for _, row in cases_df.iterrows():
                conn.execute(text("""
                    INSERT INTO cases
                        (case_id, source, start_time, end_time,
                         cycle_time_mins, event_count)
                    VALUES
                        (:case_id, :source, :start_time, :end_time,
                         :cycle_time_mins, :event_count)
                    ON CONFLICT (case_id) DO UPDATE SET
                        end_time        = EXCLUDED.end_time,
                        cycle_time_mins = EXCLUDED.cycle_time_mins,
                        event_count     = EXCLUDED.event_count
                """), row.to_dict())

        return {
            "rows_loaded":  len(df),
            "cases_loaded": df["case_id"].nunique()
        }
```

### 6e — `etl/pipeline.py`

This file calls Extract → Validate → Transform → Load in order. If any step fails, it logs the failure to `etl_runs` and raises the exception so you can see what went wrong.

```python
import pandas as pd
from datetime import datetime, timezone
from sqlalchemy import text

from etl.extractor   import Extractor
from etl.validator   import Validator
from etl.transformer import Transformer
from etl.loader      import Loader


class ETLPipeline:

    def __init__(self):
        self.extractor   = Extractor()
        self.validator   = Validator()
        self.transformer = Transformer()
        self.loader      = Loader()

    def run(self, filepath: str, source_name: str) -> dict:
        print(f"\n[ETL] ── Starting pipeline for: {source_name} ──")
        run_at = datetime.now(timezone.utc)

        try:
            # Step 1: Extract
            print(f"[ETL] Step 1/4 — Extracting from {filepath}")
            raw_df = self.extractor.extract(filepath)
            print(f"[ETL]   Extracted {len(raw_df)} raw rows")

            # Step 2: Validate
            print(f"[ETL] Step 2/4 — Validating")
            report = self.validator.validate(raw_df)

            for warning in report["warnings"]:
                print(f"[ETL]   WARNING: {warning}")

            if not report["passed"]:
                raise ValueError(f"Validation failed: {report['errors']}")
            print(f"[ETL]   Validation passed")

            # Step 3: Transform
            print(f"[ETL] Step 3/4 — Transforming")
            clean_df = self.transformer.transform(raw_df)
            print(f"[ETL]   Clean rows: {len(clean_df)}")
            print(f"[ETL]   Unique cases: {clean_df['case_id'].nunique()}")

            # Step 4: Load
            print(f"[ETL] Step 4/4 — Loading into PostgreSQL")
            result = self.loader.load(clean_df, source_name, filepath)

            # Log success to etl_runs
            self._log_run(source_name, filepath,
                          result["rows_loaded"], result["cases_loaded"],
                          "success", None, run_at)

            print(f"[ETL] ── Done: {result['rows_loaded']} rows, "
                  f"{result['cases_loaded']} cases loaded ──")
            return {"status": "success", **result}

        except Exception as e:
            self._log_run(source_name, filepath, 0, 0, "failed", str(e), run_at)
            print(f"[ETL] ── FAILED: {e} ──")
            raise

    def _log_run(self, source, filepath, rows, cases, status, error, run_at):
        pd.DataFrame([{
            "source":     source,
            "file_path":  filepath,
            "row_count":  rows,
            "case_count": cases,
            "status":     status,
            "error_msg":  error,
            "run_at":     run_at
        }]).to_sql("etl_runs", self.loader.engine,
                   if_exists="append", index=False)
```

### 6f — `main.py`

This is the entry point. Running this file executes the full ETL pipeline for both datasets.

```python
from etl.pipeline import ETLPipeline

if __name__ == "__main__":
    pipeline = ETLPipeline()

    # Dataset 1: Helpdesk CSV
    pipeline.run(
        filepath    = "data/raw/helpdesk.csv",
        source_name = "helpdesk"
    )

    # Dataset 2: BPI Challenge 2012 XES
    pipeline.run(
        filepath    = "data/raw/BPI_Challenge_2012.xes",
        source_name = "bpi_2012"
    )
```

---

## Step 7 — Run the ETL pipeline

From the project root folder, run:

```bash
python main.py
```

### Expected console output

```
[ETL] ── Starting pipeline for: helpdesk ──
[ETL] Step 1/4 — Extracting from data/raw/helpdesk.csv
[ETL]   Extracted 21348 raw rows
[ETL] Step 2/4 — Validating
[ETL]   Validation passed
[ETL] Step 3/4 — Transforming
[ETL]   Clean rows: 21340
[ETL]   Unique cases: 4580
[ETL] Step 4/4 — Loading into PostgreSQL
[ETL] ── Done: 21340 rows, 4580 cases loaded ──

[ETL] ── Starting pipeline for: bpi_2012 ──
[ETL] Step 1/4 — Extracting from data/raw/BPI_Challenge_2012.xes
[ETL]   Extracted 262200 raw rows
[ETL] Step 2/4 — Validating
[ETL]   Validation passed
[ETL] Step 3/4 — Transforming
[ETL]   Clean rows: 261980
[ETL]   Unique cases: 13087
[ETL] Step 4/4 — Loading into PostgreSQL
[ETL] ── Done: 261980 rows, 13087 cases loaded ──
```

Row counts may differ slightly depending on the exact file version downloaded.

---

## Step 8 — Verify data in PostgreSQL

Connect to the database:

```bash
psql -U postgres -d process_mining_db
```

Run each query below and confirm the output matches the description.

### Query 1 — confirm both datasets loaded

```sql
SELECT source, COUNT(*) AS event_count, COUNT(DISTINCT case_id) AS case_count
FROM event_log
GROUP BY source;
```

Expected: two rows, one for `helpdesk` and one for `bpi_2012`, each with non-zero counts.

### Query 2 — inspect the first 5 cleaned event rows

```sql
SELECT case_id, activity, timestamp, resource, wait_time_mins, cycle_time_mins
FROM event_log
LIMIT 5;
```

Expected: all columns populated, timestamp in UTC format, activity in lowercase.

### Query 3 — check average cycle time per dataset

```sql
SELECT source,
       ROUND(AVG(cycle_time_mins)::numeric, 2) AS avg_cycle_mins,
       ROUND(MIN(cycle_time_mins)::numeric, 2) AS min_cycle_mins,
       ROUND(MAX(cycle_time_mins)::numeric, 2) AS max_cycle_mins
FROM cases
GROUP BY source;
```

Expected: meaningful numeric values. Very large max values in BPI 2012 are normal — some loan applications take months.

### Query 4 — confirm ETL run audit trail

```sql
SELECT source, row_count, case_count, status, run_at
FROM etl_runs
ORDER BY run_at DESC;
```

Expected: two rows with `status = 'success'`.

---

## Troubleshooting

### Error: `could not connect to server`

PostgreSQL is not running. Start it using the command in the Prerequisites section.

### Error: `password authentication failed`

The `DB_PASSWORD` value in your `.env` file does not match your PostgreSQL password. Update it and retry.

### Error: `FileNotFoundError: File not found: data/raw/helpdesk.csv`

The dataset file is missing or named incorrectly. Confirm the file exists at exactly the path shown and is named exactly `helpdesk.csv`.

### Error: `Validation failed: Missing required columns`

The CSV file does not contain recognisable column names. Open the file in a text editor, check the header row, and map your column names manually by editing `XES_COLUMN_MAP` in `transformer.py`.

### Warning: `Column X contains N null values`

This is expected for some datasets. Null rows are dropped during transformation. If the number of dropped rows seems too high (more than 10% of total rows), inspect the raw file for data quality issues.

### XES file takes a long time to parse

BPI 2012 XES is a large file. PM4Py parsing can take 2–5 minutes on a standard laptop. This is normal.

---

## What the cleaned data looks like

After a successful ETL run, the `event_log` table contains rows in this exact structure:

| Column | Type | Description | Example |
|---|---|---|---|
| `id` | integer | Auto-generated row ID | 1 |
| `case_id` | string | Unique process instance identifier | `173688` |
| `activity` | string | Name of the process step (lowercase) | `a_submitted` |
| `timestamp` | timestamptz | When the event occurred (UTC) | `2012-01-08 10:38:00+00` |
| `resource` | string | Who or what performed the step | `112` |
| `wait_time_mins` | float | Minutes since the previous event in this case | `14.5` |
| `cycle_time_mins` | float | Total minutes from first to last event in this case | `2880.0` |
| `source` | string | Which dataset this row came from | `bpi_2012` |
| `loaded_at` | timestamptz | When this row was inserted by ETL | `2024-06-09 11:00:00+00` |

---

## How other platform modules consume this data

Every module in Phase 1 and beyond reads from the `event_log` table using the same pattern. No module reads a raw file directly.

```python
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql://postgres:password@localhost:5432/process_mining_db")

# Load one dataset for process discovery
df = pd.read_sql(
    "SELECT * FROM event_log WHERE source = 'bpi_2012' ORDER BY case_id, timestamp",
    engine
)

# Load all datasets combined
df_all = pd.read_sql(
    "SELECT * FROM event_log ORDER BY case_id, timestamp",
    engine
)
```

This is the only integration point any downstream module needs. The ETL pipeline is the single gatekeeper that ensures all data in the database is clean and standardised.

---

*Document version: 1.0 — Phase 1 — Business Process Mining & Optimization Platform*