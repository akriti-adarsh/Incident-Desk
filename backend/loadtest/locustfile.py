"""Load test for the incident list and create endpoints.

Run against the compose stack:

    uv run locust -f loadtest/locustfile.py --host http://localhost:8000 \
        --users 50 --spawn-rate 25 --run-time 30s --headless

Each simulated user logs in once as a seeded account, then loops: mostly
listing incidents (the hot read path) with occasional creates. Percentile
latencies are reported by locust; the captured numbers live in
docs/performance.md.
"""

import random

from locust import HttpUser, between, task

SEED_PASSWORD = "incident-desk-demo-9"
# Seeded accounts that can both read and create in their org.
ACCOUNTS = [
    ("ada@example.com", "northwind"),
    ("chen@example.com", "atlas"),
    ("farah@example.com", "helios"),
]


class IncidentUser(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        self.email, self.org = random.choice(ACCOUNTS)
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": SEED_PASSWORD},
            name="POST /auth/login",
        )
        self.token = response.json()["data"]["access_token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}
        services = self.client.get(
            f"/api/v1/orgs/{self.org}/services",
            headers=self.headers,
            name="GET /services",
        )
        self.service_id = services.json()["data"][0]["id"]

    @task(9)
    def list_incidents(self) -> None:
        self.client.get(
            f"/api/v1/orgs/{self.org}/incidents",
            headers=self.headers,
            name="GET /incidents (list)",
        )

    @task(3)
    def search_incidents(self) -> None:
        self.client.get(
            f"/api/v1/orgs/{self.org}/incidents",
            params={"q": random.choice(["latency", "deploy", "cache", "timeout"])},
            headers=self.headers,
            name="GET /incidents (search)",
        )

    @task(1)
    def create_incident(self) -> None:
        self.client.post(
            f"/api/v1/orgs/{self.org}/incidents",
            headers=self.headers,
            json={
                "service_id": self.service_id,
                "title": f"Load test {random.randint(1, 1_000_000)}",
                "severity": random.choice(["sev2", "sev3", "sev4"]),
            },
            name="POST /incidents (create)",
        )
