"""Transparent appliance comparisons. No AI is used to calculate any number."""

import json
import math
from pathlib import Path

REFERENCE_PATH = Path(__file__).parent / "data" / "reference.json"
REFERENCE = json.loads(REFERENCE_PATH.read_text(encoding="utf-8"))

CHOICES = {
    "dwelling": ["house", "apartment"],
    "heating": ["unknown", "gas", "electric_resistance", "heat_pump", "none", "other"],
    "cooling": ["none", "fan", "air_conditioner", "evaporative", "unknown"],
    "cooking": ["unknown", "gas", "electric_resistance", "induction", "none"],
    "hot_water": ["unknown", "gas", "electric_resistance", "heat_pump", "shared", "solar"],
    "insulation": ["unknown", "none", "poor", "present", "not_applicable"],
    "comfort": ["both", "cold", "hot", "comfortable"],
    "other_gas": ["unknown", "yes", "no"],
    "solar": ["no", "yes", "unknown"],
}

APPLIANCE_LABELS = {
    "gas": "Gas",
    "electric_resistance": "Conventional electric",
    "heat_pump": "Heat pump / reverse cycle",
    "induction": "Induction",
    "none": "No appliance",
    "unknown": "Not identified",
    "other": "Another heating system",
    "shared": "Shared hot water",
    "solar": "Solar / boosted hot water",
}

UPGRADES = {
    "heating": {
        "title": "Heating & cooling",
        "target": "heat_pump",
        "target_label": "Reverse-cycle air conditioning",
        "request": "a quote for appropriately sized reverse-cycle heating and cooling",
        "benefit": "Efficient heating, with the option of cooling in summer. Cooling electricity is additional and is not included in this heating estimate.",
        "installation": "Quote required. Room coverage, electrical capacity and installation access determine the cost.",
        "rebate_url": "https://www.energy.vic.gov.au/victorian-energy-upgrades/products/heating-and-cooling-discounts",
        "source_ids": ["heating", "veu"],
    },
    "cooking": {
        "title": "Cooking",
        "target": "induction",
        "target_label": "Induction cooktop",
        "request": "a quote for an induction cooktop and any required electrical work",
        "benefit": "Responsive electric cooking. Check cookware compatibility, the electrical circuit and permission for installation.",
        "installation": "Cooktop: about $600 to over $6,000; dedicated circuit: $600–$1,200; gas capping: $250–$500 where needed. Other work may cost extra.",
        "rebate_url": "https://www.energy.vic.gov.au/victorian-energy-upgrades/products/induction-cooktop-discounts",
        "source_ids": ["cooking", "cooking_cost", "veu"],
    },
    "hot_water": {
        "title": "Hot water",
        "target": "heat_pump",
        "target_label": "Heat-pump hot water",
        "request": "a quote for a suitably sized heat-pump hot-water system",
        "benefit": "Uses electricity to move heat into water. An installer should confirm space, noise, climate suitability and household demand.",
        "installation": "Indicative installed heat-pump cost: $2,500–$7,500 before incentives. A property-specific quote is needed.",
        "rebate_url": "https://www.energy.vic.gov.au/victorian-energy-upgrades/products/hot-water-system-discounts",
        "source_ids": ["hot_water", "veu"],
    },
}


def validate_payload(payload):
    """Return cleaned answers and useful field errors for the browser."""
    if not isinstance(payload, dict) or not isinstance(payload.get("home"), dict):
        return None, {"form": "Please provide your home details."}

    answers = payload["home"]
    home = {}
    errors = {}
    postcode = str(answers.get("postcode", "")).strip()
    # This is a postcode-format screen, not an address or climate lookup.
    if len(postcode) != 4 or not postcode.isascii() or not postcode.isdigit():
        errors["postcode"] = "Enter a four-digit Victorian postcode."
    elif not 3000 <= int(postcode) <= 3999:
        errors["postcode"] = "This pilot supports Victorian residential postcodes in the 3000–3999 range."
    home["postcode"] = postcode

    for field, choices in CHOICES.items():
        value = answers.get(field, choices[0])
        if value not in choices:
            errors[field] = "Choose one of the available options."
        else:
            home[field] = value

    try:
        occupants = float(answers.get("occupants", 2))
        if isinstance(answers.get("occupants"), bool) or not occupants.is_integer() or not 1 <= occupants <= 8:
            raise ValueError
        home["occupants"] = int(occupants)
    except (ValueError, TypeError, OverflowError):
        errors["occupants"] = "Choose a household size between 1 and 8 people."

    heated_area = str(answers.get("heated_area", "unknown"))
    if heated_area not in ["30", "60", "100", "150", "unknown"]:
        errors["heated_area"] = "Choose the approximate area you usually heat."
    home["heated_area"] = None if heated_area == "unknown" else heated_area

    price_limits = {
        "electricity_price": (1, 200),
        "gas_price": (0.1, 50),
        "gas_daily_charge": (0, 1000),
    }
    for field, (minimum, maximum) in price_limits.items():
        value = answers.get(field, REFERENCE["defaults"][field])
        try:
            if isinstance(value, bool):
                raise ValueError
            value = float(value)
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError
            home[field] = value
        except (ValueError, TypeError):
            errors[field] = f"Enter a price between {minimum} and {maximum} cents."

    selected = payload.get("selected_upgrades")
    if selected is not None:
        if not isinstance(selected, list) or any(item not in [*UPGRADES, "insulation"] for item in selected):
            errors["form"] = "Choose valid improvements for your comparison."
    if not isinstance(payload.get("disconnect_gas", False), bool):
        errors["form"] = "Choose whether to include gas disconnection."

    if errors:
        return None, errors
    return home, {}


def demand_range(category, home):
    """Useful energy demand in kWh/year, before appliance efficiency."""
    demand = REFERENCE["demand"]
    if category == "heating":
        if home["heated_area"] is None:
            return None
        return [float(home["heated_area"]) * rate for rate in demand["heating_kwh_per_m2"]]
    if category == "cooking":
        return [home["occupants"] * rate for rate in demand["cooking_kwh_per_person"]]

    # Heat a daily volume of water, then allow for illustrative system losses.
    yearly_demand = []
    for litres in demand["hot_water_litres_per_person_per_day"]:
        daily_heat_kj = litres * home["occupants"] * demand["water_temperature_rise_c"]
        daily_heat_kj *= demand["water_heat_capacity_kj_per_litre_c"]
        yearly_heat_kwh = daily_heat_kj / 3600 * 365
        yearly_demand.append(yearly_heat_kwh * demand["hot_water_loss_multiplier"])
    return yearly_demand


def appliance_usage(category, appliance, useful_energy, home):
    """Convert demand to purchased energy, costs and operational emissions."""
    efficiency = REFERENCE["efficiency"][category][appliance]
    purchased_energy = [demand / efficiency for demand in useful_energy]
    if appliance == "gas":
        purchased_energy = [energy * 3.6 for energy in purchased_energy]
        price = home["gas_price"] / 100
        emission_factor = REFERENCE["emissions"]["gas_kg_per_mj"]
        unit = "MJ/year"
    else:
        price = home["electricity_price"] / 100
        emission_factor = REFERENCE["emissions"]["electricity_kg_per_kwh"]
        unit = "kWh/year"
    return {
        "energy": purchased_energy,
        "unit": unit,
        "cost": [energy * price for energy in purchased_energy],
        "emissions": [energy * emission_factor for energy in purchased_energy],
    }


def insulation_guidance(home):
    condition = home["insulation"]
    if condition == "not_applicable":
        return "With another home above, ceiling insulation may not be the relevant improvement. Ask about draughts, external walls, shading and any owners-corporation responsibilities."
    if condition in ["none", "poor"]:
        return "Ask the landlord to arrange a professional ceiling-insulation assessment. Confirm suitable materials, electrical safety, access and any applicable standards before installation."
    if condition == "present":
        return "Insulation is present, but its coverage and performance are unverified. If rooms remain uncomfortable, ask about gaps, draughts, window shading and an assessment before adding more."
    return "Ask the landlord or property manager for any existing insulation records. If the condition is unclear, request a professional assessment. Building age alone cannot tell us how well the home is insulated."


def assess_home(home, selected_upgrades=None, disconnect_gas=False):
    """Compare the same low/high demand scenarios before and after upgrades."""
    components = []
    available_upgrades = []
    for category, upgrade in UPGRADES.items():
        appliance = home[category]
        useful_energy = demand_range(category, home)
        supported = appliance in REFERENCE["efficiency"][category] and useful_energy is not None
        can_upgrade = supported and appliance != upgrade["target"]
        if can_upgrade:
            available_upgrades.append(category)
        component = {
            "id": category, **upgrade,
            "current_label": APPLIANCE_LABELS[appliance],
            "supported": supported, "can_upgrade": can_upgrade,
            "selected": False, "current": None, "proposed": None,
            "savings": None, "emissions_savings": None,
        }
        if supported:
            component["current"] = appliance_usage(category, appliance, useful_energy, home)
        else:
            component["reason"] = "This appliance could not be modelled. Identify the system or obtain an individual assessment."
            if category == "heating" and home["heated_area"] is None:
                component["reason"] = "Choose an approximate heated area to include heating in the numerical comparison."
            if appliance == "none":
                component["reason"] = "There is no existing appliance to compare. Adding one needs a separate comfort and running-cost assessment."
            if appliance in ["shared", "solar"]:
                component["reason"] = "Shared and solar hot-water systems need a tailored assessment. Their costs are not included in this subtotal."
        components.append(component)

    insulation_available = home["insulation"] != "not_applicable"
    if insulation_available:
        available_upgrades.append("insulation")
    if selected_upgrades is None:
        selected_upgrades = available_upgrades.copy()
    selected = [item for item in available_upgrades if item in selected_upgrades]

    current_cost = [0.0, 0.0]
    proposed_cost = [0.0, 0.0]
    current_emissions = [0.0, 0.0]
    proposed_emissions = [0.0, 0.0]
    estimated_count = 0
    for component in components:
        category = component["id"]
        component["selected"] = category in selected
        if not component["supported"]:
            continue
        estimated_count += 1
        next_appliance = component["target"] if component["selected"] else home[category]
        component["proposed"] = appliance_usage(category, next_appliance, demand_range(category, home), home)
        component["proposed_label"] = APPLIANCE_LABELS[next_appliance]
        component["savings"] = []
        component["emissions_savings"] = []
        for scenario in range(2):
            current = component["current"]
            proposed = component["proposed"]
            current_cost[scenario] += current["cost"][scenario]
            proposed_cost[scenario] += proposed["cost"][scenario]
            current_emissions[scenario] += current["emissions"][scenario]
            proposed_emissions[scenario] += proposed["emissions"][scenario]
            component["savings"].append(current["cost"][scenario] - proposed["cost"][scenario])
            component["emissions_savings"].append(current["emissions"][scenario] - proposed["emissions"][scenario])

    # Avoid assuming a gas connection can end while any gas use is unresolved.
    known_gas = any(home[category] == "gas" for category in UPGRADES)
    unresolved_gas = home["other_gas"] != "no"
    for category in UPGRADES:
        if home[category] in ["unknown", "other", "shared", "solar"]:
            unresolved_gas = True
    gas_remains = any(home[category] == "gas" and category not in selected for category in UPGRADES)
    can_disconnect = known_gas and not unresolved_gas and not gas_remains
    disconnection_selected = disconnect_gas and can_disconnect
    supply_saving = home["gas_daily_charge"] / 100 * 365 if disconnection_selected else 0
    cost_savings = [current_cost[scenario] - proposed_cost[scenario] for scenario in range(2)]
    total_savings = [saving + supply_saving for saving in cost_savings]
    emission_savings = [current_emissions[scenario] - proposed_emissions[scenario] for scenario in range(2)]

    notes = [
        "Low and high figures are illustrative usage scenarios, not confidence intervals or measurements of your home.",
        "The subtotal excludes cooling, ovens, lighting, refrigeration, other appliances and electricity supply charges. Gas supply savings are shown separately.",
        "Postcode screens for the Victorian pilot only. It does not provide a weather forecast, local climate model or address-level inspection.",
        "Insulation recommendations do not change the cost or emissions calculation.",
    ]
    if estimated_count < 3:
        notes.insert(0, f"Only {estimated_count} of 3 appliance categories could be estimated. Missing components are not treated as zero-cost appliances.")
    if home["solar"] != "no":
        notes.insert(0, "This is a grid-priced illustration. Solar generation, battery storage and feed-in tariffs are not modelled, so these figures do not predict your actual bills.")
    if any(value < 0 for value in emission_savings):
        notes.append("The selected scenario can increase operational emissions using Victoria’s 2025 grid factor. Electrification does not guarantee an immediate emissions reduction.")

    actions = ["Keep a short record of uncomfortable rooms and when the problem occurs, to help explain the request."]
    if home["comfort"] in ["both", "hot"]:
        actions.append("Use existing external shading or close blinds before direct sun enters. Ask about shading and cooling if the home remains too hot.")
    if home["comfort"] in ["both", "cold"]:
        actions.append("Use existing curtains and close doors to unused rooms when heating. Ask about draughts without blocking required ventilation.")
    if home["dwelling"] == "apartment":
        actions.append("Ask the property manager whether equipment locations or shared building systems require owners-corporation approval.")
    actions.append("Check with the landlord before fixed installations and use qualified installers. Do not enter a roof space to inspect insulation yourself.")

    return {
        "home": home, "components": components, "selected_upgrades": selected,
        "estimated_count": estimated_count,
        "totals": {
            "current_cost": current_cost if estimated_count else None,
            "proposed_cost": proposed_cost if estimated_count else None,
            "cost_savings": cost_savings if estimated_count else None,
            "total_savings": total_savings if estimated_count else None,
            "emissions_savings": emission_savings if estimated_count else None,
        },
        "gas_supply": {"eligible": can_disconnect, "selected": disconnection_selected, "annual_saving": supply_saving, "possible_annual_saving": home["gas_daily_charge"] / 100 * 365},
        "insulation": {"available": insulation_available, "selected": "insulation" in selected, "guidance": insulation_guidance(home)},
        "notes": notes, "tenant_actions": actions,
        "assumptions": [
            "Heating useful demand: 60–120 kWh per heated m² per year (project scenarios, not a measured climate profile).",
            "Cooking useful demand: 75–150 kWh per person per year (project scenarios; cooktop only).",
            "Hot water: 35–55 litres per person per day, heated by 45°C, with a 15% system-loss allowance (project assumptions).",
            f"Prices: electricity {home['electricity_price']:g} c/kWh; gas {home['gas_price']:g} c/MJ; gas supply {home['gas_daily_charge']:g} c/day. Edit these to match your bill.",
            "Efficiencies: gas heating 75%; conventional electric heating 100%; reverse cycle COP 3.5. Cooking: gas 40%, conventional electric 74%, induction 90%. Hot water: gas 70%, conventional electric 90%, heat pump COP 2.7.",
            "Operational emissions use 2025 factors: electricity 0.78 kg CO₂e/kWh and gas 0.05153 kg CO₂e/MJ. Upstream and embodied emissions are excluded.",
        ],
        "sources": REFERENCE["sources"], "reviewed_on": REFERENCE["reviewed_on"],
    }
