import bittensor as bt
# Replace below with your SS58 hotkey
hotkey = "5DyNeD2rhcavsHQRnrNPLBkaiceavrqqAVCZkCATsSQt2sTR"
network = "finney"
netuid = 100 # subnet uid
sub = bt.Subtensor(network)
mg = sub.metagraph(netuid)
if hotkey not in mg.hotkeys:
  print(f"Hotkey {hotkey} deregistered")
else:
  print(f"Hotkey {hotkey} is registered")