"""Safe transaction executor for merging outcome tokens."""

import json
import os
from pathlib import Path

from eth_account import Account
from eth_account.signers.local import LocalAccount
from safe_eth.eth import EthereumClient
from safe_eth.safe import Safe
from web3 import Web3


def _load_abi(filename: str) -> list:
    """Load ABI from the abis folder."""
    abis_dir = Path(__file__).parent.parent / "abis"
    with open(abis_dir / filename) as f:
        return json.load(f)


CTF_ABI = _load_abi("ctf_abi.json")
NEG_RISK_ADAPTER_ABI = _load_abi("neg_risk_adapter_abi.json")


class SafeExecutor:
    """Execute transactions via Gnosis Safe."""

    def __init__(self, private_key: str, safe_address: str, rpc_url: str):
        """
        Initialize the SafeExecutor.

        Args:
            private_key: Private key of an owner of the Safe
            safe_address: Address of the Gnosis Safe
            rpc_url: RPC URL for the blockchain
        """
        if not private_key.startswith("0x"):
            private_key = f"0x{private_key}"

        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        self.ethereum_client = EthereumClient(rpc_url)
        self.account: LocalAccount = Account.from_key(private_key)
        self.safe_address = Web3.to_checksum_address(safe_address)
        self.safe = Safe(self.safe_address, self.ethereum_client)

    def get_token_balances(
        self, ctf_address: str, owner: str, token_ids: list[int]
    ) -> list[int]:
        """
        Query balanceOfBatch for multiple token IDs.

        Args:
            ctf_address: Address of the CTF contract
            owner: Address to check balances for
            token_ids: List of ERC-1155 token IDs

        Returns:
            List of balances corresponding to each token ID
        """
        ctf = self.w3.eth.contract(
            address=Web3.to_checksum_address(ctf_address), abi=CTF_ABI
        )
        owners = [Web3.to_checksum_address(owner)] * len(token_ids)
        return ctf.functions.balanceOfBatch(owners, token_ids).call()

    def execute_merge_ctf(
        self,
        ctf_address: str,
        collateral_token: str,
        condition_id: str,
        amount: int,
    ) -> str:
        """
        Build and execute CTF mergePositions via Safe.

        Args:
            ctf_address: Address of the CTF contract
            collateral_token: Address of the collateral token (e.g., USDC)
            condition_id: Condition ID (hex string with 0x prefix)
            amount: Amount of tokens to merge (in atomic units)

        Returns:
            Transaction hash as hex string
        """
        ctf = self.w3.eth.contract(
            address=Web3.to_checksum_address(ctf_address), abi=CTF_ABI
        )

        # Convert condition_id from hex string to bytes32
        condition_id_bytes = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)

        # parentCollectionId = bytes32(0)
        # partition = [1, 2] for binary markets
        calldata = ctf.encode_abi(
            abi_element_identifier="mergePositions",
            args=[
                Web3.to_checksum_address(collateral_token),
                bytes(32),  # parentCollectionId = 0x00...00
                condition_id_bytes,
                [1, 2],  # partition for binary markets
                amount,
            ],
        )
        return self._exec_safe_tx(ctf_address, calldata)

    def execute_merge_neg_risk(
        self,
        adapter_address: str,
        condition_id: str,
        amount: int,
    ) -> str:
        """
        Build and execute NegRisk mergePositions via Safe.

        Args:
            adapter_address: Address of the NegRisk adapter
            condition_id: Condition ID (hex string with 0x prefix)
            amount: Amount of tokens to merge (in atomic units)

        Returns:
            Transaction hash as hex string
        """
        adapter = self.w3.eth.contract(
            address=Web3.to_checksum_address(adapter_address), abi=NEG_RISK_ADAPTER_ABI
        )

        # Convert condition_id from hex string to bytes32
        condition_id_bytes = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)

        calldata = adapter.encode_abi(
            abi_element_identifier="mergePositions",
            args=[condition_id_bytes, amount],
        )
        return self._exec_safe_tx(adapter_address, calldata)

    def _exec_safe_tx(self, to: str, data: str) -> str:
        """
        Build, sign, and execute a Safe transaction.

        Args:
            to: Target contract address
            data: Encoded calldata

        Returns:
            Transaction hash as hex string
        """
        to_address = Web3.to_checksum_address(to)

        # Build the Safe transaction
        safe_tx = self.safe.build_multisig_tx(
            to=to_address,
            value=0,
            data=bytes.fromhex(data[2:]) if data.startswith("0x") else bytes.fromhex(data),
            operation=0,  # CALL
        )

        # Sign the transaction
        safe_tx.sign(self.account.key.hex())

        # Execute the transaction
        tx_hash, _ = safe_tx.execute(self.account.key.hex())

        return tx_hash.hex() if hasattr(tx_hash, "hex") else str(tx_hash)
