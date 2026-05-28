from app import handle_quiz, response


def lambda_handler(event, _context):
    try:
        return handle_quiz(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
