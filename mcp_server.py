"""
================================================================================
MCP SERVER - PENGHUBUNG AI KE DATABASE SUPPLY LOSS
================================================================================

Tools:

1. get_table_schema
   Melihat struktur tabel input_discharge.

2. query_database
   Menjalankan query SELECT / WITH ... SELECT.

Database:
    DashboardSupplyLoss

Table:
    input_discharge

Prinsip:
    - Data diambil langsung dari SQL Server.
    - Tidak ada pre-computed summary.
    - SUM, GROUP BY, ORDER BY dilakukan oleh SQL Server.
    - Hanya SELECT / WITH ... SELECT yang diperbolehkan.
    - Multi-statement SQL tidak diperbolehkan.
================================================================================
"""

from mcp.server.fastmcp import FastMCP

from sqlalchemy import create_engine, text

import warnings
import re

warnings.filterwarnings("ignore")


# =============================================================================
# KONFIGURASI DATABASE
# =============================================================================

SQL_SERVER = "localhost"
SQL_DATABASE = "DashboardSupplyLoss"

TABLE_NAME = "input_discharge"


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
# ENGINE
# =============================================================================

engine = create_engine(
    connection_string
)


# =============================================================================
# MCP
# =============================================================================

mcp = FastMCP(
    "supply-loss-data"
)


# =============================================================================
# TOOL 1 - GET TABLE SCHEMA
# =============================================================================

@mcp.tool()
def get_table_schema() -> str:
    """
    Menampilkan nama kolom dan tipe data
    yang tersedia pada tabel input_discharge.
    """

    try:

        with engine.connect() as conn:

            query = text(
                """
                SELECT
                    COLUMN_NAME,
                    DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = :table_name
                ORDER BY ORDINAL_POSITION
                """
            )

            result = conn.execute(
                query,
                {
                    "table_name": TABLE_NAME
                }
            )

            rows = result.fetchall()


        if not rows:

            return (
                f"Tidak ada kolom ditemukan "
                f"untuk tabel '{TABLE_NAME}'."
            )


        lines = [
            f"Tabel: {TABLE_NAME}",
            "Kolom yang tersedia:"
        ]


        for column_name, data_type in rows:

            lines.append(
                f" - {column_name} ({data_type})"
            )


        return "\n".join(lines)


    except Exception as e:

        return (
            "GAGAL mengambil schema.\n"
            f"Error: {str(e)}"
        )


# =============================================================================
# VALIDASI SQL
# =============================================================================

def validate_sql(sql_query: str):

    # -------------------------------------------------------------------------
    # HARUS STRING
    # -------------------------------------------------------------------------

    if not isinstance(
        sql_query,
        str
    ):

        return (
            False,
            "DITOLAK: sql_query harus berupa string."
        )


    # -------------------------------------------------------------------------
    # TRIM
    # -------------------------------------------------------------------------

    sql_query = sql_query.strip()


    if not sql_query:

        return (
            False,
            "DITOLAK: query SQL kosong."
        )


    cleaned = sql_query.upper().strip()


    # -------------------------------------------------------------------------
    # HANYA SELECT / WITH
    # -------------------------------------------------------------------------

    if not (
        cleaned.startswith("SELECT")
        or cleaned.startswith("WITH")
    ):

        return (
            False,
            "DITOLAK: hanya query SELECT "
            "atau WITH ... SELECT yang diizinkan."
        )


    # -------------------------------------------------------------------------
    # WITH HARUS MEMILIKI SELECT
    # -------------------------------------------------------------------------

    if cleaned.startswith("WITH"):

        if "SELECT" not in cleaned:

            return (
                False,
                "DITOLAK: query WITH harus "
                "mengandung SELECT."
            )


    # -------------------------------------------------------------------------
    # TIDAK BOLEH MULTI STATEMENT
    # -------------------------------------------------------------------------

    sql_without_final_semicolon = (
        cleaned
        .rstrip(";")
        .strip()
    )


    if ";" in sql_without_final_semicolon:

        return (
            False,
            "DITOLAK: hanya satu statement SQL "
            "yang diperbolehkan."
        )


    # -------------------------------------------------------------------------
    # KEYWORD BERBAHAYA
    # -------------------------------------------------------------------------

    forbidden_keywords = [

        "DROP",
        "DELETE",
        "UPDATE",
        "INSERT",
        "ALTER",
        "TRUNCATE",
        "EXEC",
        "EXECUTE",
        "CREATE",
        "MERGE",
        "GRANT",
        "REVOKE",
        "DENY",
        "BACKUP",
        "RESTORE",
        "SHUTDOWN",
        "DBCC",
        "WAITFOR",
        "OPENROWSET",
        "OPENDATASOURCE"

    ]


    for keyword in forbidden_keywords:

        pattern = (
            rf"\b{re.escape(keyword)}\b"
        )


        if re.search(
            pattern,
            cleaned
        ):

            return (
                False,
                "DITOLAK: query mengandung "
                f"kata kunci yang tidak diizinkan: {keyword}"
            )


    # -------------------------------------------------------------------------
    # XP PROCEDURE
    # -------------------------------------------------------------------------

    if re.search(
        r"\bxp_[a-zA-Z0-9_]+",
        sql_query
    ):

        return (
            False,
            "DITOLAK: extended procedure "
            "tidak diizinkan."
        )


    return (
        True,
        ""
    )


# =============================================================================
# TOOL 2 - QUERY DATABASE
# =============================================================================

@mcp.tool()
def query_database(sql_query: str) -> str:
    """
    Menjalankan query SELECT ke database Supply Loss.

    Contoh:

        SELECT TOP 5
            VESSEL_NAME,
            SUM(R4_N) AS total_r4n
        FROM input_discharge
        WHERE ALAT_ANGKUT = 'KAPAL'
        GROUP BY VESSEL_NAME
        ORDER BY total_r4n DESC
    """

    # =========================================================================
    # 1. VALIDASI
    # =========================================================================

    valid, error_message = validate_sql(
        sql_query
    )


    if not valid:

        return error_message


    # =========================================================================
    # 2. JALANKAN QUERY
    # =========================================================================

    try:

        with engine.connect() as conn:

            result = conn.execute(
                text(sql_query)
            )

            rows = result.fetchall()

            columns = list(
                result.keys()
            )


    except Exception as e:

        return (
            "Query gagal dijalankan.\n"
            f"Error: {str(e)}"
        )


    # =========================================================================
    # 3. TIDAK ADA DATA
    # =========================================================================

    if not rows:

        return (
            "Query berhasil dijalankan, "
            "tetapi tidak ada data yang ditemukan."
        )


    # =========================================================================
    # 4. HEADER
    # =========================================================================

    lines = [
        " | ".join(
            str(column)
            for column in columns
        )
    ]


    # =========================================================================
    # 5. DATA
    # =========================================================================

    for row in rows[:50]:

        lines.append(
            " | ".join(
                str(value)
                for value in row
            )
        )


    # =========================================================================
    # 6. JIKA DATA > 50 BARIS
    # =========================================================================

    if len(rows) > 50:

        lines.append(
            f"... ({len(rows) - 50} baris lainnya "
            "tidak ditampilkan)"
        )


    return "\n".join(lines)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    mcp.run(
        transport="stdio"
    )