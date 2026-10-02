"""Draft the prose with AI when available; always insert evidence ourselves."""

import json
import os
import re
from urllib.parse import urlsplit

from openai import OpenAI, OpenAIError

from calculations import UPGRADES


# These providers expose endpoints understood by the existing OpenAI SDK.
# Qwen's preset is the Alibaba Cloud Singapore endpoint.
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "deepseek": "https://api.deepseek.com/v1",
    "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
    "custom": "",
}


def get_ai_settings():
    """Read one provider's settings without borrowing another provider's key."""
    provider = os.environ.get("AI_PROVIDER", "openai").strip().lower()
    if provider not in PROVIDER_URLS:
        raise ValueError("Set AI_PROVIDER to openai, gemini, deepseek, qwen or custom.")

    # Generic settings take priority; existing OPENAI_* settings still work.
    prefix = provider.upper()
    api_key = os.environ.get("AI_API_KEY", "").strip()
    if not api_key:
        api_key = os.environ.get(f"{prefix}_API_KEY", "").strip()
    model = os.environ.get("AI_MODEL", "").strip()
    if not model:
        model = os.environ.get(f"{prefix}_MODEL", "").strip()
    if not model and provider == "openai":
        model = "gpt-4o-mini"

    base_url = os.environ.get("AI_BASE_URL", "").strip() or PROVIDER_URLS[provider]
    try:
        endpoint = urlsplit(base_url)
    except ValueError:
        raise ValueError("AI_BASE_URL must be a valid API URL.") from None
    local_http = endpoint.scheme == "http" and endpoint.hostname in ("localhost", "127.0.0.1", "::1")
    if not endpoint.hostname or (endpoint.scheme != "https" and not local_http):
        raise ValueError("Set AI_BASE_URL to an HTTPS API URL (HTTP is allowed for localhost).")
    if endpoint.username or endpoint.password or endpoint.query or endpoint.fragment:
        raise ValueError("AI_BASE_URL must not contain credentials, query parameters or a fragment.")

    json_mode = os.environ.get("AI_JSON_MODE", "true").strip().lower()
    if json_mode not in ("true", "false"):
        raise ValueError("Set AI_JSON_MODE to true or false.")
    if api_key and not model:
        raise ValueError("Set AI_MODEL to the exact model ID from your provider.")
    return {
        "provider": provider, "api_key": api_key, "model": model,
        "base_url": base_url, "json_mode": json_mode == "true",
    }


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
    try:
        settings = get_ai_settings()
    except ValueError as error:
        return opening, closing, "template", f"{error} Your personalised template is ready."
    if not settings["api_key"]:
        return opening, closing, "template", "A personalised template is ready. AI drafting can be enabled with a server API key."

    try:
        client = OpenAI(
            api_key=settings["api_key"], base_url=settings["base_url"],
            timeout=30, max_retries=0,
        )
        instructions = (
            "Write two short Australian-English paragraphs for a polite renter-to-landlord request. "
            "Return a JSON object with exactly opening and closing text fields. "
            "The opening introduces a discussion about comfort and energy performance. "
            "The closing asks for a discussion and professional quote or assessment. "
            "Use only the provided request topics. Do not add numbers, prices, sources, rebates, "
            "laws, deadlines, health diagnoses, tenancy history, promises of savings, property "
            "values, or obligations. Do not include names, addresses, greetings or signatures. "
            "The verified evidence and exact requests will be inserted separately."
        )
        request_topics = json.dumps({"request_topics": requests})
        if settings["provider"] == "openai":
            # Preserve the Responses API and disabled response storage for OpenAI.
            response = client.responses.create(
                model=settings["model"], store=False, max_output_tokens=2048,
                instructions=instructions, input=request_topics,
                text={"format": {"type": "json_object" if settings["json_mode"] else "text"}},
            )
            response_text = response.output_text
        else:
            # Gemini, DeepSeek, Qwen and custom endpoints use Chat Completions.
            options = {}
            if settings["json_mode"]:
                options["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(
                model=settings["model"], max_tokens=2048,
                messages=[
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": request_topics},
                ],
                **options,
            )
            response_text = response.choices[0].message.content

        # Some compatible providers wrap JSON in a Markdown code block.
        if not isinstance(response_text, str):
            raise ValueError("Missing drafting text")
        response_text = response_text.strip()
        if response_text.startswith("```") and response_text.endswith("```"):
            response_text = "\n".join(response_text.splitlines()[1:-1])
        prose = json.loads(response_text)
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
        return prose["opening"], prose["closing"], "ai", f"AI-assisted wording via {settings['provider']}, with calculated figures inserted separately. Please review before use."
    except (OpenAIError, ValueError, TypeError, IndexError, AttributeError):
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
