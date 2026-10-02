"""Run meaningful calculator and API checks with Python's built-in unittest."""

import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app import app
from calculations import REFERENCE, assess_home, validate_payload
from letters import create_letter, get_ai_settings


EXAMPLE = {
    "home": {
        "postcode": "3056", "dwelling": "house", "occupants": 2,
        "heated_area": "60", "heating": "gas", "cooling": "fan",
        "cooking": "gas", "hot_water": "gas", "insulation": "unknown",
        "comfort": "both", "other_gas": "no", "solar": "no",
        "electricity_price": 30, "gas_price": 3, "gas_daily_charge": 100,
    }
}


def example_report(changes=None, selected=None, disconnect=False):
    payload = copy.deepcopy(EXAMPLE)
    if changes:
        payload["home"].update(changes)
    home, errors = validate_payload(payload)
    if errors:
        raise AssertionError(errors)
    return assess_home(home, selected, disconnect)


class CalculationTests(unittest.TestCase):
    def test_gas_units_cost_and_emissions_are_separate(self):
        report = example_report()
        heating = report["components"][0]["current"]
        # Low heating demand is 60 m² × 60 kWh/m², divided by 75% efficiency.
        gas_mj = 60 * 60 / 0.75 * 3.6
        self.assertAlmostEqual(heating["energy"][0], gas_mj)
        self.assertAlmostEqual(heating["cost"][0], gas_mj * 0.03)
        self.assertAlmostEqual(heating["emissions"][0], gas_mj * 0.05153)

    def test_tariff_change_does_not_change_emissions(self):
        original = example_report()
        expensive = example_report({"electricity_price": 100, "gas_price": 10})
        self.assertEqual(original["totals"]["emissions_savings"], expensive["totals"]["emissions_savings"])
        self.assertNotEqual(original["totals"]["cost_savings"], expensive["totals"]["cost_savings"])

    def test_combined_costs_equal_components(self):
        report = example_report()
        for scenario in range(2):
            current = sum(component["current"]["cost"][scenario] for component in report["components"])
            proposed = sum(component["proposed"]["cost"][scenario] for component in report["components"])
            self.assertAlmostEqual(report["totals"]["current_cost"][scenario], current)
            self.assertAlmostEqual(report["totals"]["cost_savings"][scenario], current - proposed)

    def test_unselected_upgrades_do_not_create_savings(self):
        report = example_report(selected=[])
        self.assertEqual(report["totals"]["cost_savings"], [0, 0])
        self.assertEqual(report["selected_upgrades"], [])

    def test_insulation_does_not_change_numbers(self):
        original = example_report(selected=["heating"])
        insulated = example_report({"insulation": "none"}, selected=["heating", "insulation"])
        self.assertEqual(original["totals"], insulated["totals"])

    def test_gas_supply_counted_once_and_separately(self):
        report = example_report(disconnect=True)
        self.assertEqual(report["gas_supply"]["annual_saving"], 365)
        for scenario in range(2):
            difference = report["totals"]["total_savings"][scenario] - report["totals"]["cost_savings"][scenario]
            self.assertAlmostEqual(difference, 365)

    def test_gas_supply_requires_all_gas_uses_resolved(self):
        cases = [
            ({"other_gas": "yes"}, None),
            ({"other_gas": "unknown"}, None),
            ({"hot_water": "shared"}, None),
            ({"hot_water": "solar"}, None),
            ({"cooking": "unknown"}, None),
            ({}, ["heating", "hot_water"]),
        ]
        for changes, selected in cases:
            with self.subTest(changes=changes, selected=selected):
                report = example_report(changes, selected, disconnect=True)
                self.assertFalse(report["gas_supply"]["eligible"])
                self.assertEqual(report["gas_supply"]["annual_saving"], 0)

    def test_unknown_components_are_not_zero_cost(self):
        report = example_report({"heating": "unknown", "cooking": "unknown", "hot_water": "shared"})
        self.assertEqual(report["estimated_count"], 0)
        self.assertIsNone(report["totals"]["current_cost"])
        for component in report["components"]:
            self.assertIsNone(component["current"])

    def test_unknown_heated_area_excludes_only_heating(self):
        report = example_report({"heated_area": "unknown"})
        self.assertEqual(report["estimated_count"], 2)
        self.assertFalse(report["components"][0]["supported"])

    def test_efficient_electric_home_has_no_replacement_saving(self):
        report = example_report({"heating": "heat_pump", "cooking": "induction", "hot_water": "heat_pump"})
        self.assertEqual(report["totals"]["cost_savings"], [0, 0])
        self.assertFalse(report["gas_supply"]["eligible"])

    def test_negative_savings_and_emissions_are_preserved(self):
        report = example_report({"electricity_price": 100, "gas_price": 1}, selected=["cooking"])
        self.assertLess(report["totals"]["cost_savings"][0], 0)
        self.assertLess(report["totals"]["emissions_savings"][0], 0)

    def test_solar_is_labelled_as_grid_illustration(self):
        report = example_report({"solar": "yes"})
        self.assertTrue(any("grid-priced illustration" in note for note in report["notes"]))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_valid_assessment(self):
        response = self.client.post("/api/assessment", json=EXAMPLE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["estimated_count"], 3)

    def test_bad_inputs_return_field_errors(self):
        cases = [("postcode", "2000"), ("occupants", 0), ("occupants", 2.5),
                 ("occupants", True), ("heating", "invented"),
                 ("electricity_price", "nan"), ("gas_price", -1), ("gas_daily_charge", "inf")]
        for field, value in cases:
            with self.subTest(field=field, value=value):
                payload = copy.deepcopy(EXAMPLE)
                payload["home"][field] = value
                response = self.client.post("/api/assessment", json=payload)
                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json["errors"])

    def test_bad_json_and_body_shape(self):
        for body in ["{", "[]", "null", '{"home":[]}', '{"home":{}}']:
            response = self.client.post("/api/assessment", data=body, content_type="application/json")
            self.assertEqual(response.status_code, 400)

    def test_rejects_foreign_origins_and_non_json_requests(self):
        response = self.client.post("/api/letter", json=EXAMPLE, headers={"Origin": "https://elsewhere.example"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.post("/api/assessment", data="test").status_code, 415)

    def test_rejects_unexpected_host(self):
        response = self.client.get("/", headers={"Host": "elsewhere.example"})
        self.assertEqual(response.status_code, 403)

    def test_pages_and_assets(self):
        for path in ["/", "/methodology", "/static/app.js", "/static/style.css", "/static/fitzroy-homes.jpg"]:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["X-Robots-Tag"], "noindex, nofollow")
                response.close()

    @patch.dict(os.environ, {}, clear=True)
    def test_letter_without_key_uses_template(self):
        response = self.client.post("/api/letter", json=EXAMPLE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["mode"], "template")
        self.assertIn("[Your name]", response.json["letter"])

    @patch.dict(os.environ, {}, clear=True)
    def test_letter_recalculates_instead_of_trusting_browser_totals(self):
        payload = copy.deepcopy(EXAMPLE)
        payload["totals"] = {"savings": 9999999}
        response = self.client.post("/api/letter", json=payload)
        self.assertNotIn("9999999", response.json["letter"])

    def test_letter_rejects_empty_selection(self):
        response = self.client.post("/api/letter", json={**EXAMPLE, "selected_upgrades": []})
        self.assertEqual(response.status_code, 400)


class DraftingTests(unittest.TestCase):
    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-sent"}, clear=True)
    @patch("letters.OpenAI")
    def test_ai_changes_prose_but_not_evidence(self, mock_client):
        mock_client.return_value.responses.create.return_value = SimpleNamespace(output_text=json.dumps({
            "opening": "I would like to discuss the practical improvements listed below.",
            "closing": "Could we arrange a suitable time to discuss a professional quote?"
        }))
        report = example_report()
        draft = create_letter(report)
        self.assertEqual(draft["mode"], "ai")
        self.assertIn("Current running costs $518–$1,037/year", draft["letter"])
        self.assertIn("not a financial return to the property owner", draft["letter"])
        arguments = mock_client.return_value.responses.create.call_args.kwargs
        self.assertFalse(arguments["store"])
        self.assertNotIn("3056", arguments["input"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-sent"}, clear=True)
    @patch("letters.OpenAI")
    def test_unsupported_ai_claim_uses_template(self, mock_client):
        mock_client.return_value.responses.create.return_value = SimpleNamespace(output_text=json.dumps({
            "opening": "The property will be worth $1000000 after these improvements.",
            "closing": "Please arrange the proposed assessment when convenient."
        }))
        draft = create_letter(example_report())
        self.assertEqual(draft["mode"], "template")
        self.assertNotIn("1000000", draft["letter"])

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-sent"}, clear=True)
    @patch("letters.OpenAI")
    def test_malformed_ai_response_uses_template(self, mock_client):
        mock_client.return_value.responses.create.return_value = SimpleNamespace(output_text="not json")
        self.assertEqual(create_letter(example_report())["mode"], "template")

    @patch.dict(os.environ, {"OPENAI_API_KEY": "test-key-never-sent"}, clear=True)
    @patch("letters.OpenAI")
    def test_api_failure_uses_template_without_error_details(self, mock_client):
        from openai import APIConnectionError
        mock_client.return_value.responses.create.side_effect = APIConnectionError(request=None)
        draft = create_letter(example_report())
        self.assertEqual(draft["mode"], "template")
        self.assertNotIn("test-key-never-sent", str(draft))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.prose = json.dumps({
            "opening": "I would like to discuss the practical improvements listed below.",
            "closing": "Could we arrange a suitable time to discuss a professional quote?",
        })

    @patch("letters.OpenAI")
    def test_compatible_providers_route_to_the_right_endpoint(self, mock_client):
        endpoints = {
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "deepseek": "https://api.deepseek.com/v1",
            "qwen": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
            "custom": "https://example.com/v1",
        }
        for provider, endpoint in endpoints.items():
            with self.subTest(provider=provider):
                mock_client.reset_mock()
                mock_client.return_value.chat.completions.create.return_value = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=self.prose))]
                )
                environment = {
                    "AI_PROVIDER": provider, "AI_API_KEY": "selected-provider-key",
                    "AI_MODEL": "chosen-model", "OPENAI_API_KEY": "wrong-provider-key",
                }
                if provider == "custom":
                    environment["AI_BASE_URL"] = endpoint
                with patch.dict(os.environ, environment, clear=True):
                    draft = create_letter(example_report())
                self.assertEqual(draft["mode"], "ai")
                self.assertIn("Current running costs $518–$1,037/year", draft["letter"])
                self.assertEqual(mock_client.call_args.kwargs["base_url"], endpoint)
                self.assertEqual(mock_client.call_args.kwargs["api_key"], "selected-provider-key")
                arguments = mock_client.return_value.chat.completions.create.call_args.kwargs
                self.assertEqual(arguments["model"], "chosen-model")
                self.assertEqual(arguments["response_format"], {"type": "json_object"})
                self.assertNotIn("store", arguments)
                self.assertNotIn("3056", arguments["messages"][1]["content"])
                self.assertNotIn("selected-provider-key", str(draft))
                mock_client.return_value.responses.create.assert_not_called()

    @patch.dict(os.environ, {"AI_PROVIDER": "gemini", "OPENAI_API_KEY": "wrong-key"}, clear=True)
    @patch("letters.OpenAI")
    def test_missing_provider_key_never_borrows_openai_key(self, mock_client):
        self.assertEqual(create_letter(example_report())["mode"], "template")
        mock_client.assert_not_called()

    def test_generic_settings_and_provider_specific_fallbacks(self):
        for provider in ["openai", "gemini", "deepseek", "qwen"]:
            with self.subTest(provider=provider):
                environment = {
                    "AI_PROVIDER": provider, "AI_API_KEY": "", "AI_MODEL": "",
                    f"{provider.upper()}_API_KEY": "provider-key",
                    f"{provider.upper()}_MODEL": "provider-model",
                }
                with patch.dict(os.environ, environment, clear=True):
                    self.assertEqual(get_ai_settings()["api_key"], "provider-key")
                    self.assertEqual(get_ai_settings()["model"], "provider-model")
                    with patch.dict(os.environ, {"AI_API_KEY": "generic-key", "AI_MODEL": "generic-model"}):
                        self.assertEqual(get_ai_settings()["api_key"], "generic-key")
                        self.assertEqual(get_ai_settings()["model"], "generic-model")

    @patch.dict(os.environ, {"AI_PROVIDER": "qwen", "AI_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1"}, clear=True)
    def test_region_endpoint_override(self):
        self.assertEqual(get_ai_settings()["base_url"], "https://dashscope.aliyuncs.com/compatible-mode/v1")

    @patch("letters.OpenAI")
    def test_invalid_settings_fall_back_without_a_request(self, mock_client):
        cases = [
            {"AI_PROVIDER": "typo"},
            {"AI_PROVIDER": "custom"},
            {"AI_PROVIDER": "gemini", "AI_API_KEY": "test-key"},
            {"AI_BASE_URL": "http://remote.example/v1"},
            {"AI_BASE_URL": "https://user:secret@example.com/v1"},
            {"AI_BASE_URL": "https://example.com/v1?key=secret"},
            {"AI_BASE_URL": "https://[invalid"},
            {"AI_JSON_MODE": "invalid"},
        ]
        for environment in cases:
            with self.subTest(environment=environment):
                with patch.dict(os.environ, environment, clear=True):
                    draft = create_letter(example_report())
                self.assertEqual(draft["mode"], "template")
                self.assertNotIn("secret", draft["message"])
        mock_client.assert_not_called()

    @patch.dict(os.environ, {"AI_PROVIDER": "custom", "AI_BASE_URL": "http://localhost:11434/v1", "AI_API_KEY": "local", "AI_MODEL": "local-model", "AI_JSON_MODE": "false"}, clear=True)
    @patch("letters.OpenAI")
    def test_custom_endpoint_without_json_mode_accepts_fenced_json(self, mock_client):
        mock_client.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"```json\n{self.prose}\n```"))]
        )
        self.assertEqual(create_letter(example_report())["mode"], "ai")
        arguments = mock_client.return_value.chat.completions.create.call_args.kwargs
        self.assertNotIn("response_format", arguments)

    @patch.dict(os.environ, {"AI_PROVIDER": "gemini", "AI_API_KEY": "test-key", "AI_MODEL": "gemini-3.1-flash-lite"}, clear=True)
    @patch("letters.OpenAI")
    def test_empty_refused_or_malformed_chat_responses_use_template(self, mock_client):
        for response in [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="not JSON"))]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='{"opening": "Pay $500 now", "closing": "Please consider it."}'))]),
        ]:
            mock_client.return_value.chat.completions.create.return_value = response
            self.assertEqual(create_letter(example_report())["mode"], "template")

    @patch.dict(os.environ, {"AI_PROVIDER": "deepseek", "AI_API_KEY": "private-test-key", "AI_MODEL": "chosen-model"}, clear=True)
    @patch("letters.OpenAI")
    def test_compatible_api_failure_does_not_expose_provider_error(self, mock_client):
        from openai import APIConnectionError
        mock_client.return_value.chat.completions.create.side_effect = APIConnectionError(
            request=None, message="Error containing private-test-key"
        )
        draft = create_letter(example_report())
        self.assertEqual(draft["mode"], "template")
        self.assertNotIn("private-test-key", str(draft))


if __name__ == "__main__":
    unittest.main()
