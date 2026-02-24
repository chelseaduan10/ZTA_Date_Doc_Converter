import pandas as pd

def process_file(filename):
    date_df = pd.read_csv(filename, sep=None, engine='python', skiprows=1)
    #for line in date_df:
        #print(line)

    if date_df.shape[1] != 8:
        print("ERROR: Date Doc format has changed.")
        print("# of columns: ", date_df.shape[1])
        return

    clean_date_df = pd.DataFrame({
        "Member Name": date_df.iloc[:, 1],
        "Member DOB": date_df.iloc[:, 3],
        "Guest Name": date_df.iloc[:, 5],
        "Guest DOB": date_df.iloc[:, 7]
    })

    print(clean_date_df.head())


if __name__ == "__main__":
    filename = input("Enter CSV filename: ")
    process_file(filename)