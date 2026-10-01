"""Draft the prose with AI when available; always insert evidence ourselves."""

import json
import os
import re

from openai import OpenAI, OpenAIError

from calculations import UPGRADES


def money_range(values):
    low, high = sorted(values)
    return f"${low:,.0f}–${high:,.0f}"


def change_description(values, unit="dollars"):
    low, high = sorted(values)
    if unit == "dollars":
        magnitude = money_range([abs(low), abs(high)])
    else:
        magnitude = f"{min(abs(low), abs(high)):,.0f}–{max(abs(low), abs(high)):,.0f} kg CO₂e"
    if high < 0:
        return f"an estimated increase of {magnitude} per year"
    if low >= 0:
        return f"an estimated reduction of {magnitude} per year"
    return f"a change ranging from an increase of {abs(low):,.0f} to a reduction of {high:,.0f} {unit} per year"


def request_lines(assessment):
    requests = []
    for category in assessment["selected_upgrades"]:
        if category == "insulation":
            requests.append("a professional assessment of the ceiling insulation and suitable improvements")
        else:
            requests.append(UPGRADES[category]["request"])
    return requests


def draft_prose(requests):
    """AI writes only the opening and closing; all facts stay in fixed text."""
    opening = (
        "I am writing to ask whether we could discuss some practical improvements "
        "to the comfort and energy performance of the property. I would appreciate "
        "your consideration of the options listed below."
    )
    closing = (
        "Would you be willing to discuss these options and arrange an appropriate "
        "assessment or quote? I understand that suitability, access and costs need "
        "to be confirmed before any work is agreed. Thank you for considering this request."
    )
    if not os.environ.get("OPENAI_API_KEY"):
        return opening, closing, "template", "A personalised template is ready. AI drafting can be enabled with a server API key."

    try:
        client = OpenAI(timeout=25, max_retries=0)
        response = client.responses.create(
            model=os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
            store=False,
            max_output_tokens=450,
            instructions=(
                "Write two short Australian-English paragraphs for a polite renter-to-landlord request. "
                "Return a JSON object with exactly opening and closing text fields. "
                "The opening introduces a discussion about comfort and energy performance. "
                "The closing asks for a discussion and professional quote or assessment. "
                "Use only the provided request topics. Do not add numbers, prices, sources, rebates, "
                "laws, deadlines, health diagnoses, tenancy history, promises of savings, property "
                "values, or obligations. Do not include names, addresses, greetings or signatures. "
                "The verified evidence and exact requests will be inserted separately."
            ),
            input=json.dumps({"request_topics": requests}),
            text={"format": {"type": "json_object"}},
        )
        prose = json.loads(response.output_text)
        if not isinstance(prose, dict):
            raise ValueError("Unexpected drafting response")
        for key in ["opening", "closing"]:
            paragraph = prose.get(key)
            if not isinstance(paragraph, str) or not 20 <= len(paragraph) <= 1200:
                raise ValueError("Unexpected paragraph")
            # Reject unsupported quantities and links; evidence is added below.
            if any(character.isdigit() for character in paragraph) or "$" in paragraph or "http" in paragraph.lower():
                raise ValueError("Unexpected claim in drafting response")
            if re.search(r"\b(legal|obligation|rebate|guarantee|deadline|diagnosis|value|must)\b", paragraph, re.IGNORECASE):
                raise ValueError("Unsupported claim in drafting response")
        return prose["opening"], prose["closing"], "ai", "AI-assisted wording with calculated figures inserted separately. Please review before use."
    except (OpenAIError, ValueError, TypeError):
        # Do not return provider errors: they can contain request or account data.
        return opening, closing, "template", "AI drafting is unavailable. Your personalised template is ready and can be edited."


def create_letter(assessment):
    requests = request_lines(assessment)
    if not requests:
        raise ValueError("Choose at least one improvement before preparing a request.")
    opening, closing, mode, message = draft_prose(requests)
    lines = [
        "Dear [Landlord or property manager name],", "",
        "Re: proposed improvements at [Rental property address]", "", opening, "",
        "I would like to discuss:",
    ]
    for request in requests:
        lines.append(f"• {request[0].upper() + request[1:]}.")

    # Only evidence for selected, supported appliances belongs in the request.
    selected_components = []
    for component in assessment["components"]:
        if component["selected"] and component["supported"]:
            selected_components.append(component)
    if selected_components:
        lines.extend(["", "ILLUSTRATIVE RUNNING-COST COMPARISON", ""])
        for component in selected_components:
            lines.append(
                f"{component['title']}: {component['current_label']} to {component['target_label']}. "
                f"Current running costs {money_range(component['current']['cost'])}/year; "
                f"proposed {money_range(component['proposed']['cost'])}/year. "
                f"This is {change_description(component['savings'])}."
            )
        lines.append("Any energy-bill savings accrue to the bill-paying renter; these figures are not a financial return to the property owner.")
        totals = assessment["totals"]
        lines.append(f"For the selected appliance changes together, operational emissions show {change_description(totals['emissions_savings'], 'kg CO₂e')}.")
        lines.extend(["", "INSTALLATION AND POSSIBLE ASSISTANCE", ""])
        for component in selected_components:
            lines.append(f"{component['title']}: {component['installation']}")
            lines.append(f"Check Victorian Energy Upgrades eligibility with an accredited provider: {component['rebate_url']}")
        lines.append("No unconfirmed rebate has been subtracted. The final scope and price require an installer quote.")

    if assessment["gas_supply"]["selected"]:
        saving = assessment["gas_supply"]["annual_saving"]
        lines.extend(["", f"If every gas use is replaced and the gas connection/account is ended, the scenario also avoids about ${saving:,.0f}/year in gas supply charges. Disconnection costs are separate and need to be confirmed."])
    if assessment["insulation"]["selected"]:
        lines.extend(["", "INSULATION", assessment["insulation"]["guidance"], "No dollar saving, R-value or health-risk score has been assigned to insulation."])

    lines.extend(["", "BASIS AND LIMITATIONS", "These are illustrative scenarios from What Does My Home Need?, an independent competition prototype. They are not an energy audit, measured bill forecast or quote."])
    for assumption in assessment["assumptions"]:
        lines.append(f"• {assumption}")
    for note in assessment["notes"]:
        lines.append(f"• {note}")
    lines.append("Installation permissions, building suitability and any applicable rental standards should be checked for this specific property. No legal obligation or deadline is asserted by this letter.")

    source_ids = {"rental_standards"}
    if selected_components:
        source_ids.update(["emissions", "bills"])
    if assessment["insulation"]["selected"]:
        source_ids.add("insulation")
    for component in selected_components:
        source_ids.update(component["source_ids"])
    lines.extend(["", "SOURCES"])
    for source in assessment["sources"]:
        if source["id"] in source_ids:
            lines.append(f"{source['title']} ({source['reference']}): {source['url']}")
    lines.extend(["", closing, "", "Kind regards,", "[Your name]"])
    return {"letter": "\n".join(lines), "mode": mode, "message": message, "selected_upgrades": assessment["selected_upgrades"]}
