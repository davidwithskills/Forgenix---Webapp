import os
import tempfile
import unittest
from unittest.mock import Mock, patch

TEST_DIRECTORY = tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"] = os.path.join(TEST_DIRECTORY.name, "test.sqlite3")
os.environ["SECRET_KEY"] = "test-key-not-for-production"

import app


class ForgenixAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app.app.config.update(TESTING=True)

    def setUp(self):
        with app.connect_db() as connection:
            connection.execute("DELETE FROM payments")
            connection.execute("DELETE FROM learner_state")
            connection.execute("DELETE FROM users")
        self.client = app.app.test_client()

    @classmethod
    def tearDownClass(cls):
        TEST_DIRECTORY.cleanup()

    def register(self, email="learner@example.com", password="correct-horse-42"):
        return self.client.post(
            "/api/auth/register",
            json={
                "email": email,
                "password": password,
                "state": {
                    "goal": "Software Engineering",
                    "hours": 4,
                    "completed": {"Software Engineering": ["foundation"]},
                },
            },
        )

    def test_guest_can_read_original_learning_paths(self):
        response = self.client.get("/static/paths.json")
        self.assertEqual(response.status_code, 200)
        paths = response.get_json()
        response.close()
        self.assertEqual(set(paths), set(app.LEARNING_PATHS))
        for path in paths.values():
            self.assertEqual(len(path["modules"]), 4)
            self.assertTrue(all(module["activity"] and module["checklist"] for module in path["modules"]))

    def test_registration_login_and_progress_sync(self):
        created = self.register()
        self.assertEqual(created.status_code, 201)
        self.assertTrue(created.get_json()["authenticated"])
        self.assertEqual(
            self.client.get("/api/auth/me").get_json()["state"]["completed"]["Software Engineering"],
            ["foundation"],
        )

        self.client.post("/api/auth/logout", json={})
        denied = self.client.post(
            "/api/auth/login",
            json={"email": "learner@example.com", "password": "wrong-password"},
        )
        self.assertEqual(denied.status_code, 401)

        logged_in = self.client.post(
            "/api/auth/login",
            json={"email": "learner@example.com", "password": "correct-horse-42"},
        )
        self.assertEqual(logged_in.status_code, 200)
        synced = self.client.post(
            "/api/state",
            json={
                "state": {
                    "goal": "Software Engineering",
                    "hours": 7,
                    "completed": {"Software Engineering": ["foundation", "project"]},
                }
            },
        )
        self.assertEqual(synced.status_code, 200)
        self.assertEqual(
            self.client.get("/api/auth/me").get_json()["state"]["completed"]["Software Engineering"],
            ["foundation", "project"],
        )

    def test_progress_rejects_unknown_learning_modules(self):
        self.register()
        response = self.client.post(
            "/api/state",
            json={
                "state": {
                    "goal": "Cybersecurity",
                    "hours": 4,
                    "completed": {"Cybersecurity": ["unauthorized-module"]},
                }
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_payment_requires_account_and_verified_callback_updates_subscription(self):
        anonymous = self.client.post("/api/start-payment", json={"plan": "pro_monthly"})
        self.assertEqual(anonymous.status_code, 401)

        self.register()
        checkout = self.client.post("/api/start-payment", json={"plan": "pro_monthly"})
        self.assertEqual(checkout.status_code, 200)
        checkout_data = checkout.get_json()
        self.assertEqual(checkout_data["fields"]["cust_email"], "learner@example.com")
        self.assertEqual(
            checkout_data["fields"]["amount"], str(app.PRO_PRICE_NAIRA * 100)
        )
        reference = checkout_data["fields"]["txn_ref"]
        payment_response = Mock()
        payment_response.json.return_value = {
            "ResponseCode": "00",
            "Amount": str(app.PRO_PRICE_NAIRA * 100),
        }
        with patch("app.requests.get", return_value=payment_response) as query:
            completed = self.client.get(
                "/payment-response", query_string={"txnref": reference}
            )
        self.assertEqual(completed.status_code, 303)
        query.assert_called_once()
        account = self.client.get("/api/auth/me").get_json()
        self.assertGreater(account["pro_until"], 0)
        duplicate = self.client.get(
            "/payment-response", query_string={"txnref": reference}
        )
        self.assertEqual(duplicate.status_code, 303)
        self.assertEqual(self.client.get("/api/auth/me").get_json()["pro_until"], account["pro_until"])
        self.assertTrue(self.client.get("/api/status").get_json()["pro"])

    def test_public_config_does_not_expose_payment_credentials(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["payment_mode"], "TEST")
        self.assertEqual(response.get_json()["pro_price_naira"], app.PRO_PRICE_NAIRA)
        self.assertNotIn("merchant", response.get_json())
        landing_config = self.client.get(
            "/api/config",
            headers={"Origin": "https://davidwithskills.github.io"},
        )
        self.assertEqual(
            landing_config.headers["Access-Control-Allow-Origin"],
            "https://davidwithskills.github.io",
        )


if __name__ == "__main__":
    unittest.main()
