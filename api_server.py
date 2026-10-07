"""
================================================================================
API SERVER - MEMBUNGKUS CHATBOT MENJADI WEB API
================================================================================

Endpoint:

GET:
    /health

POST:
    /chat

Contoh request:

{
    "question": "Kapal penyumbang loss terbesar pada June 2025?"
}

Contoh response:

{
    "answer": "..."
}
================================================================================
"""

import asyncio

from flask import Flask, request, jsonify
from flask_cors import CORS

from chatbot import answer_question


# =============================================================================
# FLASK APP
# =============================================================================

app = Flask(
    __name__
)


CORS(
    app
)


# =============================================================================
# POST /chat
# =============================================================================

@app.route(
    "/chat",
    methods=["POST"]
)
def chat_endpoint():

    # =========================================================================
    # AMBIL JSON
    # =========================================================================

    try:

        data = request.get_json(
            force=True
        )

    except Exception:

        return jsonify({
            "answer": (
                "Format request JSON tidak valid."
            )
        }), 400


    # =========================================================================
    # VALIDASI OBJECT
    # =========================================================================

    if not isinstance(
        data,
        dict
    ):

        return jsonify({
            "answer": (
                "Request harus berupa JSON object."
            )
        }), 400


    # =========================================================================
    # AMBIL QUESTION
    # =========================================================================

    question = data.get(
        "question",
        ""
    )


    # =========================================================================
    # VALIDASI STRING
    # =========================================================================

    if not isinstance(
        question,
        str
    ):

        return jsonify({
            "answer": (
                "Field question harus berupa string."
            )
        }), 400


    question = question.strip()


    # =========================================================================
    # QUESTION KOSONG
    # =========================================================================

    if not question:

        return jsonify({
            "answer": (
                "Pertanyaan tidak boleh kosong."
            )
        }), 400


    # =========================================================================
    # JALANKAN CHATBOT
    # =========================================================================

    try:

        answer = asyncio.run(
            answer_question(
                question
            )
        )


        return jsonify({
            "answer": answer
        })


    except Exception as e:

        print(
            "ERROR:",
            str(e)
        )


        return jsonify({
            "answer": (
                "Terjadi error di server: "
                + str(e)
            )
        }), 500


# =============================================================================
# GET /health
# =============================================================================

@app.route(
    "/health",
    methods=["GET"]
)
def health():

    return jsonify({
        "status": "ok"
    })


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":

    print("=" * 70)
    print("SUPPLY LOSS CHATBOT API")
    print("=" * 70)

    print(
        "API server : http://localhost:5000"
    )

    print(
        "Chat       : POST http://localhost:5000/chat"
    )

    print(
        "Health     : GET http://localhost:5000/health"
    )

    print("=" * 70)


    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )