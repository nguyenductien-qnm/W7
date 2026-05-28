from core import DEMO_USER_ID, find_profile_by_email, parse_json_body, response


def handle_login(event):
    payload = parse_json_body(event)
    email = str(payload.get("email", "")).strip().lower()
    profile = find_profile_by_email(email)
    if not profile:
        return response(401, {"message": "Invalid email"})

    user_id = profile.get("user_id") or str(profile.get("PK", "")).replace("USER#", "")
    if not user_id:
        user_id = DEMO_USER_ID

    return response(
        200,
        {
            "user_id": user_id,
            "token": "demo-token",
            "message": "Login success",
        },
    )


def lambda_handler(event, _context):
    try:
        return handle_login(event)
    except Exception as exc:
        return response(500, {"message": "Internal server error", "error": str(exc)})
