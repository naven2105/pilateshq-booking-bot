from flask import Flask, request
from twilio.twiml.messaging_response import MessagingResponse
import os

app = Flask(__name__)

# Session store (basic, in-memory)
sessions = {}

@app.route("/whatsapp", methods=["POST"])
def whatsapp():
    incoming_msg = request.values.get("Body", "").strip().lower()
    from_number = request.values.get("From")

    resp = MessagingResponse()
    msg = resp.message()

    session = sessions.get(from_number, {"step": 0})

    if incoming_msg in ["hi", "hello", "book", "hey"]:
        session = {"step": 1}
        msg.body("Hi! Welcome to *PilatesHQ* with Nadine. 🧘‍♀️\n\nWhich class would you like to book?\n1. Reformer Single (R300)\n2. Reformer Duo (R250)\n3. Reformer Trio (R200)")

    elif session["step"] == 1:
        if incoming_msg.startswith("1"):
            session["class"] = "Reformer Single"
        elif incoming_msg.startswith("2"):
            session["class"] = "Reformer Duo"
        elif incoming_msg.startswith("3"):
            session["class"] = "Reformer Trio"
        else:
            msg.body("Please enter 1, 2, or 3 to choose your class.")
            return str(resp)

        session["step"] = 2
        msg.body(f"Great! You selected *{session['class']}*.\n\nPlease enter your preferred date and time (e.g. 15 Aug, 10am):")

    elif session["step"] == 2:
        session["datetime"] = incoming_msg
        session["step"] = 3
        msg.body("Got it. Please enter your *full name*:")

    elif session["step"] == 3:
        session["name"] = incoming_msg
        session["step"] = 4
        msg.body("Thanks! Lastly, please provide your *contact number*:")

    elif session["step"] == 4:
        session["contact"] = incoming_msg
        msg.body(f"✅ Booking Confirmed!\n\nClass: {session['class']}\nDate/Time: {session['datetime']}\nName: {session['name']}\nContact: {session['contact']}\n\nSee you soon at *PilatesHQ*! 🙌")
        # Store booking (in real app, store to DB/Google Sheets)
        print("New Booking:", session)
        session = {"step": 0}  # Reset

    else:
        msg.body("Hi! To start your booking, reply with *Hi* or *Book*.")

    sessions[from_number] = session
    return str(resp)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, host="0.0.0.0", port=port)
