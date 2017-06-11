Deterministic Bitcoin wallets for multi user Django apps. Internal transactions are made off chain.

Settings
========

Here is a list of variables supported in Django settings:

- BITCOIN_RPC_IP
  - Required
- BITCOIN_RPC_PORT
  - Required
- BITCOIN_RPC_USERNAME
  - Required
- BITCOIN_RPC_PASSWORD
  - Required
- MASTERWALLET_BIP32_KEY
  - Required
- CONFIRMED_THRESHOLD
  - Required
- TESTNET
  - Use testnet instead of real Bitcoin network
  - Optional
- DEFAULT_FEE_SATOSHIS_PER_BYTE
  - Fee that is used when real time fee information is not available
  - Optional
