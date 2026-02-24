from flask import Flask, render_template, request, send_file
import pandas as pd
import io

# consistency checks: check number of cells w 2 dates
# option to enter names of girls not going - must delete girls off list who are not going
# if blank date next to name, leave date blank
# format of date bday

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/process', methods=['POST'])
def process_files():
    verisky_file = request.files['verisky']
    date_file = request.files['date_doc']

    # --------------------------------------
    # READ FILES
    # --------------------------------------
    verisky_df = pd.read_csv(verisky_file, skiprows=1)
    date_df = pd.read_csv(date_file, sep=None, engine='python', skiprows=1)

    # Strip column names for Verisky ONLY
    verisky_df.columns = (
    verisky_df.columns
    .str.strip()
    .str.replace("\ufeff", "", regex=False)  # removes hidden BOM characters
)
    date_df.columns = date_df.columns.str.strip()

    # --------------------------------------
    # BUILD CLEAN DATE DATAFRAME 
    # --------------------------------------

    # Check to see if sheet layout has changed
    if date_df.shape[1] != 8:
        return "ERROR: Date Doc format has changed."
    
    clean_date_df = pd.DataFrame({
        "Member Name": date_df.iloc[:, 1], # Col B
        "Member DOB": date_df.iloc[:, 3], # Col D
        "Guest Name": date_df.iloc[:, 5], # Col F
        "Guest DOB": date_df.iloc[:, 7] # Col H
    })

    # --------------------------------------
    # CLEAN + NORMALIZE DATA
    # --------------------------------------

    # Clean whitespace
    clean_date_df["Member Name"] = clean_date_df["Member Name"].astype(str).str.strip()
    clean_date_df["Guest Name"] = clean_date_df["Guest Name"].astype(str).str.strip()
    verisky_df["Member Name"] = verisky_df["Member Name"].astype(str).str.strip()

    # Standardize capitalization (prevents subtle mismatches)
    clean_date_df["Member Name"] = clean_date_df["Member Name"].str.title()
    verisky_df["Member Name"] = verisky_df["Member Name"].str.title()
    clean_date_df["Guest Name"] = clean_date_df["Guest Name"].str.title()

    # --- CONVERT TO DATETIME ---
    clean_date_df["Member DOB"] = pd.to_datetime(clean_date_df["Member DOB"], errors="coerce")
    clean_date_df["Guest DOB"] = pd.to_datetime(clean_date_df["Guest DOB"], errors="coerce")

    verisky_df["Member Birthdate"] = pd.to_datetime(
    verisky_df["Member Birthdate"],
    errors="coerce"
    )

    # --- FORMAT TO SAME STRING FORMAT ---
    clean_date_df["Member DOB"] = clean_date_df["Member DOB"].dt.strftime("%m/%d/%Y")
    clean_date_df["Guest DOB"] = clean_date_df["Guest DOB"].dt.strftime("%m/%d/%Y")

    verisky_df["Member DOB"] = verisky_df["Member Birthdate"].dt.strftime("%m/%d/%Y")


    # -------------------------------------
    # MERGE ON NAME + DOB
    # -------------------------------------
    merged = verisky_df.merge(clean_date_df, on=["Member Name", "Member DOB"], how="left")

    # -------------------------------------
    # Populate columns
    # -------------------------------------
    merged["Guest 1 Name"] = merged["Guest Name"]
    merged["Guest 1 Birthdate"] = merged["Guest DOB"]

    # Ensure Notes column exists + blank
    if "Notes" not in merged.columns:
        merged["Notes"] = ""
    else:
        merged["Notes"] = ""

    # -------------------------------------
    # Only keep Verisky columns
    # -------------------------------------
    merged["Guest 1 Name"] = merged["Guest Name"]
    merged["Guest 1 Birthdate"] = merged["Guest DOB"]

    # Ensure Notes column exists + blank
    if "Notes" not in merged.columns:
        merged["Notes"] = ""
    else:
        merged["Notes"] = ""


    # -------------------------------------
    # Output CSV
    # -------------------------------------
    output = io.StringIO()
    merged.to_csv(output, index=False)
    output.seek(0)

    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='verisky_filled.csv')

if __name__ == '__main__':
    app.run(debug="True")