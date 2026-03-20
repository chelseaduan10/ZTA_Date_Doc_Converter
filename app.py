from flask import Flask, render_template, request, send_file
import pandas as pd
import io
import re

app = Flask(__name__)

# option to enter names of girls not going - must delete girls off list who are not going
# if blank date next to name, leave date blank
# format of date bday


@app.route('/')
def home():
    return render_template('index.html')


NICKNAME_MAP = {
    "abby": "abigail",
    "ally": "allison",
    "catey": "catherine",
    "dani": "danielle",
    "gabby": "gabrielle",
    "jess": "jessica",
    "maggie": "marguerite",
    "nikka": "nikki",
    "sophie": "sofia",
}


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
    Creates a looser match key so names like:
    Chloe O'Neill -> chloe oneill
    """
    name = clean_basic_name(name).lower()

    # remove punctuation
    name = re.sub(r"[^a-z0-9\s]", "", name)

    # collapse whitespace
    name = re.sub(r"\s+", " ", name).strip()

    if not name:
        return ""

    parts = name.split()

    # replace common nicknames
    parts = [NICKNAME_MAP.get(part, part) for part in parts]

    return " ".join(parts)


@app.route('/process', methods=['POST'])
def process_files():
    verisky_file = request.files['verisky']   # blank template csv
    date_file = request.files['date_doc']     # google sheet csv

    # --------------------------------------
    # READ FILES
    # --------------------------------------
    verisky_df = pd.read_csv(verisky_file, skiprows=1)
    date_df = pd.read_csv(date_file, skiprows=1)

    # Clean column names only
    verisky_df.columns = (
        verisky_df.columns
        .str.strip()
        .str.replace("\ufeff", "", regex=False)
    )
    date_df.columns = date_df.columns.str.strip()

    # Save exact original template column order
    original_verisky_columns = verisky_df.columns.tolist()

    # --------------------------------------
    # CHECK REQUIRED VERISKY COLUMNS
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
    # CHECK SHEET FORMAT
    # --------------------------------------
    if date_df.shape[1] != 8:
        return "ERROR: Date Doc format has changed."

    # --------------------------------------
    # BUILD CLEAN DATE DATAFRAME
    # --------------------------------------
    clean_date_df = pd.DataFrame({
        "Member Name": date_df.iloc[:, 1],   # Col B
        "Member DOB": date_df.iloc[:, 3],    # Col D
        "Guest Name": date_df.iloc[:, 5],    # Col F
        "Guest DOB": date_df.iloc[:, 7]      # Col H
    })

    # remove spacer rows
    clean_date_df = clean_date_df.dropna(how="all")

    # --------------------------------------
    # CLEAN + NORMALIZE
    # --------------------------------------
    clean_date_df["Member Name"] = clean_date_df["Member Name"].apply(normalize_sheet_name)
    clean_date_df["Guest Name"] = clean_date_df["Guest Name"].apply(normalize_sheet_name)
    verisky_df["Member Name"] = verisky_df["Member Name"].apply(normalize_template_name)

    # datetime parsing
    clean_date_df["Member DOB"] = pd.to_datetime(clean_date_df["Member DOB"], errors="coerce")
    clean_date_df["Guest DOB"] = pd.to_datetime(clean_date_df["Guest DOB"], errors="coerce")
    verisky_df["Member Birthdate"] = pd.to_datetime(verisky_df["Member Birthdate"], errors="coerce")

    # build merge keys
    clean_date_df["member_name_key"] = clean_date_df["Member Name"].apply(build_match_key)
    verisky_df["member_name_key"] = verisky_df["Member Name"].apply(build_match_key)

    clean_date_df["member_dob_key"] = clean_date_df["Member DOB"].dt.strftime("%Y-%m-%d").fillna("")
    verisky_df["member_dob_key"] = verisky_df["Member Birthdate"].dt.strftime("%Y-%m-%d").fillna("")

    # output formatting
    clean_date_df["Guest DOB Out"] = clean_date_df["Guest DOB"].dt.strftime("%m/%d/%Y").fillna("")

    # --------------------------------------
    # BUILD LOOKUP TABLE
    # --------------------------------------
    guest_lookup = clean_date_df[[
        "member_name_key",
        "member_dob_key",
        "Guest Name",
        "Guest DOB Out"
    ]].copy()

    guest_lookup = guest_lookup.rename(columns={
        "Guest Name": "lookup_guest_name",
        "Guest DOB Out": "lookup_guest_dob"
    })

    # Remove blank keys
    guest_lookup = guest_lookup[
        (guest_lookup["member_name_key"] != "") &
        (guest_lookup["member_dob_key"] != "")
    ]

    # Keep first match if duplicates exist
    guest_lookup = guest_lookup.drop_duplicates(
        subset=["member_name_key", "member_dob_key"],
        keep="first"
    )

    # --------------------------------------
    # MERGE ONLY FOR LOOKUP
    # --------------------------------------
    merged = verisky_df.merge(
        guest_lookup,
        on=["member_name_key", "member_dob_key"],
        how="left"
    )

    # --------------------------------------
    # POPULATE EXISTING TEMPLATE COLUMNS ONLY
    # --------------------------------------
    merged["Guest 1 Name"] = merged["lookup_guest_name"].fillna("")
    merged["Guest 1 Birthdate"] = merged["lookup_guest_dob"].fillna("")
    merged["Notes"] = ""

    # restore member birthdate display
    merged["Member Birthdate"] = pd.to_datetime(
        merged["Member Birthdate"],
        errors="coerce"
    ).dt.strftime("%m/%d/%Y").fillna("")

    # --------------------------------------
    # REMOVE HELPER COLUMNS
    # --------------------------------------
    helper_cols = [
        "member_name_key",
        "member_dob_key",
        "lookup_guest_name",
        "lookup_guest_dob"
    ]

    merged = merged.drop(columns=[col for col in helper_cols if col in merged.columns])

    # preserve exact original template columns and order
    merged = merged[original_verisky_columns]

    merged = merged.fillna("")

    # --------------------------------------
    # OUTPUT CSV
    # --------------------------------------
    output = io.StringIO()
    merged.to_csv(output, index=False)
    output.seek(0)

    return send_file(
        io.BytesIO(output.getvalue().encode("utf-8")),
        mimetype='text/csv',
        as_attachment=True,
        download_name='verisky_filled.csv'
    )


if __name__ == '__main__':
    app.run(debug=True)