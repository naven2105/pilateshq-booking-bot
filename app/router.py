# app/router.py (inside register_routes)
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json() or {}
    logging.debug(f"[WEBHOOK DATA keys] {list(data.keys())}")

    try:
        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = (change.get("value") or {})
                # 1) status callbacks
                if value.get("statuses"):
                    st = value["statuses"][0]
                    logging.info(f"[STATUS] id={st.get('id')} status={st.get('status')} to={st.get('recipient_id')}")
                    continue
                # 2) messages
                for message in value.get("messages", []):
                    sender = message.get("from")
                    if not sender:
                        logging.warning("[WARN] message without sender")
                        continue

                    if "interactive" in message:
                        rep = message["interactive"]
                        reply_id = (rep.get("button_reply", {}) or {}).get("id") or (rep.get("list_reply", {}) or {}).get("id")
                        logging.info(f"[USER CHOICE] {reply_id}")
                        if reply_id and reply_id.upper().startswith("ADMIN"):
                            handle_admin_action(sender, reply_id)
                        else:
                            handle_onboarding(sender, reply_id or "ROOT_MENU")
                        continue

                    if "text" in message:
                        msg_text = (message["text"].get("body") or "").strip()
                        up = msg_text.upper()
                        if up in ("HI","HELLO","START","MENU","MAIN_MENU"):
                            handle_onboarding(sender, "ROOT_MENU")
                        else:
                            capture_onboarding_free_text(sender, msg_text)
                        continue

    except Exception as e:
        logging.exception(f"[ERROR webhook]: {e}")

    return "ok", 200  # <-- inside the function
