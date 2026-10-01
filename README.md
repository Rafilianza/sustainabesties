# What Does My Home Need?

A local Flask website for Victorian renters. Compare illustrative heating, cooking and hot-water running costs, review insulation guidance and prepare an editable landlord request.

## Run locally

Open a terminal in this `website` folder:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:8000**. Press **Control+C** in the terminal to stop the server. The app runs only on your computer and is not published. Create the virtual environment and install the dependencies after cloning; the virtual environment is not included in Git.

For the competition walkthrough, select **Try an example home**, then **See my options**. Change selected upgrades and prepare a landlord request. The renter view focuses on running costs and comfort; the landlord request identifies the work, indicative installation costs and sources.

## Enable AI drafting

The calculator and personalised template work without an API key. AI drafting is optional and uses the OpenAI API, which needs its own account access and billing; a ChatGPT subscription is not an API credential.

1. Follow the [official OpenAI setup guide](https://developers.openai.com/api/docs/quickstart) to create a project API key and configure your account. Check your project's spending settings before use.
2. In the same terminal that will run Flask, enter the key privately. The following **zsh** commands avoid putting the value in shell history or printing it:

```sh
read -s 'OPENAI_API_KEY?Paste your OpenAI API key: '
export OPENAI_API_KEY
printf '\n'
export OPENAI_MODEL='gpt-4o-mini'
python app.py
```

If the server is already running, stop it first. Never put the key in JavaScript, commit it, or paste it into chat. `.env.example` documents the variable names; the app deliberately does **not** automatically load `.env` files.

3. Generate a letter. The label will say **AI-assisted draft** when the call succeeds. If the key is missing, inaccessible or invalid, or the request times out, the app returns an editable personalised template.

Only fixed, selected improvement topics are sent to OpenAI. The API writes the opening and closing; the app inserts every numerical comparison and source itself. Names, street addresses, postcodes, tariffs and the edited letter are not sent. Responses use `store=False`; the provider's separate data-handling policies still apply. The app never sends the letter to a landlord.

## Understand the code

- `app.py`: serves pages and the two JSON endpoints, with basic local-only request checks.
- `calculations.py`: validates answers and computes energy, costs, emissions and recommendations.
- `letters.py`: assembles the request, optionally using AI for its introductory and closing wording.
- `data/reference.json`: source links, dates, conversion factors, assumptions and illustrative tariffs.
- `templates/`: the assessment and methodology pages.
- `static/`: plain CSS, JavaScript, favicon and the licensed photograph.
- `tests/test_website.py`: checks calculations, validation, API behaviour and drafting fallback.

There is no database, login, frontend framework, build pipeline or browser storage. Reloading clears the current assessment. The methodology links open separately to preserve the form. Installation costs and rebates are not deducted from running costs.

## Endpoints

`POST /api/assessment` accepts JSON containing `home` (the form answers), optional `selected_upgrades` (a list of `heating`, `cooking`, `hot_water`, `insulation`) and `disconnect_gas` (boolean). When selections are omitted, all available improvements are selected. It returns appliance comparisons, totals, guidance, assumptions and sources. Invalid answers return status 400 with an `errors` object keyed by form field.

`POST /api/letter` accepts the same inputs, recalculates independently and returns `letter`, `mode` (`ai` or `template`), `message` and `selected_upgrades`. No browser-supplied result or savings figure is trusted. An empty effective selection returns status 400.

## Model boundaries

Read **How estimates work** in the website for the equations and source notes. Demand presets and some efficiencies are explicitly labelled project assumptions. They are scenarios, not measurements or predictions of an individual home's bills. The postcode is a basic Victorian residential-range check, not a complete locality database or climate lookup.

The totals cover supported heating, cooktop and individual hot-water categories only. Unknown/shared/solar-boosted systems are omitted, not counted as zero. Existing cooling, ovens, lights, refrigeration, solar generation, batteries and electricity supply charges are outside the numerical subtotal. Insulation changes guidance only. No personal health-risk score, property valuation or legal compliance assessment is produced.

Gas fixed-charge savings are separate and counted once only when all gas uses are resolved and ending the connection is selected. Current operational emissions use the **2025** reference factors and can increase in some scenarios. No unconfirmed rebate is deducted. Check current program rules and obtain property-specific quotes before making decisions.

## Run checks

```sh
source .venv/bin/activate
python -m unittest discover -s tests -v
```

All 25 automated checks pass. They mock the AI service and do not spend API credits. Browser checks cover the example flow, selection updates, postcode errors, keyboard operation, letter editing/copying and mobile reflow without horizontal overflow. Live AI access must be confirmed after you configure a valid key.

The in-app browser did not expose working download/print dialogs or page zoom controls during testing. The edited print text was verified, but the final exported files and actual 200% browser zoom remain unverified. Open the local address in Safari or Chrome to check **Download text**, **Print / save PDF**, and 200% zoom. The print stylesheet shows only the edited letter.

## Photo credit

[Fitzroy Greeves Street houses](https://commons.wikimedia.org/wiki/File:Fitzroy_Greeves_Street_houses.jpg), Redtree21, 31 March 2025, [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). The local copy is resized for the page. It does not depict an assessed household.

## Publishing later

Publishing is intentionally deferred. The Flask development server is for local use. A future public version will need production hosting, securely configured secrets, abuse controls and a review of data accuracy and user-facing claims before opening access.
