"""
================================================================================
CHATBOT SUPPLY LOSS
================================================================================

Fungsi:
    - Menerima pertanyaan user.
    - Memahami istilah bisnis Supply Loss.
    - Mengubah bahasa user menjadi konteks kolom database.
    - Menggunakan Ollama.
    - Menggunakan MCP untuk mengakses SQL Server.
    - Membuat filter berdasarkan BL_DATE.
    - Membuat ranking berdasarkan R4_N.
    - Menjaga aturan bisnis Supply Loss.

Database:
    DashboardSupplyLoss

Table:
    input_discharge

Model:
    llama3.2
================================================================================
"""

import asyncio
import json
import os
import re

import ollama

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# =============================================================================
# KONFIGURASI
# =============================================================================

OLLAMA_MODEL = "llama3.2"


BASE_DIR = os.path.dirname(
    os.path.abspath(__file__)
)


MCP_SERVER_PATH = os.path.join(
    BASE_DIR,
    "mcp_server.py"
)


# =============================================================================
# PARAMETER MCP SERVER
# =============================================================================

server_params = StdioServerParameters(
    command="python",
    args=[
        MCP_SERVER_PATH
    ]
)


# =============================================================================
# TOOL YANG DIKENAL OLLAMA
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",

            "description": (
                "Menjalankan query SQL SELECT atau WITH SELECT "
                "ke database Supply Loss. "
                "Gunakan tabel input_discharge. "
                "Semua data harus berasal dari database. "
                "Gunakan SUM, GROUP BY, ORDER BY, WHERE, TOP "
                "dan fungsi SQL lainnya sesuai kebutuhan."
            ),

            "parameters": {
                "type": "object",

                "properties": {

                    "sql_query": {
                        "type": "string",

                        "description": (
                            "Query SQL SELECT atau WITH SELECT "
                            "yang valid untuk tabel input_discharge."
                        )
                    }

                },

                "required": [
                    "sql_query"
                ]
            }
        }
    }
]


# =============================================================================
# KAMUS BULAN
# =============================================================================
#
# SEMUA BULAN JANUARI - DESEMBER MENGARAH KE BL_DATE.
#
# Tidak hanya June.
#
# =============================================================================

MONTH_MAP = {

    # -------------------------------------------------------------------------
    # INDONESIA
    # -------------------------------------------------------------------------

    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,

    # -------------------------------------------------------------------------
    # INGGRIS
    # -------------------------------------------------------------------------

    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,

    # -------------------------------------------------------------------------
    # SINGKATAN
    # -------------------------------------------------------------------------

    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "mei": 5,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "agu": 8,
    "ags": 8,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "okt": 10,
    "oct": 10,
    "nov": 11,
    "des": 12,
    "dec": 12,
}


# =============================================================================
# DATA DICTIONARY / BUSINESS CONTEXT
# =============================================================================

BUSINESS_CONTEXT = """
================================================================================
KONTEKS BISNIS SUPPLY LOSS
================================================================================

Kamu adalah AI Assistant yang khusus digunakan untuk membaca dan menganalisis
data Supply Loss.

Data berasal dari tabel:

    input_discharge

Semua jawaban HARUS berdasarkan data yang tersedia di database.

User tidak harus menggunakan nama kolom database secara langsung.
User dapat menggunakan bahasa sehari-hari, istilah bisnis, singkatan,
atau nama objek yang harus kamu terjemahkan terlebih dahulu ke kolom database.

Tujuan utama kamu adalah:

    Bahasa user
        ↓
    Pahami konteks Supply Loss
        ↓
    Mapping ke kolom database
        ↓
    Buat query SQL
        ↓
    Ambil data database
        ↓
    Jawab user


================================================================================
1. IDENTITAS KAPAL
================================================================================

Kolom:

    VESSEL_NAME

Makna:

    Nama kapal.

Istilah user yang dapat merujuk ke VESSEL_NAME:

    - nama kapal
    - kapal tertentu
    - vessel
    - ship
    - nama vessel
    - nama ship
    - MT. ALMI SUN
    - MT ALMI SUN
    - MT. MARAN SOLON
    - dan nama kapal lainnya

Jika user menyebut nama kapal tertentu, cari pada:

    VESSEL_NAME


CONTOH:

User:
    "Berapa loss MT. ALMI SUN?"

Maka:

    VESSEL_NAME = 'MT. ALMI SUN'


PENTING:

DESTINATION BUKAN nama kapal.

Jangan pernah menggunakan DESTINATION untuk mencari nama kapal.


================================================================================
2. ALAT ANGKUT
================================================================================

Kolom:

    ALAT_ANGKUT

Kolom ini menunjukkan jenis alat angkut.

Nilai yang relevan:

    KAPAL
    PIPELINE


Jika user mengatakan:

    kapal
    vessel
    ship

dalam konteks jenis alat angkut, gunakan:

    ALAT_ANGKUT = 'KAPAL'


Jika user mengatakan:

    pipeline
    pipa
    saluran pipa

gunakan:

    ALAT_ANGKUT = 'PIPELINE'


PENTING:

VESSEL_NAME dan ALAT_ANGKUT memiliki fungsi berbeda.


VESSEL_NAME
    = nama/identitas kapal


ALAT_ANGKUT
    = jenis alat angkut


Contoh:

    "MT. ALMI SUN"
        ↓
    VESSEL_NAME


    "kapal"
        ↓
    ALAT_ANGKUT = 'KAPAL'


    "pipeline"
        ↓
    ALAT_ANGKUT = 'PIPELINE'


================================================================================
3. TANGGAL / BULAN
================================================================================

Kolom tanggal utama:

    BL_DATE

BL_DATE berarti:

    Bill of Lading Date


SEMUA BULAN JANUARI SAMPAI DESEMBER MENGARAH KE BL_DATE.

Jangan hanya mengenali June.

Bulan yang harus dikenali adalah:

    Januari
    Februari
    Maret
    April
    Mei
    Juni
    Juli
    Agustus
    September
    Oktober
    November
    Desember


Bahasa Inggris juga harus dikenali:

    January
    February
    March
    April
    May
    June
    July
    August
    September
    October
    November
    December


Singkatan juga dapat digunakan:

    Jan
    Feb
    Mar
    Apr
    Mei / May
    Jun
    Jul
    Agu / Ags / Aug
    Sep / Sept
    Okt / Oct
    Nov
    Des / Dec


CONTOH:

    Januari
        ↓
    BL_DATE bulan 1


    Februari
        ↓
    BL_DATE bulan 2


    Maret
        ↓
    BL_DATE bulan 3


    April
        ↓
    BL_DATE bulan 4


    Mei
        ↓
    BL_DATE bulan 5


    Juni
        ↓
    BL_DATE bulan 6


    Juli
        ↓
    BL_DATE bulan 7


    Agustus
        ↓
    BL_DATE bulan 8


    September
        ↓
    BL_DATE bulan 9


    Oktober
        ↓
    BL_DATE bulan 10


    November
        ↓
    BL_DATE bulan 11


    Desember
        ↓
    BL_DATE bulan 12


================================================================================
4. BULAN + TAHUN
================================================================================

Jika user menyebut bulan DAN tahun, gunakan rentang tanggal.

Contoh:

    "Januari 2025"

berarti:

    BL_DATE >= '2025-01-01'
    AND BL_DATE < '2025-02-01'


    "Februari 2025"

berarti:

    BL_DATE >= '2025-02-01'
    AND BL_DATE < '2025-03-01'


    "Maret 2025"

berarti:

    BL_DATE >= '2025-03-01'
    AND BL_DATE < '2025-04-01'


    "April 2025"

berarti:

    BL_DATE >= '2025-04-01'
    AND BL_DATE < '2025-05-01'


    "Mei 2025"

berarti:

    BL_DATE >= '2025-05-01'
    AND BL_DATE < '2025-06-01'


    "Juni 2025"

berarti:

    BL_DATE >= '2025-06-01'
    AND BL_DATE < '2025-07-01'


    "Juli 2025"

berarti:

    BL_DATE >= '2025-07-01'
    AND BL_DATE < '2025-08-01'


    "Agustus 2025"

berarti:

    BL_DATE >= '2025-08-01'
    AND BL_DATE < '2025-09-01'


    "September 2025"

berarti:

    BL_DATE >= '2025-09-01'
    AND BL_DATE < '2025-10-01'


    "Oktober 2025"

berarti:

    BL_DATE >= '2025-10-01'
    AND BL_DATE < '2025-11-01'


    "November 2025"

berarti:

    BL_DATE >= '2025-11-01'
    AND BL_DATE < '2025-12-01'


    "Desember 2025"

berarti:

    BL_DATE >= '2025-12-01'
    AND BL_DATE < '2026-01-01'


Cara rentang tanggal lebih disarankan daripada menggunakan
MONTH(BL_DATE) jika tahun juga disebut.


================================================================================
5. BULAN TANPA TAHUN
================================================================================

Jika user hanya menyebut bulan tanpa tahun:

    "Januari"

maka gunakan:

    MONTH(BL_DATE) = 1


Jika:

    "Februari"

gunakan:

    MONTH(BL_DATE) = 2


Jika:

    "Maret"

gunakan:

    MONTH(BL_DATE) = 3


dan seterusnya sampai:

    "Desember"
        ↓
    MONTH(BL_DATE) = 12


Artinya pencarian dilakukan untuk semua tahun yang memiliki
data pada bulan tersebut.


================================================================================
6. DESTINATION
================================================================================

Kolom:

    DESTINATION

Makna:

    Tujuan pengiriman / tujuan supply.

Istilah user:

    - tujuan
    - destination
    - dikirim ke
    - dibawa ke
    - tujuan pengiriman

Jika user bertanya tentang tujuan, gunakan:

    DESTINATION


CONTOH:

    "Tujuan mana yang loss-nya paling besar?"

maka:

    GROUP BY DESTINATION

dan metrik loss:

    SUM(R4_N)


JANGAN menggunakan DESTINATION untuk mencari nama kapal.


================================================================================
7. R4_N
================================================================================

Kolom:

    R4_N

R4_N adalah metrik utama Supply Loss / Net Supply Loss.


Jika user menggunakan kata:

    - loss
    - supply loss
    - net supply loss
    - susut
    - kehilangan
    - penyusutan
    - loss terbesar
    - loss terkecil
    - penyumbang loss
    - penyumbang susut

maka secara default gunakan:

    R4_N


Untuk ranking loss:

    SUM(R4_N)


Loss terbesar:

    ORDER BY SUM(R4_N) DESC


Loss terkecil:

    ORDER BY SUM(R4_N) ASC


JANGAN menggunakan:

    ABS(R4_N)


JANGAN mengubah tanda nilai database.


================================================================================
8. TANDA R4_N
================================================================================

Nilai negatif:

    LOSS / SUSUT


Nilai positif:

    GAIN / SURPLUS


Jangan mengubah:

    -10

menjadi:

    10


Jangan menggunakan ABS.


================================================================================
9. R1, R2, R3, R4
================================================================================

Jika user menyebut:

    R1
    R2
    R3
    R4
    R4_N

anggap sebagai nama metrik/kolom.

Jangan mengganti R1, R2, R3 atau R4 dengan metrik lain
tanpa dasar dari struktur database.

Jangan mengarang definisi bisnis R1, R2 atau R3 jika
definisi tersebut belum diberikan.

Jika user bertanya langsung:

    "Berapa R1?"

maka cari kolom R1.


Jika:

    "Berapa R2?"

maka cari kolom R2.


Jika:

    "Berapa R3?"

maka cari kolom R3.


Jika:

    "Berapa R4_N?"

maka cari kolom R4_N.


================================================================================
10. DIFF_R4_NETT
================================================================================

Kolom:

    DIFF_R4_NETT

Gunakan jika user secara eksplisit meminta:

    - DIFF R4 NETT
    - selisih R4 NETT
    - perbedaan R4 dan NETT
    - selisih volume
    - physical volume
    - volume fisik
    - barrel / bbl

Jangan menggunakan DIFF_R4_NETT sebagai pengganti R4_N
untuk pertanyaan Supply Loss.


================================================================================
11. NETT
================================================================================

Kolom:

    NETT

NETT bukan R4_N.

Jika user secara eksplisit meminta:

    nett
    nilai nett
    total nett

gunakan:

    NETT


Jangan mengganti permintaan R4_N menjadi NETT.


================================================================================
12. KONVERSI ISTILAH USER
================================================================================

User tidak harus menyebut nama kolom database.

Kamu harus menerjemahkan konteks.


Contoh:

    "loss"
        ↓
    R4_N


    "susut"
        ↓
    R4_N


    "nama kapal"
        ↓
    VESSEL_NAME


    "tujuan"
        ↓
    DESTINATION


    "kapal" sebagai jenis transportasi
        ↓
    ALAT_ANGKUT = 'KAPAL'


    "pipeline"
        ↓
    ALAT_ANGKUT = 'PIPELINE'


    "Januari"
        ↓
    BL_DATE


    "Februari"
        ↓
    BL_DATE


    "Maret"
        ↓
    BL_DATE


    "April"
        ↓
    BL_DATE


    "Mei"
        ↓
    BL_DATE


    "Juni"
        ↓
    BL_DATE


    "Juli"
        ↓
    BL_DATE


    "Agustus"
        ↓
    BL_DATE


    "September"
        ↓
    BL_DATE


    "Oktober"
        ↓
    BL_DATE


    "November"
        ↓
    BL_DATE


    "Desember"
        ↓
    BL_DATE


================================================================================
13. CONTOH PEMAHAMAN PERTANYAAN
================================================================================

User:

    "Kapal penyumbang loss terbesar pada Januari"


Interpretasi:

    kapal
        →
    ALAT_ANGKUT = 'KAPAL'

    penyumbang
        →
    GROUP BY VESSEL_NAME

    loss
        →
    R4_N

    terbesar
        →
    ORDER BY SUM(R4_N) DESC

    Januari
        →
    BL_DATE bulan 1


================================================================================

User:

    "Kapal penyumbang loss terbesar pada Februari 2025"


Interpretasi:

    ALAT_ANGKUT = 'KAPAL'

    GROUP BY VESSEL_NAME

    SUM(R4_N)

    ORDER BY SUM(R4_N) DESC

    BL_DATE >= '2025-02-01'
    AND BL_DATE < '2025-03-01'


================================================================================

User:

    "Loss MT ALMI SUN pada Maret"


Interpretasi:

    VESSEL_NAME = 'MT. ALMI SUN'

    R4_N

    MONTH(BL_DATE) = 3


================================================================================

User:

    "Loss pipeline pada April 2025"


Interpretasi:

    ALAT_ANGKUT = 'PIPELINE'

    R4_N

    BL_DATE >= '2025-04-01'
    AND BL_DATE < '2025-05-01'


================================================================================

User:

    "Tujuan dengan loss terbesar pada Mei"


Interpretasi:

    DESTINATION

    SUM(R4_N)

    MONTH(BL_DATE) = 5

    ORDER BY SUM(R4_N) DESC


================================================================================

User:

    "Top 5 kapal loss terbesar pada Desember 2025"


Interpretasi:

    TOP 5

    ALAT_ANGKUT = 'KAPAL'

    GROUP BY VESSEL_NAME

    SUM(R4_N)

    BL_DATE >= '2025-12-01'
    AND BL_DATE < '2026-01-01'

    ORDER BY SUM(R4_N) DESC


================================================================================
14. ATURAN MUTLAK
================================================================================

1. Semua data harus berasal dari database.

2. Jangan mengarang angka.

3. Jangan mengarang nama kapal.

4. Jangan mengarang tujuan.

5. Jangan menggunakan DESTINATION sebagai VESSEL_NAME.

6. Jangan menggunakan VESSEL_NAME sebagai DESTINATION.

7. "Kapal" sebagai jenis alat angkut berarti:

       ALAT_ANGKUT = 'KAPAL'

8. Nama kapal tertentu berarti:

       VESSEL_NAME

9. "Pipeline" berarti:

       ALAT_ANGKUT = 'PIPELINE'

10. Semua nama bulan Januari sampai Desember berarti
    filter berdasarkan:

       BL_DATE

11. Jangan hanya mengenali June.

12. Januari sampai Desember harus semuanya dikenali.

13. Jika bulan + tahun disebut, gunakan rentang tanggal BL_DATE.

14. Jika hanya bulan disebut, gunakan bulan pada BL_DATE.

15. "Loss", "susut", dan "supply loss" secara default
    berarti:

       R4_N

16. Ranking Supply Loss menggunakan:

       SUM(R4_N)

17. Jangan menggunakan:

       ABS(R4_N)

18. Jangan mengganti R4_N dengan NETT.

19. Jangan mengganti R4_N dengan DIFF_R4_NETT.

20. Jangan menambahkan % jika user tidak meminta persentase.

21. Jangan menambahkan Rp jika user tidak meminta rupiah.

22. Jangan menambahkan satuan yang tidak berasal dari database.

23. Jangan menampilkan SQL kecuali user meminta SQL.

24. Jika data tidak ditemukan, katakan bahwa data tidak ditemukan.

25. Jika istilah user ambigu, gunakan konteks pertanyaan
    dan struktur database untuk menentukan kolom yang paling tepat.

26. Jika nilai R4_N bernilai NEGATIF (-), sebut sebagai LOSS / SUSUT.

27. Jika nilai R4_N bernilai POSITIF (+), sebut sebagai GAIN / SURPLUS, BUKAN loss.

================================================================================
15. PRIORITAS PEMAHAMAN
================================================================================

Setiap pertanyaan harus diproses dengan urutan:

1. Pahami maksud user.

2. Cari entitas:
       - kapal
       - tujuan
       - alat angkut
       - tanggal
       - bulan
       - tahun

3. Cari metrik:
       - R1
       - R2
       - R3
       - R4
       - R4_N
       - NETT
       - DIFF_R4_NETT

4. Konversikan bahasa user ke kolom database.

5. Tentukan filter.

6. Tentukan agregasi.

7. Buat query SQL.

8. Jalankan query.

9. Jawab berdasarkan hasil database.


JANGAN melakukan pencocokan kata secara literal saja.

Gunakan konteks Supply Loss untuk memahami maksud user.
"""

# =============================================================================
# FUNGSI MENCARI BULAN
# =============================================================================

def get_month_number(user_text):
    """
    Mencari bulan dari Januari sampai Desember.

    Mengembalikan:
        1 - 12

    atau:
        None
    """

    text = (
        user_text
        .lower()
        .strip()
    )


    # -------------------------------------------------------------------------
    # Urutkan dari yang paling panjang
    # -------------------------------------------------------------------------
    #
    # Agar:
    #
    # september
    #
    # diperiksa sebelum:
    #
    # sep
    #
    # -------------------------------------------------------------------------

    month_names = sorted(
        MONTH_MAP.keys(),
        key=len,
        reverse=True
    )


    for month_name in month_names:

        pattern = (
            r"(?<![a-z])"
            + re.escape(month_name)
            + r"(?![a-z])"
        )


        if re.search(
            pattern,
            text
        ):

            return MONTH_MAP[
                month_name
            ]


    return None


# =============================================================================
# FUNGSI MENCARI TAHUN
# =============================================================================

def get_year(user_text):
    """
    Mencari tahun 4 digit.

    Contoh:
        2025
        2026

    Return:
        integer atau None
    """

    match = re.search(
        r"\b(20\d{2})\b",
        user_text
    )


    if match:

        return int(
            match.group(1)
        )


    return None


# =============================================================================
# BUILD DATE FILTER
# =============================================================================

def build_date_filter(user_text):
    """
    Membuat filter BL_DATE berdasarkan bulan dan tahun.

    Semua bulan Januari - Desember diproses di sini.

    Contoh:

        Januari
        Februari
        Maret
        April
        Mei
        Juni
        Juli
        Agustus
        September
        Oktober
        November
        Desember

    semuanya mengarah ke BL_DATE.
    """

    month = get_month_number(
        user_text
    )

    year = get_year(
        user_text
    )


    # =========================================================================
    # TIDAK ADA BULAN
    # =========================================================================

    if month is None:

        return ""


    # =========================================================================
    # ADA BULAN + TAHUN
    # =========================================================================

    if year is not None:

        # ---------------------------------------------------------------------
        # Desember
        # ---------------------------------------------------------------------

        if month == 12:

            next_month = 1
            next_year = year + 1


        # ---------------------------------------------------------------------
        # Januari - November
        # ---------------------------------------------------------------------

        else:

            next_month = month + 1
            next_year = year


        return (
            " AND TRY_CONVERT(date, BL_DATE) "
            f">= '{year:04d}-{month:02d}-01' "
            "AND TRY_CONVERT(date, BL_DATE) "
            f"< '{next_year:04d}-{next_month:02d}-01'"
        )


    # =========================================================================
    # HANYA BULAN
    # =========================================================================

    return (
        " AND MONTH("
        "TRY_CONVERT(date, BL_DATE)"
        f") = {month}"
    )


# =============================================================================
# DETEKSI RANKING LOSS KAPAL
# =============================================================================

def is_loss_vessel_ranking(user_text):

    text = (
        user_text
        .lower()
    )


    has_vessel_context = any(
        phrase in text
        for phrase in [
            "kapal",
            "vessel",
            "ship",
            "mt.",
            "mt "
        ]
    )


    has_loss_context = any(
        phrase in text
        for phrase in [
            "loss",
            "susut",
            "supply loss",
            "net supply loss",
            "r4_n",
            "r4 n"
        ]
    )


    has_ranking_context = any(
        phrase in text
        for phrase in [
            "top",
            "terbesar",
            "tertinggi",
            "terbanyak",
            "paling besar",
            "paling tinggi",
            "penyumbang",
            "ranking",
            "peringkat"
        ]
    )


    return (
        has_vessel_context
        and has_loss_context
        and has_ranking_context
    )


# =============================================================================
# DETEKSI LOSS TERKECIL
# =============================================================================

def is_smallest_loss_ranking(user_text):

    text = (
        user_text
        .lower()
    )


    return any(
        phrase in text
        for phrase in [
            "terkecil",
            "terendah",
            "paling kecil",
            "paling rendah",
            "smallest",
            "lowest",
            "least"
        ]
    )


# =============================================================================
# QUERY RANKING LOSS KAPAL
# =============================================================================

def build_vessel_ranking_query(user_text):
    date_filter = build_date_filter(user_text)

    # -------------------------------------------------------------------------
    # LOSS TERKECIL (Paling mendekati 0 atau positif)
    # -------------------------------------------------------------------------
    if is_smallest_loss_ranking(user_text):
        order = "ASC"

    # -------------------------------------------------------------------------
    # LOSS TERBESAR (Paling Negatif)
    # -------------------------------------------------------------------------
    else:
        order = "DESC"

    query = (
        "SELECT TOP 5 "
        "VESSEL_NAME, "
        "SUM(R4_N) AS total_r4n "
        "FROM input_discharge "
        "WHERE ALAT_ANGKUT = 'KAPAL'"
        + date_filter
        + " GROUP BY VESSEL_NAME "
        f"ORDER BY total_r4n {order}"
    )

    return query


# =============================================================================
# DETEKSI RANKING CARGO / MUATAN
# =============================================================================

def is_cargo_vessel_ranking(user_text):

    text = (
        user_text
        .lower()
    )


    has_vessel = any(
        phrase in text
        for phrase in [
            "kapal",
            "vessel",
            "ship"
        ]
    )


    has_cargo = any(
        phrase in text
        for phrase in [
            "muatan",
            "mengangkut",
            "angkutan"
        ]
    )


    has_ranking = any(
        phrase in text
        for phrase in [
            "terbesar",
            "terbanyak",
            "tertinggi",
            "paling besar",
            "top",
            "ranking",
            "peringkat"
        ]
    )


    return (
        has_vessel
        and has_cargo
        and has_ranking
    )


# =============================================================================
# QUERY RANKING MUATAN KAPAL
# =============================================================================

def build_cargo_vessel_ranking_query(
    user_text
):

    date_filter = build_date_filter(
        user_text
    )


    query = (
        "SELECT TOP 5 "
        "VESSEL_NAME, "
        "SUM(NETT) AS total_nett "
        "FROM input_discharge "
        "WHERE ALAT_ANGKUT = 'KAPAL'"
        + date_filter
        + " GROUP BY VESSEL_NAME "
        "ORDER BY total_nett DESC"
    )


    return query


# =============================================================================
# EXTRACT SQL DARI RESPONSE MODEL
# =============================================================================

def extract_sql_from_content(
    content
):

    if not content:

        return None


    # =========================================================================
    # SQL CODE BLOCK
    # =========================================================================

    sql_match = re.search(
        r"```sql\s*(.*?)```",
        content,
        re.DOTALL | re.IGNORECASE
    )


    if sql_match:

        return (
            sql_match
            .group(1)
            .strip()
        )


    # =========================================================================
    # JSON
    # =========================================================================

    json_match = re.search(
        r'"sql_query"\s*:\s*"((?:[^"\\]|\\.)*)"',
        content,
        re.DOTALL
    )


    if json_match:

        try:

            return json.loads(
                '"' +
                json_match.group(1) +
                '"'
            )

        except json.JSONDecodeError:

            return (
                json_match
                .group(1)
                .replace(
                    '\\"',
                    '"'
                )
            )


    return None


# =============================================================================
# VALIDASI SQL
# =============================================================================

def is_safe_select_query(
    sql_query
):

    if not sql_query:

        return False


    cleaned = (
        sql_query
        .strip()
        .upper()
    )


    # -------------------------------------------------------------------------
    # HANYA SELECT / WITH
    # -------------------------------------------------------------------------

    if not (
        cleaned.startswith("SELECT")
        or cleaned.startswith("WITH")
    ):

        return False


    # -------------------------------------------------------------------------
    # KEYWORD BERBAHAYA
    # -------------------------------------------------------------------------

    forbidden = [

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
        "DENY"

    ]


    for word in forbidden:

        if re.search(
            rf"\b{word}\b",
            cleaned
        ):

            return False


    # -------------------------------------------------------------------------
    # MULTI STATEMENT
    # -------------------------------------------------------------------------

    without_final_semicolon = (
        cleaned
        .rstrip(";")
        .strip()
    )


    if ";" in without_final_semicolon:

        return False


    return True


# =============================================================================
# APPLY BUSINESS RULES
# =============================================================================

def apply_business_rules(
    user_input,
    sql_query
):

    # =========================================================================
    # 1. RANKING LOSS KAPAL
    # =========================================================================

    if is_loss_vessel_ranking(
        user_input
    ):

        return build_vessel_ranking_query(
            user_input
        )


    # =========================================================================
    # 2. RANKING MUATAN KAPAL
    # =========================================================================

    if is_cargo_vessel_ranking(
        user_input
    ):

        return build_cargo_vessel_ranking_query(
            user_input
        )


    # =========================================================================
    # 3. FILTER BULAN / TANGGAL
    # =========================================================================

    date_filter = build_date_filter(
        user_input
    )


    if date_filter:

        # ---------------------------------------------------------------------
        # Pastikan query menggunakan BL_DATE
        # ---------------------------------------------------------------------

        if "BL_DATE" not in sql_query.upper():

            # -----------------------------------------------------------------
            # Query memiliki WHERE
            # -----------------------------------------------------------------

            if re.search(
                r"\bWHERE\b",
                sql_query,
                re.IGNORECASE
            ):

                sql_query = re.sub(
                    r"\bWHERE\b",
                    "WHERE 1 = 1 AND",
                    sql_query,
                    count=1,
                    flags=re.IGNORECASE
                )

                sql_query += date_filter


            # -----------------------------------------------------------------
            # Query belum memiliki WHERE
            # -----------------------------------------------------------------

            else:

                sql_query += (
                    " WHERE 1 = 1"
                    + date_filter
                )


    return sql_query


# =============================================================================
# FUNGSI UTAMA
# =============================================================================

async def answer_question(
    user_input: str
) -> str:

    user_input = (
        user_input
        .strip()
    )


    # =========================================================================
    # VALIDASI
    # =========================================================================

    if not user_input:

        return (
            "Pertanyaan tidak boleh kosong."
        )


    # =========================================================================
    # SYSTEM PROMPT
    # =========================================================================

    system_prompt = BUSINESS_CONTEXT


    # =========================================================================
    # MCP
    # =========================================================================

    async with stdio_client(
        server_params
    ) as (
        read,
        write
    ):

        async with ClientSession(
            read,
            write
        ) as session:

            await session.initialize()


            # ================================================================
            # MESSAGE
            # ================================================================

            messages = [

                {
                    "role": "system",
                    "content": system_prompt
                },

                {
                    "role": "user",
                    "content": user_input
                }

            ]


            # ================================================================
            # TOOL LOOP
            # ================================================================

            max_tool_rounds = 4

            final_text = None


            for _ in range(
                max_tool_rounds
            ):

                response = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=messages,
                    tools=TOOLS
                )


                assistant_msg = (
                    response["message"]
                )


                # ------------------------------------------------------------
                # SIMPAN RESPONSE
                # ------------------------------------------------------------

                messages.append(
                    assistant_msg
                )


                # ============================================================
                # TIDAK ADA TOOL CALL
                # ============================================================

                if not assistant_msg.get(
                    "tool_calls"
                ):

                    content = (
                        assistant_msg.get(
                            "content",
                            ""
                        )
                    )


                    # --------------------------------------------------------
                    # Coba ekstrak SQL
                    # --------------------------------------------------------

                    sql_query = (
                        extract_sql_from_content(
                            content
                        )
                    )


                    if sql_query:

                        if not is_safe_select_query(
                            sql_query
                        ):

                            final_text = (
                                "Query yang diberikan "
                                "tidak memenuhi aturan "
                                "keamanan database."
                            )

                            break


                        sql_query = (
                            apply_business_rules(
                                user_input,
                                sql_query
                            )
                        )


                        try:

                            tool_result = (
                                await session.call_tool(
                                    "query_database",
                                    arguments={
                                        "sql_query": sql_query
                                    }
                                )
                            )


                            tool_text = (
                                tool_result
                                .content[0]
                                .text
                            )


                        except Exception as e:

                            tool_text = (
                                "Query database gagal.\n"
                                f"Error: {str(e)}"
                            )


                        messages.append({
                            "role": "tool",
                            "content": tool_text
                        })


                        continue


                    # --------------------------------------------------------
                    # Jika model belum menggunakan tool
                    # --------------------------------------------------------

                    if (
                        "query_database"
                        in content
                    ):

                        messages.append({
                            "role": "user",
                            "content": (
                                "Gunakan tool query_database "
                                "sekarang. Buat query SQL "
                                "SELECT yang sesuai dengan "
                                "konteks Supply Loss dan "
                                "pertanyaan user."
                            )
                        })


                        continue


                    # --------------------------------------------------------
                    # Jawaban biasa
                    # --------------------------------------------------------

                    final_text = content

                    break


                # ============================================================
                # ADA TOOL CALL
                # ============================================================

                for tool_call in (
                    assistant_msg["tool_calls"]
                ):

                    function = (
                        tool_call["function"]
                    )


                    args = function.get(
                        "arguments",
                        {}
                    )


                    # --------------------------------------------------------
                    # JSON STRING
                    # --------------------------------------------------------

                    if isinstance(
                        args,
                        str
                    ):

                        try:

                            args = json.loads(
                                args
                            )

                        except json.JSONDecodeError:

                            args = {}


                    # --------------------------------------------------------
                    # SQL
                    # --------------------------------------------------------

                    sql_query = args.get(
                        "sql_query",
                        ""
                    )


                    # ========================================================
                    # SQL KOSONG
                    # ========================================================

                    if not sql_query:

                        messages.append({
                            "role": "tool",
                            "content": (
                                "Query SQL tidak diberikan."
                            )
                        })

                        continue


                    # ========================================================
                    # BUSINESS RULE
                    # ========================================================

                    sql_query = (
                        apply_business_rules(
                            user_input,
                            sql_query
                        )
                    )


                    # ========================================================
                    # VALIDASI
                    # ========================================================

                    if not is_safe_select_query(
                        sql_query
                    ):

                        tool_text = (
                            "Query ditolak karena "
                            "bukan SELECT / WITH SELECT "
                            "yang aman."
                        )


                    else:

                        # ====================================================
                        # QUERY DATABASE
                        # ====================================================

                        try:

                            tool_result = (
                                await session.call_tool(
                                    "query_database",
                                    arguments={
                                        "sql_query": sql_query
                                    }
                                )
                            )


                            tool_text = (
                                tool_result
                                .content[0]
                                .text
                            )


                        except Exception as e:

                            tool_text = (
                                "Gagal menjalankan "
                                "query database.\n"
                                f"Error: {str(e)}"
                            )


                    # ========================================================
                    # KIRIM HASIL KE MODEL
                    # ========================================================

                    messages.append({
                        "role": "tool",
                        "content": tool_text
                    })


            # =================================================================
            # FINAL RESPONSE
            # =================================================================

            if final_text is None:

                response = ollama.chat(
                    model=OLLAMA_MODEL,
                    messages=messages
                )


                final_text = (
                    response["message"]
                    .get(
                        "content",
                        ""
                    )
                )


            return final_text.strip()


# =============================================================================
# TEST LANGSUNG
# =============================================================================

if __name__ == "__main__":

    question = input(
        "Pertanyaan: "
    )


    answer = asyncio.run(
        answer_question(
            question
        )
    )


    print()
    print("=" * 70)
    print("JAWABAN")
    print("=" * 70)
    print(answer)
    print("=" * 70)

