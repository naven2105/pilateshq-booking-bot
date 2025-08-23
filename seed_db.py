from sqlalchemy import select, func
from models import Client

def _next_household_id(session):
    # Simple allocator: max(household_id)+1 (skips None)
    max_id = session.scalar(select(func.max(Client.household_id)))
    return (max_id or 0) + 1

def upsert_clients(session):
    """
    Seed broader population with plans + households for couples.
    plan: "1x", "2x", "3x"
    """
    # Individuals (name, wa, plan, notes)
    individuals = [
        ("Aisha K",   "27840000021", "1x", "prefers non-peak"),
        ("Bongani D", "27840000022", "1x", ""),
        ("Carla P",   "27840000023", "1x", ""),
        ("Dumisani R","27840000024", "1x", ""),
        ("Emma T",    "27840000025", "2x", "peak preferred"),
        ("Farai N",   "27840000026", "2x", "back care"),
        ("Grace L",   "27840000027", "2x", ""),
        ("Hassan M",  "27840000028", "2x", ""),
        ("Ines C",    "27840000029", "2x", "group regular"),
        ("Jabu S",    "27840000030", "2x", "group regular"),
        ("Kelly O",   "27840000031", "2x", ""),
        ("Lerato N",  "27840000032", "2x", ""),
        ("Mandla Q",  "27840000033", "3x", "heavy group"),
        ("Nadia F",   "27840000034", "3x", "heavy group"),
        ("Oscar V",   "27840000035", "3x", "heavy group"),
        ("Qinisela H","27840000042", "2x", "group + occasional single"),
        ("Renee P",   "27840000043", "2x", "group + occasional single"),
        ("Sipho G",   "27840000044", "2x", "group + occasional single"),
        ("Thandi Z",  "27840000045", "1x", "non-peak"),
        ("Umari J",   "27840000046", "1x", "non-peak"),
        ("Victor B",  "27840000047", "1x", "non-peak"),
        ("Winnie A",  "27840000048", "2x", "peak priority"),
        ("Xolani C",  "27840000049", "2x", "peak priority"),
        ("Yara M",    "27840000050", "2x", "peak priority"),
        ("Abel R",    "27840000051", "1x", ""),
        ("Bianca U",  "27840000052", "1x", ""),
        ("Chen Z",    "27840000053", "1x", ""),
        ("Diane H",   "27840000054", "1x", ""),
        ("Evan J",    "27840000055", "1x", ""),
        ("Felix W",   "27840000056", "1x", ""),
    ]

    # Couples (two separate client rows with shared household_id)
    couples = [
        (("Priya S", "27840000038", "2x", "duo + Priya occasional single"),
         ("Raj S",   "27840000039", "2x", "duo + Raj occasional single")),
        (("Zoe K",   "27840000040", "2x", "duo + Zoe occasional single"),
         ("Liam K",  "27840000041", "2x", "duo; Liam prefers non-peak")),
    ]

    # Upsert individuals
    existing = {c.wa_number: c for c in session.scalars(select(Client)).all()}
    created = 0
    for name, wa, plan, notes in individuals:
        if wa not in existing:
            session.add(Client(wa_number=wa, name=name, plan=plan, notes=notes))
            created += 1

    # Upsert couples with household IDs
    for (n1, wa1, plan1, notes1), (n2, wa2, plan2, notes2) in couples:
        hid = _next_household_id(session)
        if wa1 not in existing:
            session.add(Client(wa_number=wa1, name=n1, plan=plan1, notes=notes1, household_id=hid))
            created += 1
        if wa2 not in existing:
            session.add(Client(wa_number=wa2, name=n2, plan=plan2, notes=notes2, household_id=hid))
            created += 1

    session.commit()
    return created
