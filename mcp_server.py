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

def tokenize_sql(sql_query: str):
    """Return SQL tokens while ignoring comments and quoted contents."""
    tokens = []
    index = 0

    while index < len(sql_query):
        char = sql_query[index]

        if char.isspace():
            index += 1
            continue

        if sql_query.startswith("--", index):
            line_end = min(
                (
                    position
                    for position in (
                        sql_query.find("\n", index + 2),
                        sql_query.find("\r", index + 2),
                    )
                    if position != -1
                ),
                default=-1,
            )
            if line_end == -1:
                index = len(sql_query)
            else:
                index = line_end + 1
                if (
                    sql_query[line_end] == "\r"
                    and index < len(sql_query)
                    and sql_query[index] == "\n"
                ):
                    index += 1
            continue

        if sql_query.startswith("/*", index):
            index += 2
            depth = 1
            while index < len(sql_query) and depth:
                if sql_query.startswith("/*", index):
                    depth += 1
                    index += 2
                elif sql_query.startswith("*/", index):
                    depth -= 1
                    index += 2
                else:
                    index += 1
            if depth:
                return None
            continue

        if char in ("'", '"', "["):
            closing = "]" if char == "[" else char
            index += 1
            while index < len(sql_query):
                if sql_query[index] == closing:
                    if index + 1 < len(sql_query) and sql_query[index + 1] == closing:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            else:
                return None
            tokens.append("QUOTED")
            continue

        if char.isalpha() or char in "_@#":
            end = index + 1
            while end < len(sql_query) and (
                sql_query[end].isalnum() or sql_query[end] in "_@$#"
            ):
                end += 1
            tokens.append(sql_query[index:end].upper())
            index = end
            continue

        tokens.append(char)
        index += 1

    return tokens


def validate_sql(sql_query: str):
    if not isinstance(sql_query, str):
        return False, "DITOLAK: sql_query harus berupa string."

    tokens = tokenize_sql(sql_query.strip())
    if tokens is None:
        return False, "DITOLAK: query memiliki komentar atau kutipan yang tidak lengkap."
    if not tokens:
        return False, "DITOLAK: query SQL kosong."

    semicolons = [index for index, token in enumerate(tokens) if token == ";"]
    if len(semicolons) > 1 or (
        semicolons and semicolons[0] != len(tokens) - 1
    ):
        return False, "DITOLAK: hanya satu statement SQL yang diperbolehkan."
    if semicolons:
        tokens.pop()

    if not tokens or tokens[0] not in {"SELECT", "WITH"}:
        return (
            False,
            "DITOLAK: hanya query SELECT atau WITH ... SELECT yang diizinkan.",
        )
    if tokens[0] == "WITH" and "SELECT" not in tokens:
        return False, "DITOLAK: query WITH harus mengandung SELECT."

    forbidden_keywords = {
        "ALTER",
        "BACKUP",
        "BEGIN",
        "BULK",
        "COMMIT",
        "CREATE",
        "DBCC",
        "DECLARE",
        "DELETE",
        "DENY",
        "DROP",
        "EXEC",
        "EXECUTE",
        "GO",
        "GRANT",
        "INSERT",
        "INTO",
        "KILL",
        "MERGE",
        "OPENQUERY",
        "OPENDATASOURCE",
        "OPENROWSET",
        "PRINT",
        "RAISERROR",
        "RESTORE",
        "REVOKE",
        "ROLLBACK",
        "SAVE",
        "SET",
        "SHUTDOWN",
        "TRAN",
        "TRANSACTION",
        "TRUNCATE",
        "UPDATE",
        "USE",
        "WAITFOR",
    }

    for token in tokens:
        if token in forbidden_keywords:
            return False, f"DITOLAK: kata kunci SQL tidak diizinkan: {token}."
        if token.startswith("XP_"):
            return False, "DITOLAK: extended procedure tidak diizinkan."
        if token == "NEXT":
            return False, "DITOLAK: akses sequence tidak diizinkan."

    return True, ""


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