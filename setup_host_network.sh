#!/bin/bash

# This script sets up the host network to allow gVisor sandboxes to access
# the internet via a TAP device. It needs to be run as root/sudo.

set -e

# 1. Find the host's main internet interface.
# We'll search for the default route and extract the interface name.
YOUR_IF=$(ip route | grep default | awk '{print $5}')

if [ -z "$YOUR_IF" ]; then
    echo "Could not determine the default network interface."
    echo "Please set YOUR_IF manually and re-run."
    exit 1
fi

echo "Using network interface: $YOUR_IF"

# 2. Create the TAP device.
echo "Creating and configuring tap0 device..."
# Create the 'tap0' device and assign ownership to the current user.
# If you run the main application as a different user, change $(whoami).
sudo ip tuntap add dev tap0 mode tap user $(whoami)

# Assign an IP address to this device (this will be the sandbox's gateway).
sudo ip addr add 192.168.250.1/24 dev tap0

# Bring the device up.
sudo ip link set tap0 up
echo "tap0 device is up."

# 3. Enable IP Forwarding.
echo "Enabling IP forwarding..."
sudo sysctl -w net.ipv4.ip_forward=1
echo "IP forwarding enabled."

# 4. Configure NAT (Masquerading).
echo "Configuring iptables for NAT..."
# Set up the NAT rule to masquerade traffic from the sandbox subnet.
sudo iptables -t nat -A POSTROUTING -o $YOUR_IF -j MASQUERADE

# Allow forwarding from tap0 to your main interface.
sudo iptables -A FORWARD -i tap0 -o $YOUR_IF -j ACCEPT

# Allow forwarding for established connections back in.
sudo iptables -A FORWARD -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
echo "iptables rules configured."

echo -e "\nHost network setup is complete."
echo "You can now start the application."
echo "To tear down this configuration, you can reboot or manually reverse these commands."
