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
import threading
import uuid

from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.exceptions import BadRequest

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

_conversation_contexts = {}
_session_locks = {}
_session_registry_lock = threading.Lock()


def get_session_lock(session_id):
    with _session_registry_lock:
        return _session_locks.setdefault(session_id, threading.RLock())


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

    except BadRequest:

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
                "Question harus berupa string."
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

    session_id = data.get("session_id")
    if session_id is None:
        session_id = str(uuid.uuid4())
    elif (
        not isinstance(session_id, str)
        or not session_id.strip()
        or len(session_id) > 128
    ):
        return jsonify({
            "answer": "Field session_id harus berupa string yang valid."
        }), 400
    else:
        session_id = session_id.strip()

    # =========================================================================
    # JALANKAN CHATBOT
    # =========================================================================

    try:

        with get_session_lock(session_id):
            context = _conversation_contexts.setdefault(session_id, {})
            answer = asyncio.run(
                answer_question(
                    question,
                    context,
                )
            )


        return jsonify({
            "answer": answer,
            "session_id": session_id,
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
# POST /reset
# =============================================================================

@app.route(
    "/reset",
    methods=["POST"]
)
def reset_conversation():
    try:
        data = request.get_json(force=True)
    except BadRequest:
        return jsonify({
            "answer": "Format request JSON tidak valid."
        }), 400

    if not isinstance(data, dict):
        return jsonify({
            "answer": "Request harus berupa JSON object."
        }), 400

    session_id = data.get("session_id")
    if (
        not isinstance(session_id, str)
        or not session_id.strip()
        or len(session_id) > 128
    ):
        return jsonify({
            "answer": "Field session_id harus berupa string yang valid."
        }), 400

    session_id = session_id.strip()
    with get_session_lock(session_id):
        _conversation_contexts.pop(session_id, None)

    return jsonify({
        "status": "ok",
        "session_id": session_id,
    })


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