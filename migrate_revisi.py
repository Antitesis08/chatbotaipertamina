"""Safely prepare or apply the REVISI Excel load to dbo.input_discharge.

Default mode performs read-only preflight checks. Pass --apply explicitly to
replace the target rows inside one SQL Server transaction.
"""

import argparse
import math
import uuid
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text


WORKBOOK_PATH = Path(__file__).with_name("Clean.xlsx")
SHEET_NAME = "REVISI"
SQL_SERVER = "localhost"
SQL_DATABASE = "DashboardSupplyLoss"
SCHEMA_NAME = "dbo"
TABLE_NAME = "input_discharge"

EXPECTED_ROWS = 179
EXPECTED_COLUMNS = 60
EXPECTED_R4_N_SUM = -6.046978677852763
R4_N_SUM_TOLERANCE = 1e-12


def clean_column_name(column):
    column = str(column).strip()
    return (
        column.replace("/", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "_")
        .replace(".", "")
    )


def quote_identifier(identifier):
    return "[" + identifier.replace("]", "]]") + "]"


def qualified_table(schema, table):
    return f"{quote_identifier(schema)}.{quote_identifier(table)}"


def make_engine():
    connection_string = (
        f"mssql+pyodbc://@{SQL_SERVER}/{SQL_DATABASE}"
        "?driver=ODBC+Driver+17+for+SQL+Server"
        "&trusted_connection=yes"
        "&TrustServerCertificate=yes"
    )
    return create_engine(
        connection_string,
        fast_executemany=True,
        pool_pre_ping=True,
    )


def load_source():
    if not WORKBOOK_PATH.is_file():
        raise FileNotFoundError(f"Workbook tidak ditemukan: {WORKBOOK_PATH}")

    frame = pd.read_excel(
        WORKBOOK_PATH,
        sheet_name=SHEET_NAME,
        header=0,
    )
    frame.columns = [clean_column_name(column) for column in frame.columns]

    if len(frame) != EXPECTED_ROWS:
        raise ValueError(
            f"Jumlah baris Excel {len(frame)}; target yang disetujui "
            f"{EXPECTED_ROWS}."
        )
    if len(frame.columns) != EXPECTED_COLUMNS:
        raise ValueError(
            f"Jumlah kolom Excel {len(frame.columns)}; "
            f"target {EXPECTED_COLUMNS}."
        )
    if frame.columns.duplicated().any():
        duplicates = frame.columns[frame.columns.duplicated()].tolist()
        raise ValueError(f"Nama kolom hasil normalisasi duplikat: {duplicates}")
    if frame["NO"].isna().any() or frame["NO"].duplicated().any():
        raise ValueError("Kolom NO harus terisi dan unik.")
    if frame["R4_N"].isna().any():
        raise ValueError("R4_N mengandung NULL pada workbook sumber.")

    source_sum = float(frame["R4_N"].sum())
    if not math.isclose(
        source_sum,
        EXPECTED_R4_N_SUM,
        rel_tol=0.0,
        abs_tol=R4_N_SUM_TOLERANCE,
    ):
        raise ValueError(
            f"SUM(R4_N) Excel {source_sum} tidak sama dengan target "
            f"{EXPECTED_R4_N_SUM}."
        )
    if not (frame["R4_N"] < 0).any():
        raise ValueError("R4_N tidak memiliki nilai negatif; tanda perlu diverifikasi.")

    return frame


def expected_sql_family(series):
    if pd.api.types.is_datetime64_any_dtype(series.dtype):
        return "datetime"
    if pd.api.types.is_integer_dtype(series.dtype):
        return "bigint"
    if pd.api.types.is_float_dtype(series.dtype):
        return "float"
    if pd.api.types.is_string_dtype(series.dtype) or series.dtype == object:
        return "varchar"
    return None


def read_table_schema(connection):
    rows = connection.execute(
        text(
            """
            SELECT
                ORDINAL_POSITION,
                COLUMN_NAME,
                DATA_TYPE,
                CHARACTER_MAXIMUM_LENGTH,
                NUMERIC_PRECISION,
                NUMERIC_SCALE,
                IS_NULLABLE
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = :schema_name
              AND TABLE_NAME = :table_name
            ORDER BY ORDINAL_POSITION
            """
        ),
        {"schema_name": SCHEMA_NAME, "table_name": TABLE_NAME},
    ).mappings()
    return list(rows)


def validate_schema(connection, frame):
    schema = read_table_schema(connection)
    if not schema:
        raise RuntimeError(
            f"Tabel {SCHEMA_NAME}.{TABLE_NAME} tidak ditemukan."
        )

    source_columns = list(frame.columns)
    target_columns = [row["COLUMN_NAME"] for row in schema]
    missing = [column for column in source_columns if column not in target_columns]
    unexpected = [column for column in target_columns if column not in source_columns]
    if missing or unexpected or source_columns != target_columns:
        raise RuntimeError(
            "Struktur kolom tidak cocok. "
            f"Excel-only/missing in SQL={missing}; "
            f"SQL-only={unexpected}; urutan Excel={source_columns}; "
            f"urutan SQL={target_columns}"
        )

    mismatches = []
    for column, sql_column in zip(source_columns, schema):
        source_family = expected_sql_family(frame[column])
        target_type = sql_column["DATA_TYPE"].lower()
        compatible = (
            (source_family == "bigint" and target_type in {"bigint", "int"})
            or (source_family == "float" and target_type in {"float", "real"})
            or (
                source_family == "datetime"
                and target_type in {"datetime", "datetime2", "smalldatetime", "date"}
            )
            or (
                source_family == "varchar"
                and target_type in {"varchar", "nvarchar", "char", "nchar"}
            )
        )
        if not compatible:
            mismatches.append(
                f"{column}: pandas {frame[column].dtype} -> SQL "
                f"{sql_column['DATA_TYPE']}"
            )
    if mismatches:
        raise RuntimeError("Tipe data tidak kompatibel: " + "; ".join(mismatches))

    return schema


def table_metrics(connection, table, columns):
    quoted_table = qualified_table(SCHEMA_NAME, table)
    null_expressions = [
        "SUM(CASE WHEN "
        + quote_identifier(column)
        + " IS NULL THEN CONVERT(bigint, 1) ELSE CONVERT(bigint, 0) END) "
        + quote_identifier(f"null_{index}")
        for index, column in enumerate(columns)
    ]
    query = (
        "SELECT COUNT_BIG(*) AS row_count, "
        "COUNT_BIG(R4_N) AS r4_n_filled, "
        "SUM(R4_N) AS r4_n_sum, "
        + ", ".join(null_expressions)
        + f" FROM {quoted_table}"
    )
    row = connection.execute(text(query)).mappings().one()
    null_counts = {
        column: int(row[f"null_{index}"] or 0)
        for index, column in enumerate(columns)
    }
    return {
        "row_count": int(row["row_count"]),
        "r4_n_filled": int(row["r4_n_filled"]),
        "r4_n_sum": (
            float(row["r4_n_sum"]) if row["r4_n_sum"] is not None else None
        ),
        "null_counts": null_counts,
    }


def validate_metrics(metrics, expected_nulls, label):
    if metrics["row_count"] != EXPECTED_ROWS:
        raise RuntimeError(
            f"{label}: jumlah baris {metrics['row_count']}, "
            f"target {EXPECTED_ROWS}."
        )
    if metrics["r4_n_filled"] != EXPECTED_ROWS:
        raise RuntimeError(
            f"{label}: nilai R4_N terisi {metrics['r4_n_filled']}, "
            f"target {EXPECTED_ROWS}."
        )
    if metrics["r4_n_sum"] is None or not math.isclose(
        metrics["r4_n_sum"],
        EXPECTED_R4_N_SUM,
        rel_tol=0.0,
        abs_tol=R4_N_SUM_TOLERANCE,
    ):
        raise RuntimeError(
            f"{label}: SUM(R4_N)={metrics['r4_n_sum']}, "
            f"target {EXPECTED_R4_N_SUM}."
        )
    if metrics["null_counts"] != expected_nulls:
        differences = {
            column: (expected_nulls[column], metrics["null_counts"][column])
            for column in expected_nulls
            if expected_nulls[column] != metrics["null_counts"][column]
        }
        raise RuntimeError(f"{label}: jumlah NULL berbeda: {differences}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Ganti isi tabel utama; tanpa flag ini hanya melakukan preflight baca-saja.",
    )
    args = parser.parse_args()

    frame = load_source()
    source_nulls = {
        column: int(count) for column, count in frame.isna().sum().items()
    }
    source_metrics = {
        "row_count": len(frame),
        "r4_n_filled": int(frame["R4_N"].notna().sum()),
        "r4_n_sum": float(frame["R4_N"].sum()),
        "null_counts": source_nulls,
    }

    engine = make_engine()
    try:
        with engine.connect() as connection:
            database_name = connection.execute(text("SELECT DB_NAME()")).scalar_one()
            if database_name != SQL_DATABASE:
                raise RuntimeError(
                    f"Koneksi berada di database {database_name}, "
                    f"bukan {SQL_DATABASE}."
                )
            schema = validate_schema(connection, frame)
            current_metrics = table_metrics(
                connection,
                TABLE_NAME,
                list(frame.columns),
            )

        print(f"Workbook/sheet : {WORKBOOK_PATH} / {SHEET_NAME}")
        print(f"Database/table : {SQL_DATABASE} / {SCHEMA_NAME}.{TABLE_NAME}")
        print(f"Kolom cocok    : {len(schema)} dari {len(frame.columns)}")
        print(f"Baris sumber   : {source_metrics['row_count']}")
        print(f"SUM(R4_N) sumber: {source_metrics['r4_n_sum']:.15g}")
        print(f"Baris saat ini : {current_metrics['row_count']}")
        print(f"SUM(R4_N) saat ini: {current_metrics['r4_n_sum']}")
        print("Null source    :", source_nulls)

        if not args.apply:
            print("DRY-RUN: tidak ada perubahan database yang dilakukan.")
            return

        stage_name = f"input_discharge_stage_{uuid.uuid4().hex}"
        target = qualified_table(SCHEMA_NAME, TABLE_NAME)
        stage = qualified_table(SCHEMA_NAME, stage_name)
        columns_sql = ", ".join(quote_identifier(column) for column in frame.columns)

        with engine.begin() as connection:
            connection.exec_driver_sql("SET XACT_ABORT ON")
            connection.exec_driver_sql(
                "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"
            )
            connection.execute(
                text(
                    f"SELECT COUNT_BIG(*) FROM {target} "
                    "WITH (TABLOCKX, HOLDLOCK)"
                )
            )

            validate_schema(connection, frame)
            connection.exec_driver_sql(
                f"SELECT TOP (0) * INTO {stage} FROM {target}"
            )
            frame.to_sql(
                name=stage_name,
                schema=SCHEMA_NAME,
                con=connection,
                if_exists="append",
                index=False,
                chunksize=25,
                method="multi",
            )

            staged_metrics = table_metrics(
                connection,
                stage_name,
                list(frame.columns),
            )
            validate_metrics(staged_metrics, source_nulls, "Staging")

            connection.exec_driver_sql(f"DELETE FROM {target}")
            connection.exec_driver_sql(
                f"INSERT INTO {target} ({columns_sql}) "
                f"SELECT {columns_sql} FROM {stage}"
            )

            final_metrics = table_metrics(
                connection,
                TABLE_NAME,
                list(frame.columns),
            )
            validate_metrics(final_metrics, source_nulls, "Tabel utama")
            connection.exec_driver_sql(f"DROP TABLE {stage}")

        print("Migrasi selesai dan seluruh validasi lulus.")
        print(f"Baris akhir     : {final_metrics['row_count']}")
        print(f"SUM(R4_N) akhir : {final_metrics['r4_n_sum']}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
