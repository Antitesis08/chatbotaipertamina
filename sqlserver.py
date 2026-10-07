"""
================================================================================
IMPORT DATA EXCEL BERSIH KE SQL SERVER
================================================================================

Fungsi:
    Membaca file Excel dari sheet REVISI
    kemudian memasukkannya ke SQL Server.

Database:
    DashboardSupplyLoss

Table:
    input_discharge

Catatan:
    - Data akan menggantikan tabel input_discharge yang sudah ada.
    - Nama kolom Excel dirapikan agar kompatibel dengan SQL Server.
================================================================================
"""

import pandas as pd
from sqlalchemy import create_engine
import warnings

warnings.filterwarnings("ignore")


# =============================================================================
# KONFIGURASI
# =============================================================================

FILEPATH = (
    r"D:\UNJANI\UNVERSITAS UNJANI\KP\PERTAMINA\Advanced Analyst"
    r"\Cleaning\programcleaning\Clean.xlsx"
)

SHEET_NAME = "REVISI"

SQL_SERVER = "localhost"
SQL_DATABASE = "DashboardSupplyLoss"

TABLE_NAME = "input_discharge"


# =============================================================================
# FUNGSI MEMBERSIHKAN NAMA KOLOM
# =============================================================================

def clean_column_name(column):
    """
    Membersihkan nama kolom Excel agar aman digunakan di SQL Server.
    """

    column = str(column).strip()

    column = (
        column
        .replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "_")
        .replace(".", "")
    )

    return column


# =============================================================================
# CONNECTION STRING
# =============================================================================

connection_string = (
    f"mssql+pyodbc://@{SQL_SERVER}/{SQL_DATABASE}"
    "?driver=ODBC+Driver+17+for+SQL+Server"
    "&trusted_connection=yes"
    "&TrustServerCertificate=yes"
)


# =============================================================================
# MAIN
# =============================================================================

def main():

    print("=" * 80)
    print("IMPORT DATA EXCEL KE SQL SERVER")
    print("=" * 80)

    # =========================================================================
    # 1. BACA EXCEL
    # =========================================================================

    print("\n[1] Membaca file Excel...")

    try:

        df = pd.read_excel(
            FILEPATH,
            sheet_name=SHEET_NAME,
            header=0
        )

    except Exception as e:

        print("Gagal membaca file Excel.")
        print("Error:", e)

        raise

    print(
        f"Data terbaca: "
        f"{df.shape[0]} baris, "
        f"{df.shape[1]} kolom"
    )


    # =========================================================================
    # 2. BERSIHKAN NAMA KOLOM
    # =========================================================================

    print("\n[2] Merapikan nama kolom...")

    df.columns = [
        clean_column_name(column)
        for column in df.columns
    ]

    print("\nKolom yang akan digunakan:")

    for column in df.columns:

        print(f" - {column}")


    # =========================================================================
    # 3. KONEKSI SQL SERVER
    # =========================================================================

    print("\n[3] Menghubungkan ke SQL Server...")

    try:

        engine = create_engine(
            connection_string
        )

        with engine.connect():

            print(
                f"Berhasil terkoneksi ke database "
                f"'{SQL_DATABASE}'."
            )

    except Exception as e:

        print("Koneksi ke SQL Server gagal.")
        print()
        print("Pastikan:")
        print("1. SQL Server sedang berjalan.")
        print("2. Database DashboardSupplyLoss tersedia.")
        print("3. ODBC Driver 17 for SQL Server terpasang.")
        print("4. Windows Authentication dapat digunakan.")
        print()
        print("Detail error:")
        print(e)

        raise


    # =========================================================================
    # 4. MASUKKAN DATA KE SQL SERVER
    # =========================================================================

    print("\n[4] Mengirim data ke SQL Server...")

    try:

        df.to_sql(
            TABLE_NAME,
            con=engine,
            if_exists="replace",
            index=False
        )

    except Exception as e:

        print("Gagal menulis data ke SQL Server.")
        print("Error:", e)

        raise


    # =========================================================================
    # 5. SELESAI
    # =========================================================================

    print()
    print("=" * 80)
    print("IMPORT BERHASIL")
    print("=" * 80)

    print(f"Tabel        : {TABLE_NAME}")
    print(f"Jumlah baris : {len(df)}")
    print(f"Jumlah kolom : {len(df.columns)}")

    print("=" * 80)


# =============================================================================
# RUN
# =============================================================================

if __name__ == "__main__":

    main()