# bittensor-tools

Python helpers and a small CLI for **subnet registration** (PoW or burn), **watching registration**, **recycle cost**, and **publishing an axon** for mining.

## Install

```bash
pip install -e .
```

Requires a normal Bittensor wallet under `~/.bittensor/wallets/`.

The SDK loads chain defaults from the environment; this package sets `BT_NO_PARSE_CLI_ARGS=1` so `AsyncSubtensor` does not consume your process `argv`.

## CLI

Commands: `bttools` or `subnet-tools` (same entry point).

```bash
bttools status --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1
bttools watch --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 --interval 15
bttools register --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 --method burn
bttools register --method pow --cuda   # PoW path; needs torch / optional CUDA
bttools recycle-cost --netuid 1
bttools serve --wallet-name MY_COLDKEY --hotkey MY_HOTKEY --netuid 1 \
  --external-ip 203.0.113.10 --external-port 8091
```

`serve` only submits the on-chain axon advertisement; you still run your miner/Axon process that listens on the advertised host/port.

## Library

```python
import asyncio
from bittensor_tools.registration import fetch_registration_status, watch_registration
from bittensor_tools.wallet_util import load_wallet
import bittensor_tools.compat  # before AsyncSubtensor if you construct it yourself
from bittensor.core.async_subtensor import AsyncSubtensor

async def main():
    wallet = load_wallet("MY_COLDKEY", "MY_HOTKEY")
    async with AsyncSubtensor(network="finney") as s:
        print(await fetch_registration_status(s, 1, wallet.hotkey.ss58_address))

asyncio.run(main())
```