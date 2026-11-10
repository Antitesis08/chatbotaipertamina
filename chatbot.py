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
import logging
import os
import re
import traceback

import ollama

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# =============================================================================
# KONFIGURASI
# =============================================================================

OLLAMA_MODEL = "llama3.2"
logger = logging.getLogger(__name__)


def ollama_error_category(error):
    class_names = {
        exception_class.__name__.lower()
        for exception_class in type(error).__mro__
    }
    message = str(error).lower()

    if (
        isinstance(error, ollama.ResponseError)
        and getattr(error, "status_code", None) == 404
        and "model" in message
        and any(term in message for term in ("not found", "does not exist"))
    ):
        return "model_not_available"
    if (
        any("timeout" in class_name for class_name in class_names)
        or "timed out" in message
    ):
        return "timeout"
    if (
        any(
            "connect" in class_name or "connection" in class_name
            for class_name in class_names
        )
        or any(
            term in message
            for term in (
                "connection refused",
                "failed to connect",
                "connection reset",
                "network is unreachable",
            )
        )
    ):
        return "connection"
    if isinstance(error, ollama.ResponseError):
        return "response"
    if isinstance(error, ollama.RequestError):
        return "request"
    return "unexpected"


def redact_ollama_log_details(value):
    value = re.sub(
        r"(?i)(https?://)[^/@\s]+:[^/@\s]+@",
        r"\1[REDACTED]@",
        value,
    )
    value = re.sub(
        r"(?i)(authorization\s*[=:]\s*['\"]?)"
        r"(?:bearer\s+)?[^\s,;}\"']+",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(
        r"(?i)(authorization|api[_-]?key|access[_-]?token|password|secret)"
        r"(\s*[=:]\s*)(['\"]?)[^'\"\s,;}]+",
        r"\1\2\3[REDACTED]",
        value,
    )
    return re.sub(
        r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+=*",
        r"\1[REDACTED]",
        value,
    )


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
# TOOL OLLAMA
# =============================================================================

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_database",

            "description": (
                "Buat satu query SELECT lengkap yang sesuai dengan "
                "pertanyaan pengguna untuk dbo.input_discharge. Gunakan "
                "hanya kolom pada schema instruksi sistem; jangan "
                "mengarang tabel atau kolom. Untuk loss saja, jumlahkan "
                "SUM(R4_N) dengan WHERE R4_N < 0; jangan gunakan ABS(). "
                "Untuk pertanyaan distribusi loss berdasarkan tujuan, "
                "gunakan query lengkap: SELECT DESTINATION, SUM(R4_N) AS "
                "total_loss FROM dbo.input_discharge WHERE R4_N < 0 GROUP "
                "BY DESTINATION ORDER BY total_loss ASC. Untuk pertanyaan "
                "tren perubahan loss berdasarkan bulan, artikan tren sebagai "
                "total loss per bulan secara kronologis (bukan selisih "
                "berjalan) dan gunakan query lengkap: SELECT YEAR(BL_DATE) "
                "AS tahun, MONTH(BL_DATE) AS bulan, SUM(R4_N) AS total_loss "
                "FROM dbo.input_discharge WHERE R4_N < 0 GROUP BY "
                "YEAR(BL_DATE), MONTH(BL_DATE) ORDER BY tahun ASC, bulan "
                "ASC. Jangan mengubah pola tersebut menjadi pivot, jangan "
                "menambah CASE, fungsi window OVER, gain/netral, atau kolom "
                "lain, dan jangan kelompokkan tren bulanan menurut "
                "DESTINATION. Patuhi instruksi sistem untuk pertanyaan lain. "
                "Isi hanya sql_query; query divalidasi sebelum dijalankan."
            ),

            "parameters": {
                "type": "object",

                "properties": {

                    "sql_query": {
                        "type": "string",

                        "description": (
                            "Satu query SQL SELECT atau WITH ... SELECT yang "
                            "valid untuk dbo.input_discharge, menggunakan "
                            "hanya kolom yang tercantum pada schema di "
                            "instruksi sistem."
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
# =============================================================================

MONTH_MAP = {

    # -------------------------------------------------------------------------
    # INDONESIA
    # -------------------------------------------------------------------------

    "januari": 1,
    "februari": 2,
    "pebruari": 2,
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

MONTH_NAMES_ID = {
    1: "Januari",
    2: "Februari",
    3: "Maret",
    4: "April",
    5: "Mei",
    6: "Juni",
    7: "Juli",
    8: "Agustus",
    9: "September",
    10: "Oktober",
    11: "November",
    12: "Desember",
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

Sebelum menjawab, bedakan pertanyaan konseptual dari permintaan data aktual.
Untuk pertanyaan definisi, arti istilah, penjelasan indikator, atau aturan
bisnis, jawab langsung berdasarkan konteks bisnis ini tanpa memanggil database.
Jangan menyertakan daftar kapal, angka total, atau hasil query yang tidak diminta.
Untuk permintaan informasi aktual, angka, peringkat, perbandingan, kapal,
tujuan, atau periode, gunakan hasil query database sebagai satu-satunya sumber
fakta. Jangan menjalankan query hanya karena pertanyaan mengandung kata
"loss", "gain", "kapal", atau "volume".

ATURAN UTAMA UNTUK DUA BENTUK PERTANYAAN:

Jika pengguna bertanya "Bagaimana distribusi loss berdasarkan tujuan
pengiriman?", gunakan query lengkap berikut sebagai pola:

    SELECT DESTINATION, SUM(R4_N) AS total_loss
    FROM dbo.input_discharge
    WHERE R4_N < 0
    GROUP BY DESTINATION
    ORDER BY total_loss ASC

Jika pengguna bertanya "Bagaimana tren perubahan loss berdasarkan bulan?",
artikan tren sebagai total loss untuk setiap bulan/tahun secara kronologis,
bukan selisih berjalan. Gunakan query lengkap berikut sebagai pola:

    SELECT YEAR(BL_DATE) AS tahun, MONTH(BL_DATE) AS bulan,
           SUM(R4_N) AS total_loss
    FROM dbo.input_discharge
    WHERE R4_N < 0
    GROUP BY YEAR(BL_DATE), MONTH(BL_DATE)
    ORDER BY tahun ASC, bulan ASC

Untuk kedua pola tersebut, jangan menambah kolom atau perhitungan lain,
jangan gunakan ABS(), dan jangan membuat query pivot. Untuk tren bulanan,
jangan gunakan CASE, fungsi window OVER, CTE, atau subquery. Terapkan pola
hanya jika sesuai maksud pertanyaan; jangan menambah filter periode yang
tidak diminta.

Data berasal dari tabel:

    input_discharge

Schema aktual tabel input_discharge (gunakan daftar ini sebagai acuan nama
kolom yang valid; jangan mengarang nama tabel atau kolom):

    NO, BL_DATE, BL_NUMBER, CQD_DATE, CQD_NUMBER, SHIPMENT_NUMBER,
    VESSEL_NAME, FROM, DESTINATION, MATERIAL_NUMBER, GRADE, GROSS, NETT,
    AFTER_LOADING, BEFORE_DISCHARGE, GROSS1, NETT1, R1_G, R2_G, R3_G,
    R4_G, R4_N, AMOUNT_G_L_TRANSPORT, Unnamed:_23, Unnamed:_24, GROSS2,
    NETT2, B_L, SHIP_TANK, MASTER_SAMPLE, Unnamed:_30, Unnamed:_31,
    Unnamed:_32, Unnamed:_33, PIPELINE_SFAL, PIPELINE_SFBD,
    PIPELINE_BL_=_AR_GROSS, PIPELINE_BL_=_AR_NETT, R1_G1, R2_G1, R3_G1,
    R4_G1, R4_N1, DIFF_R1, DIFF_R2, DIFF_R3, DIFF_R4_GROSS,
    DIFF_R4_NETT, JENIS_REPORT, JENIS_PRODUK_MQAR, BULAN,
    KODE_REPORT_ROB_OBQ, KEY_REPORT_SL, KEY_REPORT_ROBOBQ, CEK_duplicate,
    ALAT_ANGKUT, TAHUN, KEY_1_MAT, KEY_2_SN_+_MAT, CEK_SN_DUPLICATE

Schema aktual ini adalah acuan nama kolom. Jika contoh atau petunjuk lain di
konteks menyebut nama yang tidak ada pada daftar ini, jangan gunakan nama
tersebut dalam SQL.

Untuk pertanyaan tentang data, jalankan tool query_database terlebih dahulu.
Jangan menjawab dengan contoh atau usulan SQL; jawab hanya dari hasil tool
untuk pertanyaan saat ini. Jika query gagal, sampaikan bahwa data tidak dapat
diambil dan jangan membuat jawaban pengganti.
Jangan menjawab pertanyaan data dengan pengetahuan umum. Jika tool tidak
mengembalikan hasil query yang berhasil, sampaikan bahwa data tidak dapat
diambil. R4_N negatif adalah Supply Loss, positif adalah Gain/Surplus, dan
nol adalah netral.

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
    - dan nama kapal lainnya

Jika user menyebut nama kapal tertentu, cari pada:

    VESSEL_NAME

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

Jika tahun juga disebut, gunakan rentang dari hari pertama bulan yang
disebut sampai (tetapi tidak termasuk) hari pertama bulan berikutnya.
Gunakan hanya bulan dan tahun yang benar-benar diminta user.


Cara rentang tanggal lebih disarankan daripada menggunakan
MONTH(BL_DATE) jika tahun juga disebut.


================================================================================
5. BULAN TANPA TAHUN
================================================================================

Jika user hanya menyebut bulan tanpa tahun, jangan mencampur tahun.
Gunakan konteks data untuk menentukan tahun hanya jika ada tepat satu tahun
yang cocok untuk bulan/perbandingan tersebut. Jika ada beberapa tahun yang
cocok atau tahun tidak dapat ditentukan, minta klarifikasi.


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

ANALISIS LOSS BERDASARKAN TUJUAN:

Jika pengguna meminta distribusi atau total loss berdasarkan tujuan
pengiriman, kelompokkan berdasarkan DESTINATION dan hitung SUM(R4_N).
Untuk analisis loss saja, filter R4_N < 0. Urutkan total loss ASC agar nilai
paling negatif tampil lebih dahulu. Jangan gunakan ABS(R4_N), karena tanda
negatif adalah informasi Supply Loss.

Contoh pola:

    SELECT DESTINATION, SUM(R4_N) AS total_loss
    FROM dbo.input_discharge
    WHERE R4_N < 0
    GROUP BY DESTINATION
    ORDER BY total_loss ASC

Gunakan pola ini hanya jika sesuai dengan maksud pertanyaan; jangan
menambahkan filter atau batas periode yang tidak diminta.


ANALISIS TREN LOSS BERDASARKAN BULAN:

Jika pengguna meminta tren atau perubahan loss per bulan tanpa menyebut
bulan tertentu, kelompokkan menurut YEAR(BL_DATE) dan MONTH(BL_DATE), hitung
SUM(R4_N), filter R4_N < 0, dan urutkan kronologis menurut tahun lalu bulan
secara ASC. Jangan kelompokkan berdasarkan DESTINATION untuk permintaan tren
bulanan dan jangan gunakan ABS(R4_N). Pilih hanya tahun, bulan, dan total
loss; jangan menambahkan CASE, fungsi window OVER, gain/netral, atau metrik
lain. Gunakan satu SELECT langsung dari tabel, tanpa CTE atau subquery.
Tren berarti total loss per bulan secara kronologis, bukan perhitungan
perubahan berjalan. Jangan mengarang batas tahun atau periode yang tidak
disebutkan.

Contoh pola:

    SELECT YEAR(BL_DATE) AS tahun, MONTH(BL_DATE) AS bulan,
           SUM(R4_N) AS total_loss
    FROM dbo.input_discharge
    WHERE R4_N < 0
    GROUP BY YEAR(BL_DATE), MONTH(BL_DATE)
    ORDER BY tahun ASC, bulan ASC

Gunakan pola ini hanya jika sesuai dengan maksud pertanyaan; jangan
mengubah permintaan analisis lain menjadi tren bulanan.


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

Supply Loss terbesar (nilai paling negatif):

    ORDER BY SUM(R4_N) ASC

Nilai numerik R4_N tertinggi:

    ORDER BY SUM(R4_N) DESC

Supply Loss terkecil (paling dekat ke nol):

    ORDER BY SUM(R4_N) DESC


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

Nilai nol bersifat netral dan bukan LOSS maupun GAIN / SURPLUS.


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
Jika pertanyaan tidak menyebut tahun, jangan menebak tahun; filter bulan
tersebut berlaku untuk semua tahun yang memiliki data.

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

28. Jika nilai R4_N sama dengan nol, jangan sebut sebagai LOSS atau GAIN.

29. Untuk kapal dengan Supply Loss terbesar, agregasikan SUM(R4_N) per
    VESSEL_NAME dan urutkan ASC agar nilai paling negatif berada di urutan pertama.

30. Untuk nilai numerik R4_N tertinggi, urutkan SUM(R4_N) DESC.

31. Terapkan ALAT_ANGKUT = 'KAPAL' pada analisis ranking kapal.

32. Jawab hanya pertanyaan user saat ini. Jangan memakai nama kapal, periode,
    hasil, atau pertanyaan dari contoh statis maupun percakapan sebelumnya.

33. Salin tanda dan nilai R4_N persis seperti hasil query. Jangan menghilangkan
    tanda minus atau mengganti nilai dengan nilai absolut/magnitudonya.

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

def is_gain_vessel_ranking(user_text):
    text = user_text.lower()
    has_vessel_context = any(
        phrase in text for phrase in ["kapal", "vessel", "ship"]
    )
    has_gain_context = any(
        phrase in text
        for phrase in [
            "gain",
            "surplus",
            "positif",
            "positive",
            "r4_n > 0",
            "r4_n>0",
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
            "terpositif",
            "ranking",
            "peringkat",
        ]
    )
    return has_vessel_context and has_gain_context and has_ranking_context


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
        and not is_gain_vessel_ranking(user_text)
    )


def is_unfiltered_total_loss_question(user_text):
    text = user_text.lower()
    has_total_context = any(
        phrase in text
        for phrase in ["total", "jumlah keseluruhan", "grand total"]
    )
    has_loss_context = any(
        phrase in text for phrase in ["loss", "susut", "r4_n", "r4 n"]
    )
    has_scope_context = any(
        phrase in text
        for phrase in [
            "berdasarkan",
            "masing-masing",
            "per kapal",
            "per destination",
            "per tujuan",
            "per jenis",
            "kapal",
            "vessel",
            "ship",
            "pipeline",
            "destination",
            "tujuan",
            "pada",
            "untuk",
            "dari",
        ]
    ) or get_year(user_text) is not None or get_month_number(user_text) is not None

    return has_total_context and has_loss_context and not has_scope_context


def answer_conceptual_question(user_text):
    text = re.sub(r"\s+", " ", user_text.strip().lower())
    concepts = {
        "r4_n": any(term in text for term in ("r4_n", "r4 n")),
        "supply_loss": any(
            term in text for term in ("supply loss", "loss", "susut")
        ),
        "gain": any(term in text for term in ("gain", "surplus")),
        "bl_date": "bl_date" in text or "tanggal bl" in text,
        "vessel_name": any(
            term in text for term in ("vessel_name", "nama kapal")
        ),
        "transport_type": any(
            term in text
            for term in ("kapal", "pipeline", "pipa", "alat angkut")
        ),
    }
    asks_concept = any(
        re.search(pattern, text)
        for pattern in (
            r"\bapa arti\b",
            r"\bapa makna\b",
            r"\bapa yang dimaksud\b",
            r"\bapa itu\b",
            r"\bapa fungsi\b",
            r"\bapa perbedaan\b",
            r"\bjelaskan\b",
            r"\bterangkan\b",
            r"\bmengapa\b",
            r"\bkenapa\b",
            r"\bbagaimana (?:cara )?(?:memahami|menafsirkan|menginterpretasikan)\b",
        )
    )
    if not asks_concept:
        return None

    if any(
        term in text
        for term in (
            "berapa",
            "total",
            "ranking",
            "peringkat",
            "terbesar",
            "tertinggi",
            "terendah",
            "tampilkan",
            "daftar",
        )
    ) or (
        extract_vessel_name(user_text)
        or is_loss_vessel_ranking(user_text)
        or detect_destination_question(user_text)
        or extract_month_occurrences(user_text)
        or get_year(user_text)
    ):
        return None

    if concepts["r4_n"] and any(
        term in text for term in ("mengapa", "kenapa")
    ) and any(term in text for term in ("negatif", "minus")):
        return (
            "Nilai R4_N bisa berada di bawah nol jika hasil indikator pada "
            "suatu record negatif; menurut aturan bisnis, nilai tersebut "
            "dikategorikan sebagai Supply Loss. Formula rinci yang menghasilkan "
            "nilai itu tidak dijelaskan dalam konteks bisnis yang tersedia."
        )
    if concepts["r4_n"] and any(
        term in text for term in ("negatif", "positif", "gain", "surplus")
    ):
        return (
            "R4_N adalah indikator Supply Loss bersih. Nilai R4_N < 0 "
            "menunjukkan Supply Loss (kehilangan volume), R4_N > 0 "
            "menunjukkan Gain/Surplus, dan R4_N = 0 menunjukkan tidak ada "
            "selisih volume (netral)."
        )
    if concepts["supply_loss"] and concepts["gain"]:
        return (
            "Supply Loss adalah selisih volume negatif (R4_N < 0), sedangkan "
            "Gain/Surplus adalah selisih volume positif (R4_N > 0). Nilai "
            "R4_N = 0 bersifat netral."
        )
    if concepts["bl_date"]:
        return (
            "BL_DATE adalah kolom tanggal pada data discharge. Kolom ini "
            "digunakan untuk mengidentifikasi atau memfilter data berdasarkan "
            "tanggal dan periode."
        )
    if concepts["vessel_name"]:
        return (
            "VESSEL_NAME adalah kolom yang berisi nama kapal. Kolom ini "
            "digunakan untuk mengidentifikasi atau memfilter data kapal."
        )
    if concepts["transport_type"] and any(
        term in text for term in ("perbedaan", "beda", "berbeda")
    ):
        return (
            "KAPAL dan PIPELINE adalah kategori pada kolom ALAT_ANGKUT. "
            "KAPAL menunjukkan pengangkutan menggunakan kapal, sedangkan "
            "PIPELINE menunjukkan pengangkutan melalui pipa."
        )
    if concepts["supply_loss"]:
        return (
            "Supply Loss adalah kehilangan volume yang ditunjukkan oleh nilai "
            "R4_N negatif. Nilai positif menunjukkan Gain/Surplus, sedangkan "
            "nilai nol bersifat netral."
        )
    return None


def detect_destination_question(user_text):
    text = user_text.lower()
    has_destination = re.search(r"\b(?:tujuan|destination)\b", text) is not None
    if not has_destination:
        return None

    asks_gain = any(term in text for term in ("gain", "surplus"))
    asks_loss = any(term in text for term in ("loss", "susut"))
    has_ranking_context = any(
        term in text
        for term in (
            "terbesar",
            "tertinggi",
            "paling besar",
            "top",
            "ranking",
            "peringkat",
        )
    )
    has_total_context = any(
        term in text for term in ("total", "jumlah", "masing-masing")
    )
    has_per_destination = re.search(
        r"\bper\s+(?:tujuan|destination)\b", text
    ) is not None

    if asks_gain and has_ranking_context:
        return "destination_gain_ranking"
    if asks_loss and has_ranking_context:
        return "destination_loss_ranking"
    if asks_loss and (has_total_context or has_per_destination):
        return "destination_loss_by_destination"
    return None


def extract_month_mentions(user_text):
    month_names = sorted(MONTH_MAP, key=len, reverse=True)
    alternatives = "|".join(re.escape(name) for name in month_names)
    pattern = re.compile(
        r"(?<![a-z])(" + alternatives + r")(?![a-z])",
        re.IGNORECASE,
    )
    return [
        (MONTH_MAP[match.group(1).lower()], match.start(), match.end())
        for match in pattern.finditer(user_text)
    ]


def extract_month_occurrences(user_text):
    months = []
    for month, _, _ in extract_month_mentions(user_text):
        if month not in months:
            months.append(month)
    return months


def extract_month_periods(user_text):
    mentions = extract_month_mentions(user_text)
    years = [
        (int(match.group(1)), match.start(), match.end())
        for match in re.finditer(r"\b(20\d{2})\b", user_text)
    ]
    distinct_years = {year for year, _, _ in years}

    if not distinct_years:
        periods = [(month, None) for month, _, _ in mentions]
        return list(dict.fromkeys(periods))
    if len(distinct_years) == 1:
        year = next(iter(distinct_years))
        periods = [(month, year) for month, _, _ in mentions]
        return list(dict.fromkeys(periods))

    periods = []
    for index, (month, month_start, month_end) in enumerate(mentions):
        previous_end = mentions[index - 1][2] if index else 0
        next_start = mentions[index + 1][1] if index + 1 < len(mentions) else len(user_text)
        nearby_years = [
            (year, abs(year_start - month_end) if year_start >= month_end else abs(month_start - year_end))
            for year, year_start, year_end in years
            if previous_end <= year_start and year_end <= next_start
            and (
                (year_start >= month_end and year_start - month_end <= 8)
                or (year_end <= month_start and month_start - year_end <= 8)
            )
        ]
        if not nearby_years:
            return None
        periods.append((month, min(nearby_years, key=lambda item: item[1])[0]))
    return list(dict.fromkeys(periods))


def detect_monthly_supply_loss_question(user_text):
    months = extract_month_occurrences(user_text)
    if not months:
        return None

    text = user_text.lower()
    asks_loss = any(
        term in text
        for term in (
            "loss",
            "susut",
            "supply loss",
            "net supply loss",
            "kehilangan",
            "penyusutan",
        )
    )
    if not asks_loss or detect_destination_question(user_text):
        return None
    if (
        extract_vessel_name(user_text)
        or is_loss_vessel_ranking(user_text)
        or any(
            term in text
            for term in (
                "gain",
                "surplus",
                "neutral",
                "netral",
                "kapal",
                "vessel",
                "ship",
                "pipeline",
                "pipa",
                "alat angkut",
                "tren",
                "trend",
                "tanggal",
                "per hari",
            )
        )
    ):
        return None

    return months


def build_monthly_year_resolution_query(months, vessel_only=False):
    month_list = ", ".join(str(month) for month in months)
    vessel_filter = "AND ALAT_ANGKUT = 'KAPAL' " if vessel_only else ""
    return (
        "SELECT YEAR(BL_DATE) AS data_year, "
        "MONTH(BL_DATE) AS data_month "
        "FROM input_discharge "
        "WHERE BL_DATE IS NOT NULL "
        + vessel_filter
        + f"AND MONTH(BL_DATE) IN ({month_list}) "
        "GROUP BY YEAR(BL_DATE), MONTH(BL_DATE) "
        "ORDER BY data_year, data_month"
    )


def build_monthly_supply_loss_query(user_text, year=None):
    months = detect_monthly_supply_loss_question(user_text)
    if months is None:
        return None

    periods = extract_month_periods(user_text)
    if periods is None:
        return "monthly_year_clarification", None

    if year is not None:
        periods = [(month, year) for month, _ in periods]
    elif all(period_year is None for _, period_year in periods):
        return "monthly_year_resolution", build_monthly_year_resolution_query(months)
    elif any(period_year is None for _, period_year in periods):
        return "monthly_year_clarification", None

    def month_range(month, period_year):
        next_month = month + 1
        next_year = period_year
        if next_month == 13:
            next_month = 1
            next_year += 1
        start = f"{period_year:04d}-{month:02d}-01"
        end = f"{next_year:04d}-{next_month:02d}-01"
        return (
            f"(BL_DATE >= '{start}' AND BL_DATE < '{end}')"
        )

    ranges = [month_range(month, period_year) for month, period_year in periods]
    if len(periods) == 1:
        query = (
            "SELECT COUNT(*) AS row_count, "
            "SUM(CASE WHEN R4_N < 0 THEN R4_N ELSE 0 END) "
            "AS total_supply_loss "
            "FROM input_discharge WHERE "
            + ranges[0]
        )
        return "monthly_loss", query

    query = (
        "SELECT YEAR(BL_DATE) AS data_year, "
        "MONTH(BL_DATE) AS data_month, "
        "SUM(CASE WHEN R4_N < 0 THEN R4_N ELSE 0 END) "
        "AS total_supply_loss "
        "FROM input_discharge WHERE "
        + " OR ".join(ranges)
        + " GROUP BY YEAR(BL_DATE), MONTH(BL_DATE) "
        "ORDER BY data_year, data_month"
    )
    return "monthly_comparison", query


def detect_monthly_vessel_loss_ranking(user_text):
    if not is_loss_vessel_ranking(user_text):
        return None
    months = extract_month_occurrences(user_text)
    return months or None


def build_monthly_vessel_loss_ranking_query(user_text, year=None):
    months = detect_monthly_vessel_loss_ranking(user_text)
    if months is None:
        return None

    periods = extract_month_periods(user_text)
    if periods is None or len(periods) != 1:
        return "monthly_vessel_ranking_year_clarification", None

    month, period_year = periods[0]
    if year is not None:
        period_year = year
    elif period_year is None:
        return (
            "monthly_vessel_ranking_year_resolution",
            build_monthly_year_resolution_query(months, vessel_only=True),
        )

    next_month = month + 1
    next_year = period_year
    if next_month == 13:
        next_month = 1
        next_year += 1
    date_filter = (
        f"BL_DATE >= '{period_year:04d}-{month:02d}-01' "
        f"AND BL_DATE < '{next_year:04d}-{next_month:02d}-01'"
    )
    query = (
        "WITH period_stats AS ("
        "SELECT COUNT(*) AS period_row_count "
        "FROM dbo.input_discharge "
        f"WHERE {date_filter} AND ALAT_ANGKUT = 'KAPAL'"
        "), vessel_losses AS ("
        "SELECT VESSEL_NAME, SUM(R4_N) AS total_supply_loss, "
        "COUNT(CASE WHEN R4_N < 0 THEN 1 END) AS jumlah_transaksi_loss "
        "FROM dbo.input_discharge "
        f"WHERE {date_filter} AND ALAT_ANGKUT = 'KAPAL' "
        "GROUP BY VESSEL_NAME"
        " HAVING SUM(R4_N) < 0"
        "), top_losses AS ("
        "SELECT TOP 5 VESSEL_NAME, total_supply_loss, jumlah_transaksi_loss "
        "FROM vessel_losses ORDER BY total_supply_loss ASC, VESSEL_NAME ASC"
        ") "
        "SELECT top_losses.VESSEL_NAME, top_losses.total_supply_loss, "
        "top_losses.jumlah_transaksi_loss, period_stats.period_row_count "
        "FROM top_losses CROSS JOIN period_stats "
        "UNION ALL "
        "SELECT NULL AS VESSEL_NAME, NULL AS total_supply_loss, "
        "0 AS jumlah_transaksi_loss, period_stats.period_row_count "
        "FROM period_stats "
        "WHERE period_stats.period_row_count = 0 "
        "OR NOT EXISTS (SELECT 1 FROM top_losses)"
    )
    return "monthly_vessel_loss_ranking", query


def build_destination_query(user_text):
    intent = detect_destination_question(user_text)
    if intent is None:
        return None

    date_filter = build_date_filter(user_text)
    where_clause = ""
    if date_filter:
        where_clause = " WHERE 1 = 1" + date_filter

    if intent == "destination_gain_ranking":
        query = (
            "SELECT TOP 1 DESTINATION, "
            "SUM(CASE WHEN R4_N > 0 THEN R4_N ELSE 0 END) "
            "AS total_gain_surplus "
            "FROM input_discharge"
            + where_clause
            + " GROUP BY DESTINATION "
            "ORDER BY total_gain_surplus DESC, DESTINATION ASC"
        )
    else:
        query = (
            "SELECT "
            + ("TOP 1 " if intent == "destination_loss_ranking" else "")
            + "DESTINATION, "
            "SUM(CASE WHEN R4_N < 0 THEN R4_N ELSE 0 END) "
            "AS total_supply_loss "
            "FROM input_discharge"
            + where_clause
            + " GROUP BY DESTINATION "
            "ORDER BY total_supply_loss ASC, DESTINATION ASC"
        )

    return intent, query


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
# DETEKSI NILAI NUMERIK TERTINGGI
# =============================================================================

def is_numeric_highest_vessel_ranking(user_text):
    text = user_text.lower()
    has_vessel_context = any(
        phrase in text for phrase in ["kapal", "vessel", "ship", "mt.", "mt "]
    )
    explicit_numeric_highest = any(
        phrase in text
        for phrase in [
            "nilai numerik tertinggi",
            "angka numerik tertinggi",
            "nilai numerik paling tinggi",
            "nilai numerik terbesar",
            "highest numeric value",
            "maximum numeric value",
            "r4_n tertinggi",
            "r4_n paling tinggi",
        ]
    )
    has_loss_context = any(
        phrase in text
        for phrase in ["loss", "susut", "supply loss", "r4_n", "r4 n"]
    )
    general_numeric_highest = any(
        phrase in text
        for phrase in [
            "nilai tertinggi",
            "nilai paling tinggi",
            "angka tertinggi",
            "angka paling tinggi",
            "highest value",
            "maximum value",
        ]
    )

    return has_vessel_context and (
        explicit_numeric_highest
        or (general_numeric_highest and not has_loss_context)
    )


# =============================================================================
# QUERY RANKING LOSS KAPAL
# =============================================================================

def build_vessel_ranking_query(user_text):
    date_filter = build_date_filter(user_text)
    top_match = re.search(r"\btop\s+(\d+)\b", user_text, re.IGNORECASE)
    top_count = min(int(top_match.group(1)), 50) if top_match else 1

    if is_numeric_highest_vessel_ranking(user_text):
        return (
            f"SELECT TOP {top_count} "
            "VESSEL_NAME, "
            "SUM(R4_N) AS total_supply_loss "
            "FROM input_discharge "
            "WHERE ALAT_ANGKUT = 'KAPAL' AND R4_N < 0"
            + date_filter
            + " GROUP BY VESSEL_NAME "
            "ORDER BY total_supply_loss DESC, VESSEL_NAME ASC"
        )

    order = (
        "DESC"
        if is_smallest_loss_ranking(user_text)
        else "ASC"
    )

    query = (
        f"SELECT TOP {top_count} "
        "VESSEL_NAME, "
        "SUM(R4_N) AS total_supply_loss "
        "FROM input_discharge "
        "WHERE ALAT_ANGKUT = 'KAPAL'"
        + date_filter
        + " GROUP BY VESSEL_NAME HAVING SUM(R4_N) < 0 "
        f"ORDER BY total_supply_loss {order}, VESSEL_NAME ASC"
    )

    return query


def build_vessel_gain_ranking_query(user_text):
    date_filter = build_date_filter(user_text)
    top_match = re.search(r"\btop\s+(\d+)\b", user_text, re.IGNORECASE)
    top_count = min(int(top_match.group(1)), 50) if top_match else 1
    return (
        f"SELECT TOP {top_count} "
        "VESSEL_NAME, "
        "SUM(R4_N) AS total_gain_surplus "
        "FROM input_discharge "
        "WHERE ALAT_ANGKUT = 'KAPAL'"
        + date_filter
        + " GROUP BY VESSEL_NAME HAVING SUM(R4_N) > 0 "
        "ORDER BY total_gain_surplus DESC, VESSEL_NAME ASC"
    )


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

    destination_query = build_destination_query(user_input)
    if destination_query:
        return destination_query[1]

    monthly_vessel_ranking_query = build_monthly_vessel_loss_ranking_query(
        user_input
    )
    if (
        monthly_vessel_ranking_query
        and monthly_vessel_ranking_query[1] is not None
    ):
        return monthly_vessel_ranking_query[1]

    monthly_loss_query = build_monthly_supply_loss_query(user_input)
    if monthly_loss_query and monthly_loss_query[1] is not None:
        return monthly_loss_query[1]

    if is_unfiltered_total_loss_question(user_input):
        return (
            "SELECT SUM(R4_N) AS total_supply_loss "
            "FROM input_discharge "
            "WHERE R4_N < 0"
        )

    if is_gain_vessel_ranking(user_input):
        return build_vessel_gain_ranking_query(user_input)

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

    if is_numeric_highest_vessel_ranking(user_input):
        return build_vessel_ranking_query(user_input)


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


def extract_vessel_name(user_text):
    name = extract_vessel_lookup_name(user_text)
    return name.upper() if name else None


def is_vessel_existence_question(user_text):
    has_vessel_reference = re.search(
        r"\b(?:kapal|vessel|ship)\b|"
        r"\b(?:MT|MV|KM)\.?\s+[A-Z0-9]",
        user_text,
        re.IGNORECASE,
    )
    has_lookup_intent = re.search(
        r"\b(?:apakah|ada|tersedia|terdapat|terdaftar|tercatat|"
        r"ditemukan|cari|carikan|tampilkan|tunjukkan|cek|periksa)\b|"
        r"\bdalam\s+database\b|\bdi\s+database\b|\bdi\s+data\b",
        user_text,
        re.IGNORECASE,
    )
    return has_vessel_reference is not None and has_lookup_intent is not None


def extract_vessel_lookup_name(user_text):
    if re.search(
        r"\bkapal\s+yang\s+(?:tidak\s+)?"
        r"(?:terdaftar|tercatat|dikenal|ada)\b",
        user_text,
        re.IGNORECASE,
    ):
        return None

    prefix_match = re.search(
        r"\b(?:MT|MV|KM)\.?\s+(.+)",
        user_text,
        re.IGNORECASE,
    )
    vessel_match = re.search(
        r"\b(?:kapal|vessel|ship)\s+"
        r"(?:(?:yang\s+)?(?:dengan\s+nama|bernama)\s+)?(.+)",
        user_text,
        re.IGNORECASE,
    )

    if prefix_match:
        prefix = re.search(r"\b(?:MT|MV|KM)\.?", user_text, re.IGNORECASE)
        name = prefix.group(0) + " " + prefix_match.group(1)
    elif vessel_match:
        name = vessel_match.group(1)
    else:
        return None

    name = re.split(
        r"\b(?:tersedia|ada|terdapat|terdaftar|tercatat|ditemukan|"
        r"dalam\s+database|di\s+database|di\s+data|loss|susut|gain|"
        r"surplus|supply|r4_n|r4\s+n|pada|bulan|tahun|tanggal|"
        r"terbesar|tertinggi|terendah|ranking|peringkat|top|"
        r"berapa|total|dengan\s+nilai|yang\s+memiliki)\b",
        name,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0].strip(" \t\r\n?.!,;:")
    name = re.sub(
        r"^(?:dengan\s+nama|yang\s+bernama|bernama)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )
    if not name or name.lower() in {
        "ada",
        "mana",
        "yang",
        "apa",
        "data",
        "supply",
        "kapal",
        "dengan",
        "berdasarkan",
        "untuk",
        "pada",
        "loss",
        "susut",
        "gain",
        "surplus",
        "ranking",
        "top",
    }:
        return None
    return re.sub(r"\s+", " ", name)


def vessel_name_candidates(vessel_name):
    normalized_name = re.sub(r"\s+", " ", vessel_name.strip()).upper()
    base_name = re.sub(r"^(?:MT|MV|KM)\.?\s+", "", normalized_name)
    return list(dict.fromkeys(
        (
            normalized_name,
            base_name,
            f"MT. {base_name}",
            f"MT {base_name}",
            f"MV. {base_name}",
            f"MV {base_name}",
            f"KM. {base_name}",
            f"KM {base_name}",
        )
    ))


def vessel_name_filter_sql(vessel_name):
    candidate_names = vessel_name_candidates(vessel_name)
    escaped_candidates = [
        "'" + candidate.replace("'", "''") + "'"
        for candidate in candidate_names
    ]
    return (
        "UPPER(LTRIM(RTRIM(VESSEL_NAME))) IN ("
        + ", ".join(escaped_candidates)
        + ")"
    )


def build_vessel_lookup_query(vessel_name, user_text=None):
    vessel_filter = vessel_name_filter_sql(vessel_name)
    normalized_name = re.sub(r"\s+", " ", vessel_name.strip()).upper()
    escaped_name = normalized_name.replace("'", "''")
    return (
        "SELECT TOP 1 VESSEL_NAME "
        "FROM input_discharge "
        "WHERE ALAT_ANGKUT = 'KAPAL' "
        "AND "
        + vessel_filter
        + build_date_filter(user_text or "")
        + " "
        "ORDER BY CASE UPPER(LTRIM(RTRIM(VESSEL_NAME))) "
        f"WHEN '{escaped_name}' THEN 0 ELSE 1 END, VESSEL_NAME"
    )


def build_targeted_supply_loss_query(user_text):
    text = user_text.lower()
    destination_query = build_destination_query(user_text)
    if destination_query:
        intent, query = destination_query
        return intent, None, query

    monthly_vessel_ranking_query = build_monthly_vessel_loss_ranking_query(
        user_text
    )
    if monthly_vessel_ranking_query:
        intent, query = monthly_vessel_ranking_query
        return intent, None, query

    monthly_loss_query = build_monthly_supply_loss_query(user_text)
    if monthly_loss_query:
        intent, query = monthly_loss_query
        return intent, None, query

    if is_vessel_existence_question(user_text):
        vessel_name = extract_vessel_lookup_name(user_text)
        if not vessel_name:
            return "vessel_lookup_clarification", None, None
        if get_month_number(user_text) is not None and get_year(user_text) is None:
            return "vessel_period_year_clarification", vessel_name, None
        return (
            "vessel_lookup",
            vessel_name,
            build_vessel_lookup_query(vessel_name, user_text),
        )

    if is_gain_vessel_ranking(user_text):
        if get_month_number(user_text) is not None and get_year(user_text) is None:
            return "ranking_period_year_clarification", None, None
        return (
            "gain_ranking",
            None,
            build_vessel_gain_ranking_query(user_text),
        )

    if is_loss_vessel_ranking(user_text):
        return "loss_ranking", None, build_vessel_ranking_query(user_text)

    vessel_name = extract_vessel_name(user_text)
    asks_gain = any(word in text for word in ("gain", "surplus"))
    asks_loss = any(word in text for word in ("loss", "susut"))

    if vessel_name and (asks_gain or asks_loss):
        if get_month_number(user_text) is not None and get_year(user_text) is None:
            return "vessel_period_year_clarification", vessel_name, None
        query = (
            "SELECT MAX(VESSEL_NAME) AS VESSEL_NAME, COUNT(*) AS row_count, "
            "SUM(CASE WHEN R4_N < 0 THEN R4_N ELSE 0 END) AS supply_loss, "
            "SUM(CASE WHEN R4_N > 0 THEN R4_N ELSE 0 END) AS gain_surplus "
            "FROM input_discharge "
            "WHERE ALAT_ANGKUT = 'KAPAL' "
            "AND "
            + vessel_name_filter_sql(vessel_name)
            + build_date_filter(user_text)
        )
        intent = "vessel_gain" if asks_gain and not asks_loss else "vessel_loss"
        return intent, vessel_name, query

    if is_unfiltered_total_loss_question(user_text):
        return (
            "total_loss",
            None,
            "SELECT SUM(R4_N) AS total_supply_loss "
            "FROM input_discharge WHERE R4_N < 0",
        )

    return None


def validate_query_semantics(user_text, sql_query):
    normalized = re.sub(r"\s+", " ", sql_query).upper()
    if not re.search(r"\bFROM\s+(?:\[?DBO\]?\.)?\[?INPUT_DISCHARGE\]?\b", normalized):
        return False

    targeted_query = build_targeted_supply_loss_query(user_text)
    if targeted_query and targeted_query[0] in {
        "vessel_lookup",
        "vessel_loss",
        "vessel_gain",
    }:
        expected = re.sub(r"\s+", " ", targeted_query[2].upper())
        return normalized == expected

    if is_vessel_existence_question(user_text):
        vessel_name = extract_vessel_lookup_name(user_text)
        if not vessel_name:
            return False
        expected = build_vessel_lookup_query(vessel_name, user_text)
        return normalized == re.sub(r"\s+", " ", expected.upper())

    destination_intent = detect_destination_question(user_text)
    if destination_intent:
        if (
            "DESTINATION" not in normalized
            or not re.search(r"\bGROUP\s+BY\s+DESTINATION\b", normalized)
            or re.search(r"\bABS\s*\(", normalized)
        ):
            return False
        if destination_intent == "destination_gain_ranking":
            return (
                re.search(r"\bR4_N\s*>\s*0\b", normalized) is not None
                and re.search(r"\bORDER\s+BY\b[^;]*\bDESC\b", normalized)
                is not None
            )
        return (
            re.search(r"\bR4_N\s*<\s*0\b", normalized) is not None
            and re.search(r"\bORDER\s+BY\b[^;]*\bASC\b", normalized)
            is not None
        )

    monthly_vessel_ranking = detect_monthly_vessel_loss_ranking(user_text)
    if monthly_vessel_ranking is not None:
        expected = build_monthly_vessel_loss_ranking_query(user_text)
        if expected is None:
            return False
        if expected[1] is None:
            expected_query = build_monthly_year_resolution_query(
                monthly_vessel_ranking,
                vessel_only=True,
            )
        else:
            expected_query = expected[1]
        return (
            re.sub(r"\s+", " ", normalized)
            == re.sub(r"\s+", " ", expected_query.upper())
        )

    monthly_months = detect_monthly_supply_loss_question(user_text)
    if monthly_months is not None:
        if get_year(user_text) is None:
            expected_query = build_monthly_year_resolution_query(monthly_months)
        else:
            _, expected_query = build_monthly_supply_loss_query(user_text)
        return (
            re.sub(r"\s+", " ", normalized)
            == re.sub(r"\s+", " ", expected_query.upper())
        )

    text = user_text.lower()
    if any(word in text for word in ("loss", "susut", "supply loss", "gain", "surplus", "r4_n")):
        if "R4_N" not in normalized or re.search(r"\bABS\s*\(", normalized):
            return False

    vessel_name = extract_vessel_name(user_text)
    if vessel_name:
        escaped_name = re.escape(vessel_name.upper())
        if not re.search(
            rf"\bVESSEL_NAME\s*=\s*'{escaped_name}'",
            normalized,
        ):
            return False

    if any(word in text for word in ("kapal", "vessel", "ship", "mt.", "mt ")):
        if not re.search(r"\bALAT_ANGKUT\s*=\s*'KAPAL'", normalized):
            return False

    if (
        any(word in text for word in ("loss", "susut", "supply loss"))
        and not is_loss_vessel_ranking(user_text)
    ):
        if not re.search(r"\bR4_N\s*<\s*0\b", normalized):
            return False

    if (
        any(word in text for word in ("gain", "surplus"))
        and not is_gain_vessel_ranking(user_text)
    ):
        if not re.search(r"\bR4_N\s*>\s*0\b", normalized):
            return False

    if is_gain_vessel_ranking(user_text):
        return (
            re.search(r"\bSELECT\s+TOP\s+\d+\b", normalized) is not None
            and re.search(r"\bALAT_ANGKUT\s*=\s*'KAPAL'", normalized)
            is not None
            and re.search(r"\bGROUP\s+BY\s+VESSEL_NAME\b", normalized)
            is not None
            and re.search(
                r"\bHAVING\s+SUM\s*\(\s*R4_N\s*\)\s*>\s*0\b",
                normalized,
            )
            is not None
            and re.search(r"\bORDER\s+BY\b[^;]*\bDESC\b", normalized)
            is not None
            and re.search(r"\bWHERE\b[^;]*\bR4_N\s*[<>]", normalized)
            is None
        )

    if is_loss_vessel_ranking(user_text):
        order = (
            "DESC"
            if is_smallest_loss_ranking(user_text)
            else "ASC"
        )
        if (
            re.search(r"\bSELECT\s+TOP\s+\d+\b", normalized) is None
            or "VESSEL_NAME" not in normalized
            or not re.search(r"\bSUM\s*\(\s*R4_N\s*\)", normalized)
            or not re.search(
                r"\bHAVING\s+SUM\s*\(\s*R4_N\s*\)\s*<\s*0\b",
                normalized,
            )
            or not re.search(
                rf"\bORDER\s+BY\b[^;]*\b{order}\b",
                normalized,
            )
            or not re.search(
                r"\bALAT_ANGKUT\s*=\s*'KAPAL'",
                normalized,
            )
            or not re.search(
                r"\bGROUP\s+BY\s+VESSEL_NAME\b",
                normalized,
            )
            or re.search(r"\bWHERE\b[^;]*\bR4_N\s*[<>]", normalized)
        ):
            return False

    if is_unfiltered_total_loss_question(user_text):
        if (
            not re.search(r"\bSUM\s*\(\s*R4_N\s*\)", normalized)
            or not re.search(r"\bR4_N\s*<\s*0\b", normalized)
        ):
            return False

    return True


def parse_mcp_table(result_text):
    lines = [line.strip() for line in result_text.splitlines() if line.strip()]
    if len(lines) < 2:
        return [], []

    headers = [value.strip() for value in lines[0].split(" | ")]
    rows = []
    for line in lines[1:]:
        values = [value.strip() for value in line.split(" | ")]
        if len(values) == len(headers):
            rows.append(dict(zip(headers, values)))
    return headers, rows


def query_result_error(result_text):
    lowered = result_text.lower()
    error_markers = (
        "query gagal",
        "gagal menjalankan query",
        "gagal mengambil",
        "ditolak:",
        "query ditolak",
        "error:",
    )
    return any(marker in lowered for marker in error_markers)


def database_error_answer(error_text):
    sql_server_error = re.search(
        r"\[SQL Server\](.*?)\s+\(\d+\)",
        error_text,
        re.IGNORECASE | re.DOTALL,
    )
    if sql_server_error:
        detail = " ".join(sql_server_error.group(1).split())
        return f"Data tidak dapat diambil: SQL Server menolak query ({detail})."
    return "Data tidak dapat diambil karena query database gagal."


def answer_from_database_result(
    intent,
    vessel_name,
    result_text,
    user_input=None,
    resolved_year=None,
):
    if query_result_error(result_text):
        return database_error_answer(result_text)

    if "tidak ada data yang ditemukan" in result_text.lower():
        if intent in {"vessel_lookup", "vessel_loss", "vessel_gain"}:
            month = get_month_number(user_input or "")
            year = get_year(user_input or "")
            if month is not None and year is not None:
                return (
                    f"Tidak ada data untuk kapal {vessel_name} pada "
                    f"{MONTH_NAMES_ID[month]} {year}."
                )
            return f"Data kapal {vessel_name} tidak ditemukan di database."
        return "Tidak ada data yang sesuai di database."

    _, rows = parse_mcp_table(result_text)
    if not rows:
        if intent in {"vessel_lookup", "vessel_loss", "vessel_gain"}:
            return f"Data kapal {vessel_name} tidak ditemukan di database."
        return "Data tidak dapat diambil karena hasil query tidak valid."

    if intent == "vessel_lookup":
        found_name = rows[0].get("VESSEL_NAME")
        if not found_name or found_name.lower() in {"none", "null"}:
            return "Data tidak dapat diambil karena hasil pencarian kapal tidak valid."
        month = get_month_number(user_input or "")
        year = get_year(user_input or "")
        if month is not None and year is not None:
            return (
                f"Kapal {found_name} ditemukan pada "
                f"{MONTH_NAMES_ID[month]} {year}."
            )
        return f"Kapal {found_name} ditemukan dalam database."

    if intent in {"vessel_loss", "vessel_gain"}:
        row = rows[0]
        try:
            row_count = int(row.get("row_count", "0"))
        except ValueError:
            return "Data tidak dapat diambil karena hasil query tidak valid."
        if row_count == 0:
            month = get_month_number(user_input or "")
            year = get_year(user_input or "")
            if month is not None and year is not None:
                return (
                    f"Tidak ada transaksi kapal {vessel_name} pada "
                    f"{MONTH_NAMES_ID[month]} {year}."
                )
            return f"Data kapal {vessel_name} tidak ditemukan di database."

        if intent == "vessel_gain":
            value = row.get("gain_surplus", "0")
            try:
                is_positive = float(value) > 0
            except ValueError:
                return "Data tidak dapat diambil karena hasil query tidak valid."
            if not is_positive:
                return f"Tidak ada Gain/Surplus untuk kapal {vessel_name}; nilainya netral (0)."
            return f"Gain/Surplus kapal {vessel_name}: {value} (R4_N)."

        loss_value = row.get("supply_loss", "0")
        gain_value = row.get("gain_surplus", "0")
        try:
            supply_loss = float(loss_value)
            gain_surplus = float(gain_value)
        except ValueError:
            return "Data tidak dapat diambil karena hasil query tidak valid."
        if supply_loss < 0:
            return f"Supply Loss kapal {vessel_name}: {loss_value} (R4_N)."
        if supply_loss == 0 and gain_surplus > 0:
            return (
                f"Tidak terdapat Supply Loss untuk kapal {vessel_name}; "
                f"kapal memiliki Gain/Surplus sebesar {gain_value} (R4_N)."
            )
        if supply_loss == 0 and gain_surplus == 0:
            return f"Tidak terdapat Supply Loss maupun Gain/Surplus untuk kapal {vessel_name}; nilainya netral (0)."
        return "Data tidak dapat diambil karena hasil query Supply Loss tidak valid."

    if intent == "monthly_comparison":
        if not rows:
            return "Tidak ada data Supply Loss untuk perbandingan bulan yang diminta."
        values_by_period = {}
        for row in rows:
            try:
                year = int(row["data_year"])
                month = int(row["data_month"])
                value = row["total_supply_loss"]
            except (KeyError, ValueError):
                return "Data tidak dapat diambil karena hasil perbandingan bulan tidak valid."
            month_name = MONTH_NAMES_ID.get(month)
            if month_name is None:
                return "Data tidak dapat diambil karena hasil perbandingan bulan tidak valid."
            values_by_period[(month, year)] = value

        expected_periods = extract_month_periods(user_input or "")
        if expected_periods and resolved_year is not None:
            expected_periods = [
                (month, year if year is not None else resolved_year)
                for month, year in expected_periods
            ]
        if not expected_periods or any(year is None for _, year in expected_periods):
            expected_periods = [
                (month, year) for month, year in values_by_period
            ]

        comparisons = []
        for month, year in expected_periods:
            value = values_by_period.get((month, year))
            month_name = MONTH_NAMES_ID[month]
            if value is None:
                comparisons.append(f"{month_name} {year}: tidak ada data")
            else:
                comparisons.append(f"{month_name} {year}: {value} (R4_N)")
        return "Perbandingan Supply Loss:\n" + "\n".join(comparisons)

    if intent == "monthly_vessel_loss_ranking":
        month_periods = extract_month_periods(user_input or "")
        month = month_periods[0][0] if month_periods else None
        year = resolved_year or get_year(user_input or "")
        if month is None or year is None:
            return "Data tidak dapat diambil karena konteks periode ranking tidak valid."

        if len(rows) == 1 and str(rows[0].get("VESSEL_NAME", "")).lower() in {
            "",
            "none",
            "null",
        }:
            try:
                period_row_count = int(rows[0]["period_row_count"])
            except (KeyError, ValueError):
                return "Data tidak dapat diambil karena hasil ranking periode tidak valid."
            period_name = f"{MONTH_NAMES_ID[month]} {year}"
            if period_row_count == 0:
                return f"Tidak ada transaksi kapal pada periode {period_name}."
            return (
                f"Terdapat {period_row_count} transaksi kapal pada periode "
                f"{period_name}, tetapi tidak ada transaksi yang mengalami "
                "Supply Loss."
            )

        ranking = []
        for index, row in enumerate(rows, start=1):
            ranking.append(
                f"{index}. {row.get('VESSEL_NAME', '')}: "
                f"{row.get('total_supply_loss', '')} (R4_N; "
                f"{row.get('jumlah_transaksi_loss', '')} transaksi loss)"
            )
        return (
            f"TOP 5 kapal dengan Supply Loss terbesar pada "
            f"{MONTH_NAMES_ID[month]} {year}:\n"
            + "\n".join(ranking)
        )

    if intent in {"total_loss", "monthly_loss"}:
        value = rows[0].get("total_supply_loss", "None")
        if value.lower() in {"none", "null", ""}:
            return "Tidak ada data Supply Loss untuk periode yang diminta."
        if intent == "monthly_loss":
            months = detect_monthly_supply_loss_question(user_input or "")
            if not months or resolved_year is None:
                return "Data tidak dapat diambil karena konteks tahun bulan tidak tersedia."
            period = MONTH_NAMES_ID[months[0]]
            return (
                f"Total Supply Loss pada {period} {resolved_year}: "
                f"{value} (R4_N)."
            )
        return f"Total Supply Loss (SUM R4_N negatif): {value}."

    if intent == "loss_ranking":
        if not rows:
            return "Tidak ditemukan kapal dengan Supply Loss di database."
        ranking = [
            f"{index}. {row.get('VESSEL_NAME', '')}: "
            f"{row.get('total_supply_loss', '')} (R4_N)"
            for index, row in enumerate(rows, start=1)
        ]
        return "Peringkat kapal berdasarkan Supply Loss terbesar:\n" + "\n".join(ranking)

    if intent == "gain_ranking":
        if not rows:
            return "Tidak ditemukan kapal dengan Gain/Surplus di database."
        ranking = [
            f"{index}. {row.get('VESSEL_NAME', '')}: "
            f"{row.get('total_gain_surplus', '')} (R4_N)"
            for index, row in enumerate(rows, start=1)
        ]
        return "Peringkat kapal berdasarkan Gain/Surplus terbesar:\n" + "\n".join(ranking)

    if intent in {
        "destination_loss_ranking",
        "destination_gain_ranking",
    }:
        row = rows[0]
        destination = row.get("DESTINATION", "")
        if intent == "destination_gain_ranking":
            value = row.get("total_gain_surplus", "0")
            try:
                has_gain = float(value) > 0
            except ValueError:
                return "Data tidak dapat diambil karena hasil query tujuan tidak valid."
            if not has_gain:
                return "Tidak ditemukan Gain/Surplus pada tujuan yang ditanyakan."
            return f"Tujuan dengan Gain/Surplus terbesar: {destination} ({value}, R4_N)."
        value = row.get("total_supply_loss", "0")
        try:
            has_loss = float(value) < 0
        except ValueError:
            return "Data tidak dapat diambil karena hasil query tujuan tidak valid."
        if not has_loss:
            return "Tidak ditemukan Supply Loss pada tujuan yang ditanyakan."
        return f"Tujuan dengan Supply Loss terbesar: {destination} ({value}, R4_N)."

    if intent == "destination_loss_by_destination":
        results = [
            f"{row.get('DESTINATION', '')}: "
            f"{row.get('total_supply_loss', '')} (R4_N)"
            for row in rows
        ]
        answer = "Total Supply Loss per tujuan:\n" + "\n".join(results)
        omitted = re.search(
            r"\.\.\.\s*\((\d+)\s+baris lainnya tidak ditampilkan\)",
            result_text,
            re.IGNORECASE,
        )
        if omitted:
            answer += f"\n({omitted.group(1)} tujuan lainnya tidak ditampilkan MCP.)"
        return answer

    return "Hasil query database:\n" + result_text


def is_supply_loss_scope_question(user_input):
    domain_terms = (
        "supply loss",
        "net supply loss",
        "loss",
        "susut",
        "gain",
        "surplus",
        "r4_n",
        "r4 n",
        "bl_date",
        "tanggal bl",
        "vessel_name",
        "nama kapal",
        "kapal",
        "vessel",
        "ship",
        "pipeline",
        "pipa",
        "alat angkut",
        "destination",
        "tujuan",
        "discharge",
        "nett",
        "volume",
    )
    text = user_input.lower()
    return any(term in text for term in domain_terms)


def contextualize_follow_up(user_input, context):
    if not isinstance(context, dict):
        context = {}

    month = get_month_number(user_input)
    year = get_year(user_input)
    vessel_name = extract_vessel_name(user_input)
    has_ranking = (
        is_loss_vessel_ranking(user_input)
        or is_gain_vessel_ranking(user_input)
    )
    is_lookup = is_vessel_existence_question(user_input)
    has_follow_up_cue = re.search(
        r"\b(?:bagaimana|bagaimana kalau|kalau|untuk|pada|dan|"
        r"yang sama|kapal yang sama|gainnya|lossnya)\b",
        user_input,
        re.IGNORECASE,
    ) is not None
    has_period = month is not None or year is not None
    prior_vessel = context.get("vessel_name")
    has_prior_context = (
        bool(prior_vessel)
        or context.get("analysis_type") == "vessel_ranking"
    )
    is_follow_up = (
        has_prior_context
        and not has_ranking
        and not is_lookup
        and vessel_name is None
        and (has_period or has_follow_up_cue)
    )

    if not has_prior_context and has_period and not is_supply_loss_scope_question(user_input):
        return user_input, (
            "Pertanyaan belum memiliki konteks kapal atau metrik. "
            "Sebutkan nama kapal dan apakah yang ingin dianalisis adalah "
            "Supply Loss atau Gain/Surplus."
        )

    if not is_follow_up:
        return user_input, None

    metric = None
    text = user_input.lower()
    if any(term in text for term in ("gain", "surplus", "positif")):
        metric = "gain"
    elif any(term in text for term in ("loss", "susut", "supply loss")):
        metric = "loss"
    else:
        metric = context.get("metric")

    if metric not in {"loss", "gain"}:
        return user_input, (
            "Apakah yang ingin dianalisis untuk kapal sebelumnya: "
            "Supply Loss atau Gain/Surplus?"
        )

    month = month if month is not None else context.get("month")
    year = year if year is not None else context.get("year")
    if month is not None and year is None:
        month_name = MONTH_NAMES_ID[month]
        return user_input, (
            f"Tahun untuk periode {month_name} belum disebutkan. "
            "Mohon sebutkan tahunnya."
        )

    if context.get("analysis_type") == "vessel_ranking":
        if metric == "loss":
            effective_question = (
                f"TOP 5 kapal dengan Supply Loss terbesar pada "
                f"{MONTH_NAMES_ID[month]} {year}"
            )
        else:
            effective_question = (
                f"TOP 5 kapal dengan Gain terbesar pada "
                f"{MONTH_NAMES_ID[month]} {year}"
            )
        return effective_question, None

    period = ""
    if month is not None and year is not None:
        period = f" pada {MONTH_NAMES_ID[month]} {year}"
    metric_name = "Supply Loss" if metric == "loss" else "Gain/Surplus"
    if not prior_vessel:
        return user_input, (
            "Konteks kapal sebelumnya tidak tersedia. Sebutkan nama kapal "
            "yang ingin dianalisis."
        )
    return (
        f"Berapa {metric_name} untuk kapal bernama {prior_vessel}{period}?",
        None,
    )


def update_conversation_context(context, user_input, intent, vessel_name):
    if not isinstance(context, dict):
        return

    if vessel_name:
        context["vessel_name"] = vessel_name
    elif intent not in {"loss_ranking", "gain_ranking", "monthly_vessel_loss_ranking"}:
        extracted_vessel = extract_vessel_name(user_input)
        if extracted_vessel:
            context["vessel_name"] = extracted_vessel

    month = get_month_number(user_input)
    year = get_year(user_input)
    if month is not None:
        context["month"] = month
    if year is not None:
        context["year"] = year

    if intent in {
        "vessel_loss",
        "loss_ranking",
        "monthly_vessel_loss_ranking",
        "monthly_vessel_ranking_year_resolution",
    }:
        context["metric"] = "loss"
    elif intent in {"vessel_gain", "gain_ranking"}:
        context["metric"] = "gain"

    if intent in {
        "loss_ranking",
        "gain_ranking",
        "monthly_vessel_loss_ranking",
        "monthly_vessel_ranking_year_resolution",
    }:
        context["analysis_type"] = "vessel_ranking"
    elif intent in {"vessel_loss", "vessel_gain"}:
        context["analysis_type"] = "vessel_metric"
    elif intent == "vessel_lookup":
        context.pop("metric", None)
        context["analysis_type"] = "vessel_lookup"
    if intent:
        context["intent"] = intent


# =============================================================================
# FUNGSI UTAMA
# =============================================================================

async def answer_question(
    user_input: str,
    conversation_context=None,
) -> str:
    user_input = user_input.strip()
    if not user_input:
        return "Pertanyaan tidak boleh kosong."

    user_input, clarification = contextualize_follow_up(
        user_input,
        conversation_context,
    )
    if clarification:
        return clarification

    conceptual_answer = answer_conceptual_question(user_input)
    if conceptual_answer is not None:
        return conceptual_answer

    if not is_supply_loss_scope_question(user_input):
        return (
            "Maaf, saya hanya dapat membantu pertanyaan konseptual atau "
            "analisis data terkait Supply Loss, R4_N, kapal, pipeline, "
            "dan periode transaksi."
        )

    targeted_query = build_targeted_supply_loss_query(user_input)
    if targeted_query:
        intent, vessel_name, sql_query = targeted_query
    else:
        intent, vessel_name, sql_query = None, None, None

    if intent == "vessel_lookup_clarification":
        return "Sebutkan nama kapal yang ingin diperiksa keberadaannya."
    if intent == "vessel_period_year_clarification":
        month = get_month_number(user_input)
        month_name = MONTH_NAMES_ID.get(month, "yang diminta")
        return f"Tahun untuk periode {month_name} belum disebutkan. Mohon sebutkan tahunnya."
    if intent == "ranking_period_year_clarification":
        month_name = MONTH_NAMES_ID[get_month_number(user_input)]
        return (
            f"Tahun untuk ranking kapal pada {month_name} belum disebutkan. "
            "Mohon sebutkan tahunnya."
        )

    update_conversation_context(
        conversation_context,
        user_input,
        intent,
        vessel_name,
    )

    requested_months = detect_monthly_supply_loss_question(user_input)
    if intent in {
        "monthly_vessel_ranking_year_resolution",
        "monthly_vessel_ranking_year_clarification",
    }:
        requested_months = detect_monthly_vessel_loss_ranking(user_input)
    if intent in {
        "monthly_year_clarification",
        "monthly_vessel_ranking_year_clarification",
    }:
        return (
            "Tahun untuk setiap bulan tidak dapat dipasangkan dengan pasti. "
            "Sebutkan tahun langsung di samping nama setiap bulan."
        )

    messages = [
        {"role": "system", "content": BUSINESS_CONTEXT},
        {"role": "user", "content": user_input},
    ]

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()

                resolved_year = None
                validation_input = user_input
                if intent in {
                    "monthly_year_resolution",
                    "monthly_vessel_ranking_year_resolution",
                }:
                    if not is_safe_select_query(sql_query) or not validate_query_semantics(
                        user_input,
                        sql_query,
                    ):
                        return "Data tidak dapat diambil karena query penentuan tahun tidak valid."
                    try:
                        year_result = await session.call_tool(
                            "query_database",
                            arguments={"sql_query": sql_query},
                        )
                    except Exception:
                        return "Data tidak dapat diambil karena MCP gagal menentukan tahun data."
                    if getattr(year_result, "isError", False):
                        return "Data tidak dapat diambil karena MCP gagal menentukan tahun data."
                    year_text = "\n".join(
                        item.text
                        for item in year_result.content
                        if hasattr(item, "text")
                    )
                    if not year_text or query_result_error(year_text):
                        return database_error_answer(year_text)
                    if "baris lainnya tidak ditampilkan" in year_text.lower():
                        return (
                            "Tahun untuk bulan yang diminta tidak dapat "
                            "ditentukan dengan pasti. Mohon sebutkan tahun."
                        )

                    _, year_rows = parse_mcp_table(year_text)
                    month_years = {month: set() for month in requested_months}
                    try:
                        for row in year_rows:
                            month_years[int(row["data_month"])].add(
                                int(row["data_year"])
                            )
                    except (KeyError, ValueError):
                        return "Data tidak dapat diambil karena konteks tahun dari database tidak valid."

                    missing_months = [
                        MONTH_NAMES_ID[month]
                        for month, years in month_years.items()
                        if not years
                    ]
                    if missing_months:
                        if intent == "monthly_vessel_ranking_year_resolution":
                            return (
                                "Tidak ada transaksi kapal pada bulan "
                                + ", ".join(missing_months)
                                + " di data."
                            )
                        return (
                            "Tidak ada data tanggal untuk bulan "
                            + ", ".join(missing_months)
                            + "."
                        )

                    common_years = set.intersection(*month_years.values())
                    if not common_years:
                        return (
                            "Bulan-bulan yang diminta tidak memiliki data "
                            "pada tahun yang sama. Sebutkan tahun untuk "
                            "setiap periode yang ingin dibandingkan."
                        )
                    if len(common_years) > 1:
                        options = ", ".join(
                            str(year) for year in sorted(common_years)
                        )
                        return (
                            "Data tersedia pada beberapa tahun ("
                            + options
                            + "). Tahun mana yang ingin digunakan?"
                        )

                    resolved_year = next(iter(common_years))
                    validation_input = f"{user_input} {resolved_year}"
                    if intent == "monthly_vessel_ranking_year_resolution":
                        resolved_query = (
                            build_monthly_vessel_loss_ranking_query(
                                validation_input
                            )
                        )
                    else:
                        resolved_query = build_monthly_supply_loss_query(
                            validation_input
                        )
                    if resolved_query is None:
                        return "Data tidak dapat diambil karena query bulan tidak dapat dibentuk."
                    intent, sql_query = resolved_query

                if sql_query is None:
                    for _ in range(3):
                        try:
                            response = ollama.chat(
                                model=OLLAMA_MODEL,
                                messages=messages,
                                tools=TOOLS,
                            )
                        except Exception as error:
                            error_message = redact_ollama_log_details(
                                str(error)
                            )
                            error_traceback = redact_ollama_log_details(
                                "".join(traceback.format_tb(error.__traceback__))
                            )
                            logger.error(
                                "Pemanggilan Ollama gagal "
                                "[%s; %s]: %s\nTraceback:\n%s",
                                ollama_error_category(error),
                                type(error).__name__,
                                error_message,
                                error_traceback,
                            )
                            return "Data tidak dapat diambil karena chatbot gagal membuat query."

                        assistant_msg = response.get("message", {})
                        tool_calls = assistant_msg.get("tool_calls") or []
                        if tool_calls:
                            if len(tool_calls) != 1:
                                return "Data tidak dapat diambil karena model menghasilkan query yang tidak valid."
                            function = tool_calls[0].get("function", {})
                            if function.get("name") != "query_database":
                                return "Data tidak dapat diambil karena model memilih tool yang tidak valid."
                            arguments = function.get("arguments", {})
                            if isinstance(arguments, str):
                                try:
                                    arguments = json.loads(arguments)
                                except json.JSONDecodeError:
                                    return "Data tidak dapat diambil karena parameter query tidak valid."
                            if not isinstance(arguments, dict):
                                return "Data tidak dapat diambil karena parameter query tidak valid."
                            sql_query = arguments.get("sql_query")
                            break

                        content = assistant_msg.get("content", "")
                        sql_query = extract_sql_from_content(content)
                        if sql_query:
                            break
                        messages.append(assistant_msg)
                        messages.append({
                            "role": "user",
                            "content": (
                                "Buat satu query SELECT yang sesuai dan panggil "
                                "tool query_database. Jangan menjawab pertanyaan."
                            ),
                        })

                if not sql_query:
                    return "Data tidak dapat diambil karena query database tidak berhasil dibuat."

                sql_query = apply_business_rules(validation_input, sql_query)
                if (
                    not is_safe_select_query(sql_query)
                    or not validate_query_semantics(validation_input, sql_query)
                ):
                    return "Data tidak dapat diambil karena query tidak sesuai dengan pertanyaan."

                try:
                    tool_result = await session.call_tool(
                        "query_database",
                        arguments={"sql_query": sql_query},
                    )
                except Exception:
                    return "Data tidak dapat diambil karena koneksi atau eksekusi query database gagal."

                if getattr(tool_result, "isError", False):
                    return "Data tidak dapat diambil karena MCP gagal menjalankan query."

                result_text = "\n".join(
                    item.text
                    for item in tool_result.content
                    if hasattr(item, "text")
                )
                if not result_text:
                    return "Data tidak dapat diambil karena MCP tidak mengembalikan hasil query."

                return answer_from_database_result(
                    intent,
                    vessel_name,
                    result_text,
                    user_input=user_input,
                    resolved_year=resolved_year or get_year(user_input),
                )
    except Exception:
        return "Data tidak dapat diambil karena koneksi MCP atau SQL Server gagal."


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
