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

## Choose an AI provider and model

AI is optional. Without a key, the calculator and editable template letters still work.
The app supports OpenAI, Gemini (Google AI Studio), DeepSeek, Qwen (Alibaba Cloud Model Studio), and other **OpenAI-compatible Chat Completions** endpoints. It uses the existing OpenAI Python SDK for the compatible providers; selecting Gemini sends the request to Google, not OpenAI.

1. Open `.env` in this folder. After cloning, copy `.env.example` to `.env` first.
2. Set the provider, its API key and the exact model ID together. For Gemini:

```dotenv
AI_PROVIDER=gemini
AI_API_KEY=your_gemini_api_key
AI_MODEL=gemini-3.1-flash-lite
AI_BASE_URL=
AI_JSON_MODE=true
```

For OpenAI, use `AI_PROVIDER=openai` and, for example, `AI_MODEL=gpt-4o-mini` with an OpenAI API key. For DeepSeek or Qwen, select that provider and enter a model ID available in its API console. These are API keys, not chat website subscriptions or passwords. Model access and billing depend on the selected provider.

| AI_PROVIDER | Default API base URL | API used |
| --- | --- | --- |
| `openai` | `https://api.openai.com/v1` | Responses |
| `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Chat Completions |
| `deepseek` | `https://api.deepseek.com/v1` | Chat Completions |
| `qwen` | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` | Chat Completions |
| `custom` | Set `AI_BASE_URL` yourself | Chat Completions |

Qwen's preset is Singapore. Set `AI_BASE_URL` to the endpoint matching your Alibaba Cloud account region/workspace when different. Gemini's preset is for the Gemini Developer API; it does not implement Vertex AI authentication.

For another compatible provider:

```dotenv
AI_PROVIDER=custom
AI_API_KEY=your_provider_api_key
AI_MODEL=your_exact_model_id
AI_BASE_URL=https://your-provider.example/v1
AI_JSON_MODE=true
```

Use the **base URL**, not the full `/chat/completions` URL. The custom server must accept bearer-key authentication and the OpenAI Chat Completions request/response format, including system/user messages and `max_tokens`. APIs using a different native format need a separate adapter. HTTP is accepted for localhost servers; for a local server without authentication, use a non-secret placeholder such as `AI_API_KEY=local`.

Set `AI_JSON_MODE=false` only if your endpoint rejects `response_format`. The prompt still requests JSON and the app validates it. Requests have a 30-second timeout, no automatic retries and a 2,048-token output limit. Refused, truncated or invalid responses fall back to the template. Reasoning-heavy models may need a different token limit in `letters.py`; a short text-drafting model is the simplest fit.

3. Save `.env`, stop Flask with **Control+C**, and restart with `python app.py`.
4. Prepare a letter. Its status identifies the provider when AI succeeds. A missing key, configuration error or provider failure gives an editable template instead. No request is sent to an alternative provider automatically.

### Existing keys and setting precedence

Your existing private `.env` values are preserved. Old `OPENAI_API_KEY` and `OPENAI_MODEL` settings still work with `AI_PROVIDER=openai` (also the default if unset). Equivalent `GEMINI_API_KEY` / `GEMINI_MODEL`, `DEEPSEEK_API_KEY` / `DEEPSEEK_MODEL`, and `QWEN_API_KEY` / `QWEN_MODEL` are supported for their selected providers.

Non-empty `AI_API_KEY` and `AI_MODEL` take priority over provider-specific variables. Keep them blank if you want to store separate provider-specific keys/models and switch with just `AI_PROVIDER`. A Gemini selection never falls back to an `OPENAI_API_KEY`. Non-OpenAI providers require an explicit model ID; OpenAI defaults to `gpt-4o-mini` if no model is set. Variables already exported in your terminal take priority over `.env` values; restart in a fresh terminal or unset old exports if needed.

`.env` is ignored by Git. Never put a key in browser code or paste it into chat. Only fixed, selected improvement topics go to the configured provider. Names, street addresses, postcodes, tariffs and the edited letter are not sent. AI writes the opening and closing; the app inserts calculations and sources locally. OpenAI requests use `store=False`; other providers have their own storage controls and policies. The app never sends the letter to a landlord.

The provider selection and API calls are in `letters.py`, in `get_ai_settings()` and `draft_prose()`. No additional dependencies were needed for the provider support.

Official integration references: [OpenAI Responses](https://developers.openai.com/api/reference/cli/resources/responses/methods/create), [Gemini compatibility](https://ai.google.dev/gemini-api/docs/openai), [Gemini model](https://ai.google.dev/gemini-api/docs/models/gemini-3.1-flash-lite), [DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/), [Qwen regional endpoints](https://help.aliyun.com/en/model-studio/base-url).

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

The automated checks mock the AI services and do not spend API credits. They cover provider routing, key isolation, configuration precedence, custom endpoints, malformed responses and fallback, alongside the calculation and endpoint tests. Browser checks cover the example flow, selection updates, postcode errors, keyboard operation, letter editing/copying and mobile reflow without horizontal overflow. Live AI access must be confirmed after you configure a valid key.

The in-app browser did not expose working download/print dialogs or page zoom controls during testing. The edited print text was verified, but the final exported files and actual 200% browser zoom remain unverified. Open the local address in Safari or Chrome to check **Download text**, **Print / save PDF**, and 200% zoom. The print stylesheet shows only the edited letter.

## Photo credit

[Fitzroy Greeves Street houses](https://commons.wikimedia.org/wiki/File:Fitzroy_Greeves_Street_houses.jpg), Redtree21, 31 March 2025, [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). The local copy is resized for the page. It does not depict an assessed household.

## Publishing later

Publishing is intentionally deferred. The Flask development server is for local use. A future public version will need production hosting, securely configured secrets, abuse controls and a review of data accuracy and user-facing claims before opening access.
