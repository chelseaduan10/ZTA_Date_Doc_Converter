from flask import Flask, render_template, request, send_file
import pandas as pd
import io
import re

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024


@app.route('/')
def home():
    return render_template('index.html')


def clean_basic_name(name):
    if pd.isna(name):
        return ""
    name = str(name).strip()
    if not name:
        return ""
    name = re.sub(r"\s+", " ", name)
    return name


def normalize_template_name(name):
    name = clean_basic_name(name)
    if not name:
        return ""
    return name.title()


def normalize_sheet_name(name):
    name = clean_basic_name(name)
    if not name:
        return ""

    # Convert "Last, First" -> "First Last"
    if "," in name:
        last, first = [part.strip() for part in name.split(",", 1)]
        name = f"{first} {last}"

    return name.title()


def build_match_key(name):
    """
    Strict normalization only:
    - lowercase
    - remove punctuation
    - collapse spaces
    No nickname replacements.
    """
    name = clean_basic_name(name).lower()
    name = re.sub(r"[^a-z0-9\s]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


@app.route('/process', methods=['POST'])
def process_files():
    verisky_file = request.files['verisky']
    date_file = request.files['date_doc']

    if not verisky_file.filename.lower().endswith('.csv'):
        return "Please upload a CSV for the Verisky template."

    if not date_file.filename.lower().endswith('.csv'):
        return "Please upload a CSV for the Date Doc."

    # --------------------------------------
    # READ FILES
    # --------------------------------------
    verisky_df = pd.read_csv(verisky_file, skiprows=1)
    date_df = pd.read_csv(date_file, skiprows=1)

    verisky_df.columns = (
        verisky_df.columns
        .str.strip()
        .str.replace("\ufeff", "", regex=False)
    )
    date_df.columns = date_df.columns.str.strip()

    original_verisky_columns = verisky_df.columns.tolist()

    # --------------------------------------
    # CHECK REQUIRED TEMPLATE COLUMNS
    # --------------------------------------
    required_verisky_cols = [
        "Member Name",
        "Member Birthdate",
        "Guest 1 Name",
        "Guest 1 Birthdate",
        "Notes"
    ]

    for col in required_verisky_cols:
        if col not in verisky_df.columns:
            return f"ERROR: Verisky template is missing required column: {col}"

    # --------------------------------------
    # CHECK GOOGLE SHEET FORMAT
    # --------------------------------------
    if date_df.shape[1] != 8:
        return "ERROR: Date Doc format has changed."

    # --------------------------------------
    # BUILD CLEAN SOURCE DATAFRAME
    # --------------------------------------
    clean_date_df = pd.DataFrame({
        "Member Name": date_df.iloc[:, 1],   # Col B
        "Member DOB": date_df.iloc[:, 3],    # Col D
        "Guest Name": date_df.iloc[:, 5],    # Col F
        "Guest DOB": date_df.iloc[:, 7]      # Col H
    })

    clean_date_df = clean_date_df.dropna(how="all")

    # --------------------------------------
    # NORMALIZE NAMES
    # --------------------------------------
    clean_date_df["Member Name"] = clean_date_df["Member Name"].apply(normalize_sheet_name)
    clean_date_df["Guest Name"] = clean_date_df["Guest Name"].apply(normalize_sheet_name)
    verisky_df["Member Name"] = verisky_df["Member Name"].apply(normalize_template_name)

    # --------------------------------------
    # PARSE DATES
    # --------------------------------------
    clean_date_df["Member DOB"] = pd.to_datetime(clean_date_df["Member DOB"], errors="coerce")
    clean_date_df["Guest DOB"] = pd.to_datetime(clean_date_df["Guest DOB"], errors="coerce")
    verisky_df["Member Birthdate"] = pd.to_datetime(verisky_df["Member Birthdate"], errors="coerce")

    # --------------------------------------
    # BUILD STRICT KEYS
    # --------------------------------------
    clean_date_df["member_name_key"] = clean_date_df["Member Name"].apply(build_match_key)
    verisky_df["member_name_key"] = verisky_df["Member Name"].apply(build_match_key)

    clean_date_df["member_dob_key"] = clean_date_df["Member DOB"].dt.strftime("%Y-%m-%d").fillna("")
    verisky_df["member_dob_key"] = verisky_df["Member Birthdate"].dt.strftime("%Y-%m-%d").fillna("")

    clean_date_df["guest_dob_out"] = clean_date_df["Guest DOB"].dt.strftime("%m/%d/%Y").fillna("")

    # --------------------------------------
    # SOURCE ROWS TO USE
    # --------------------------------------
    lookup_source = clean_date_df[
        (clean_date_df["member_name_key"] != "") &
        (clean_date_df["member_dob_key"] != "")
    ][[
        "member_name_key",
        "member_dob_key",
        "Guest Name",
        "guest_dob_out",
        "Member Name"
    ]].copy()

    # --------------------------------------
    # FAIL IF DUPLICATE SOURCE KEYS EXIST
    # --------------------------------------
    duplicate_keys = lookup_source.duplicated(
        subset=["member_name_key", "member_dob_key"],
        keep=False
    )

    if duplicate_keys.any():
        dupes = lookup_source.loc[duplicate_keys, [
            "Member Name",
            "member_dob_key",
            "Guest Name",
            "guest_dob_out"
        ]].sort_values(["Member Name", "member_dob_key"])

        return (
            "ERROR: Duplicate member name + birthdate rows found in the Google Sheet CSV. "
            "Please clean the source file so each member appears only once.<br><br>"
            + dupes.to_html(index=False)
        )

    # --------------------------------------
    # BUILD EXACT LOOKUP DICTIONARY
    # --------------------------------------
    lookup_dict = {}

    for _, row in lookup_source.iterrows():
        key = (row["member_name_key"], row["member_dob_key"])
        lookup_dict[key] = {
            "guest_name": row["Guest Name"] if pd.notna(row["Guest Name"]) else "",
            "guest_dob": row["guest_dob_out"] if pd.notna(row["guest_dob_out"]) else ""
        }

    # --------------------------------------
    # POPULATE TEMPLATE ROW BY ROW
    # --------------------------------------
    guest_names = []
    guest_dobs = []

    for _, row in verisky_df.iterrows():
        key = (row["member_name_key"], row["member_dob_key"])
        match = lookup_dict.get(key)

        if match:
            guest_names.append(match["guest_name"])
            guest_dobs.append(match["guest_dob"])
        else:
            guest_names.append("")
            guest_dobs.append("")

    verisky_df["Guest 1 Name"] = guest_names
    verisky_df["Guest 1 Birthdate"] = guest_dobs
    verisky_df["Notes"] = ""

    # restore display format
    verisky_df["Member Birthdate"] = pd.to_datetime(
        verisky_df["Member Birthdate"],
        errors="coerce"
    ).dt.strftime("%m/%d/%Y").fillna("")

    # --------------------------------------
    # REMOVE HELPER COLUMNS
    # --------------------------------------
    verisky_df = verisky_df.drop(columns=["member_name_key", "member_dob_key"], errors="ignore")

    # preserve template exactly
    verisky_df = verisky_df[original_verisky_columns]
    verisky_df = verisky_df.fillna("")

    # --------------------------------------
    # OUTPUT CSV
    # --------------------------------------
    output = io.StringIO()
    verisky_df.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype='text/csv',
        as_attachment=True,
        download_name='verisky_filled.csv'
    )


if __name__ == '__main__':
    app.run(debug=False)