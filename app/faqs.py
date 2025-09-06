# app/faqs.py
FAQ_ITEMS = [
    ("Address & parking", "We’re at 71 Grant Ave, Norwood, Johannesburg. Safe off-street parking is available."),
    ("Group sizes", "Groups are capped at 6 to keep coaching personal."),
    ("Equipment", "We use Reformers, Wall Units, Wunda chairs, small props, and mats."),
    ("Pricing", "Groups from R180"),
    ("Schedule", "Weekdays 06:00–18:00; Sat 08:00–10:00."),
    ("How to start", "Most start with a 1:1 assessment or jump into a beginner-friendly group."),
]
FAQ_MENU_TEXT = "Here are a few common questions. Reply with a number:\n" + "\n".join(
    [f"{i+1}. {title}" for i, (title, _) in enumerate(FAQ_ITEMS)]
)
