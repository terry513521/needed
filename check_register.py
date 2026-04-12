import bittensor as bt
# Replace below with your SS58 hotkey
hotkey = "5DytZi763sJVX7HuPVxrKRX8N7bciiTP13azwU9zr86rHUki"
network = "finney"
netuid = 47 # subnet uid
sub = bt.Subtensor(network)
mg = sub.metagraph(netuid)
if hotkey not in mg.hotkeys:
  print(f"Hotkey {hotkey} deregistered")
else:
  print(f"Hotkey {hotkey} is registered")