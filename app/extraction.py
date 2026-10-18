"""Rule-based fact extraction from conversation messages.

Deterministic on purpose: the demo must work with no LLM API key.
Swap `extract_facts` for an LLM call later - its output contract
(title, content, fact_type, entities) is all the graph layer sees.
"""
import re

STOP = {"I", "The", "And", "But", "Our", "We", "My", "This", "That", "Session"}


def extract_facts(text: str):
    facts = []

    m = re.search(r"allergic to ([a-zA-Z ]+?)(?:\.|,| and |$)", text, re.I)
    if m:
        item = m.group(1).strip()
        facts.append({
            "title": f"Allergy: {item}",
            "content": f"User is allergic to {item}. Never include it in plans, meals or recommendations.",
            "fact_type": "Allergy",
            "entities": [item.title(), "Health"],
            "confidence": 0.99,
        })

    for m in re.finditer(r"(?:i prefer|prefer|i like) ([^.,;]+)", text, re.I):
        pref = m.group(1).strip()
        facts.append({
            "title": f"Preference: {pref[:60]}",
            "content": f"User prefers {pref}.",
            "fact_type": "Preference",
            "entities": [w.strip(" ").title() for w in re.split(r"\s+", pref) if len(w) > 4][:2],
            "confidence": 0.9,
        })

    m = re.search(r"([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?) (?:launches|ships|is due|deadline is) (?:on )?([^.,;]+)", text)
    if m:
        facts.append({
            "title": f"{m.group(1)} deadline: {m.group(2).strip()}",
            "content": f"{m.group(1)} launches / is due {m.group(2).strip()}.",
            "fact_type": "Deadline",
            "entities": [m.group(1)],
            "confidence": 0.95,
        })

    m = re.search(r"([A-Z][a-z]+) owns ([a-zA-Z ]+?)(?:\.|,|$)", text)
    if m:
        facts.append({
            "title": f"{m.group(1)} owns {m.group(2).strip()}",
            "content": f"{m.group(1)} is the owner of {m.group(2).strip()}. Route related work and questions to them.",
            "fact_type": "Ownership",
            "entities": [m.group(1), m.group(2).strip().title()],
            "confidence": 0.92,
        })

    m = re.search(r"(?:standup|meeting) (?:is )?(?:at )?([0-9]{1,2}:[0-9]{2}\s?(?:am|pm)?)", text, re.I)
    if m:
        facts.append({
            "title": f"Recurring meeting at {m.group(1)}",
            "content": f"Team standup / meeting happens at {m.group(1)}.",
            "fact_type": "Procedure",
            "entities": ["Standup"],
            "confidence": 0.85,
        })
    return facts


def guess_entities(text: str):
    """Capitalised phrases + quoted terms - used to boost recall ranking."""
    found = re.findall(r"\b([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)\b", text or "")
    return sorted({f for f in found if f not in STOP})
