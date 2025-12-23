"""Constants for Lume Market Maker.

This module supports environment-based defaults controlled by `LUME_ENV`:
- `dev` (default)
- `prod`

You can also override individual fields via environment variables:
- `LUME_API_URL`
- `LUME_CHAIN_ID`
- `LUME_CTF_EXCHANGE_ADDRESS`
- `LUME_NEGRISK_EXCHANGE_ADDRESS`
- `LUME_FEE_RATE_BPS`

Legacy constant names remain available for backward compatibility, but note
they are resolved at import time. For runtime resolution, call
`get_config_with_env_overrides()`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from typing import Literal


LumeEnv = Literal["dev", "prod"]


@dataclass(frozen=True, slots=True)
class LumeEnvConfig:
    api_url: str
    chain_id: int
    ctf_exchange_address: str
    negrisk_exchange_address: str
    fee_rate_bps: int


# -------- Environment configs --------
# NOTE: DEV_CONFIG uses the previously hard-coded values.
DEV_CONFIG = LumeEnvConfig(
    api_url="https://server-graphql-dev.up.railway.app/query",
    chain_id=10143,
    ctf_exchange_address="0x4fEa4E2B6B90f8940ff9A5C7dd75c1299584522D",
    negrisk_exchange_address="0x2cCE4F55DAcab307b48D4d8C1139F1425cCF6759",
    fee_rate_bps=0,
)

# NOTE: Replace placeholders with real production values.
PROD_CONFIG = LumeEnvConfig(
    api_url="https://server-graphql-prod.up.railway.app",
    chain_id=143,
    ctf_exchange_address="0xebe539947016C99D59057Cc68cf9718762Da06E2",
    negrisk_exchange_address="0xD93b8F247893243b56DD56BD996a7677C8050561",
    fee_rate_bps=0,
)


def get_lume_env() -> LumeEnv:
    """Return selected environment from `LUME_ENV` (defaults to `dev`)."""
    raw = (os.getenv("LUME_ENV") or "dev").strip().lower()
    if raw in ("dev", "prod"):
        return raw  # type: ignore[return-value]
    raise ValueError("Invalid LUME_ENV. Expected 'dev' or 'prod'.")


def get_default_config() -> LumeEnvConfig:
    """Return the base config for the selected environment."""
    env = get_lume_env()
    return DEV_CONFIG if env == "dev" else PROD_CONFIG


def _parse_int_env(var_name: str) -> int | None:
    raw = os.getenv(var_name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"Invalid {var_name}: expected an integer") from e


def _parse_str_env(var_name: str) -> str | None:
    raw = os.getenv(var_name)
    if raw is None or raw == "":
        return None
    return raw


def get_config_with_env_overrides() -> LumeEnvConfig:
    """Return selected env config, applying `LUME_*` overrides if present."""
    cfg = get_default_config()

    api_url = _parse_str_env("LUME_API_URL")
    chain_id = _parse_int_env("LUME_CHAIN_ID")
    ctf_exchange_address = _parse_str_env("LUME_CTF_EXCHANGE_ADDRESS")
    negrisk_exchange_address = _parse_str_env("LUME_NEGRISK_EXCHANGE_ADDRESS")
    fee_rate_bps = _parse_int_env("LUME_FEE_RATE_BPS")

    cfg = replace(
        cfg,
        api_url=api_url if api_url is not None else cfg.api_url,
        chain_id=chain_id if chain_id is not None else cfg.chain_id,
        ctf_exchange_address=(
            ctf_exchange_address
            if ctf_exchange_address is not None
            else cfg.ctf_exchange_address
        ),
        negrisk_exchange_address=(
            negrisk_exchange_address
            if negrisk_exchange_address is not None
            else cfg.negrisk_exchange_address
        ),
        fee_rate_bps=fee_rate_bps if fee_rate_bps is not None else cfg.fee_rate_bps,
    )

    # Safety: don't silently run against placeholder prod config.
    if get_lume_env() == "prod":
        placeholders = ("__CHANGE_ME__", 0, "0x0000000000000000000000000000000000000000")
        if (
            cfg.api_url == placeholders[0]
            or cfg.chain_id == placeholders[1]
            or cfg.ctf_exchange_address == placeholders[2]
            or cfg.negrisk_exchange_address == placeholders[2]
        ):
            raise RuntimeError(
                "Production config has placeholders. Set LUME_* overrides "
                "(e.g. LUME_API_URL, LUME_CHAIN_ID, LUME_CTF_EXCHANGE_ADDRESS, "
                "LUME_NEGRISK_EXCHANGE_ADDRESS) or update PROD_CONFIG."
            )

    return cfg


# -------- Legacy names (resolved at import time) --------
_SELECTED_CONFIG = get_config_with_env_overrides()

# Default values
DEFAULT_API_URL = _SELECTED_CONFIG.api_url
DEFAULT_CHAIN_ID = _SELECTED_CONFIG.chain_id

# Exchange addresses
CTF_EXCHANGE_ADDRESS = _SELECTED_CONFIG.ctf_exchange_address
NEGRISK_EXCHANGE_ADDRESS = _SELECTED_CONFIG.negrisk_exchange_address
DEFAULT_FEE_RATE_BPS = _SELECTED_CONFIG.fee_rate_bps

# EIP-712 Domain
DOMAIN_NAME = "Lume CTF Exchange"
DOMAIN_VERSION = "1"

# Order constants
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
ORDER_STRUCTURE_HASH = "Order(uint256 salt,address maker,address signer,address taker,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint256 expiration,uint256 nonce,uint256 feeRateBps,uint8 side,uint8 signatureType)"

# USDC decimals
USDC_DECIMALS = 6

# Signature Types
SIGNATURE_TYPE_EOA = 0
SIGNATURE_TYPE_POLY_PROXY = 1
SIGNATURE_TYPE_POLY_GNOSIS_SAFE = 2
