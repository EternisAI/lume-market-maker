"""GraphQL client for Lume API."""

import json
from typing import Any, Optional

import requests


class GraphQLError(Exception):
    """GraphQL error."""
    pass


class GraphQLClient:
    """Client for making GraphQL requests."""

    def __init__(self, api_url: str, timeout: int = 30):
        """
        Initialize GraphQL client.

        Args:
            api_url: GraphQL API endpoint URL
            timeout: Request timeout in seconds
        """
        self.api_url = api_url
        self.timeout = timeout

    def query(self, query: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Execute a GraphQL query.

        Args:
            query: GraphQL query string
            variables: Query variables

        Returns:
            Query response data

        Raises:
            GraphQLError: If the query fails
        """
        payload = {
            "query": query,
            "variables": variables or {}
        }

        headers = {
            "Content-Type": "application/json"
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                headers=headers,
                timeout=self.timeout
            )
            # Try to get error details before raising
            if not response.ok:
                error_body = response.text
                raise GraphQLError(f"HTTP {response.status_code}: {error_body}")
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            if isinstance(e, requests.exceptions.HTTPError):
                raise  # Re-raise if we already handled it above
            raise GraphQLError(f"Request failed: {e}") from e

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise GraphQLError(f"Failed to parse response: {e}") from e

        if "errors" in result and result["errors"]:
            error_msg = result["errors"][0].get("message", "Unknown error")
            raise GraphQLError(f"GraphQL error: {error_msg}")

        if "data" not in result:
            raise GraphQLError("No data in response")

        return result["data"]

    def mutate(self, mutation: str, variables: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """
        Execute a GraphQL mutation.

        Args:
            mutation: GraphQL mutation string
            variables: Mutation variables

        Returns:
            Mutation response data

        Raises:
            GraphQLError: If the mutation fails
        """
        return self.query(mutation, variables)
