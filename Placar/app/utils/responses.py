from flask import jsonify


def success(data=None, status=200):
    return jsonify({"ok": True, "data": data}), status


def error(message, status=400):
    return jsonify({"ok": False, "error": message}), status
